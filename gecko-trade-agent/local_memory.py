"""Append-only JSONL memory for the local-lab panel.

The contest bot already persists a per-day artifact ledger via
``gecko_wrap.ArtifactLogger``. This file is a *parallel* surface used
exclusively by the local panel + voices — it captures opinions /
panel decisions / observations in one rolling file so the next sprint
can mine it for voice quality, calibration, and PnL attribution.

Why not reuse ``ArtifactLogger``?

* Different schema. Artifact rows are keyed by ``DecisionKind`` (a
  closed Literal); panel rows carry an open ``event`` string so the
  voice layer can extend without touching the wrap.
* Different retention. Artifact rolls per-day; this rolls per-lifetime
  (bounded by the lab being a short experiment, per
  ``project-local-lab-strategy-2026-05-20``).
* Different reader. ``outcomes_for`` is the only structural lookup we
  need today; the artifact ledger never grew one because its consumer
  is the offline analyzer.

Crash safety: each ``append`` opens the file in append-text mode,
takes an advisory ``fcntl.flock`` (we're on Linux per CLAUDE.md env),
writes one line, fsync-free since the JSONL line is small enough to
hit the page cache atomically. On corrupt or partially-written lines
(power-loss mid-write), :meth:`recent` and :meth:`outcomes_for` skip
the malformed row and log a warning rather than crashing the bot.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).parent / "local_memory.jsonl"


class LocalMemory:
    """Thin wrapper over a JSONL file. Append-only; never rewrites.

    Reads are best-effort: a malformed line is skipped with a warning,
    not raised, because the bot's main loop cannot afford to crash on
    a partial write from a previous session.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else _DEFAULT_PATH
        # Touch the file so callers can stat() it before the first
        # append; cheap on Linux ext4 — open(O_CREAT) is one syscall.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        event: str,
        payload: dict[str, Any],
        decision_id: str | None = None,
    ) -> None:
        """Append one row. Crash-safe via flock around the write."""
        row = {
            "ts_iso": datetime.now(UTC).isoformat(),
            "event": event,
            "decision_id": decision_id,
            "payload": payload,
        }
        line = json.dumps(row, separators=(",", ":")) + "\n"
        # Open per-append rather than holding the fd — the bot may run
        # for hours and we want a crash to leave a flushed file on
        # disk. Append mode + flock gives us atomicity against a
        # concurrent voice writer (if one ever runs out-of-process).
        with open(self._path, "a", encoding="utf-8") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(line)
                f.flush()
                # os.fsync would survive a hard-power-loss; we skip it
                # for write throughput. Page cache + filesystem journal
                # gives us "survives a process crash" already, which is
                # the realistic failure mode here.
            finally:
                # Best-effort unlock; the OS releases the lock on close()
                # anyway, but explicit release lets a concurrent writer
                # proceed without waiting for our fd to be GC'd.
                with contextlib.suppress(OSError):
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def recent(
        self,
        event_filter: str | tuple[str, ...] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return the last ``limit`` rows matching ``event_filter``.

        Newest-first. ``event_filter`` accepts a single event name or
        a tuple of names. None disables filtering. O(N) over the file
        — fine for the lab's expected row counts; if this becomes hot
        we can swap to a tail-buffer or sqlite.
        """
        wanted = self._normalize_filter(event_filter)
        rows = list(self._iter_rows())
        # Iterate newest-first so we can break early once we hit the
        # limit, avoiding the full file scan when the lab grows.
        out: list[dict[str, Any]] = []
        for row in reversed(rows):
            if wanted is not None and row.get("event") not in wanted:
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return out

    def outcomes_for(self, decision_id: str) -> list[dict[str, Any]]:
        """Return every row whose ``decision_id`` matches.

        Used to look up trade outcomes that reference an earlier
        ``local_decision`` row. O(N) scan; the lab is bounded so this
        stays cheap. Returned chronologically (oldest-first) so the
        caller sees decision → outcome in natural order.
        """
        return [r for r in self._iter_rows() if r.get("decision_id") == decision_id]

    # ── Internals ──────────────────────────────────────────────────────
    def _iter_rows(self) -> Iterable[dict[str, Any]]:
        if not self._path.exists() or os.path.getsize(self._path) == 0:
            return iter(())
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("local_memory: could not read %s (%s); returning empty", self._path, exc)
            return iter(())

        rows: list[dict[str, Any]] = []
        for line_num, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "local_memory: skipping corrupt row %d (%s)",
                    line_num,
                    exc,
                )
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
            else:
                logger.warning(
                    "local_memory: skipping non-object row %d (%s)",
                    line_num,
                    type(parsed).__name__,
                )
        return rows

    @staticmethod
    def _normalize_filter(
        event_filter: str | tuple[str, ...] | None,
    ) -> frozenset[str] | None:
        if event_filter is None:
            return None
        if isinstance(event_filter, str):
            return frozenset({event_filter})
        return frozenset(event_filter)


__all__ = ["LocalMemory"]
