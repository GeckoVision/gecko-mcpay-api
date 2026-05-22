"""Persisted bot state for the OKX contest bot.

Mirrors the disk-persistence pattern used by ``HourlyCircuitBreaker`` in
``gecko_wrap.py``: JSON on disk, atomic write via ``.tmp`` + ``os.replace``,
graceful corrupt-file recovery (log + start clean). Survives bot restarts
so an open live position is never orphaned on-chain by a process bounce.

Recovery hatch — ``rebuild_from_artifact`` — reads the existing artifact
JSONL ledger and reconstructs ``positions`` / ``daily_trades`` /
``total_spent_usd`` from the immutable event log. Used when the state
file is missing on startup (covers the live RAY-USDC case where the bot
opened a real position BEFORE state persistence existed).

Correlation rules for open/close matching inside an artifact day:
1. Prefer ``decision_id`` match (each ``position_open`` row gets a unique
   id; the matching ``position_close`` row carries the same id via
   ``ArtifactLogger.log(..., decision_id=...)``).
2. Fall back to (token, entry_ts) for legacy rows where decision_id is
   the sentinel ``"stub"`` (test fixtures + early bot runs).

Anything more sophisticated belongs in a structured ledger replay, not
in a recovery hatch.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

import os as _os

# GECKO_STATE_DIR lets a test instance write state to a separate directory
# without touching the live bot's files. Default is the module directory
# (unchanged behaviour for the live bot — it finds its existing files on
# the next restart).
_GECKO_STATE_DIR = Path(_os.environ["GECKO_STATE_DIR"]) if _os.environ.get("GECKO_STATE_DIR") else Path(__file__).parent
_DEFAULT_STATE_PATH = _GECKO_STATE_DIR / "bot_state.json"


class BotState(BaseModel):
    """Persisted bot state — restored on startup, written on every mutation."""

    version: int = 1  # schema version for forward-compat
    positions: list[dict[str, Any]] = Field(default_factory=list)
    daily_trades: int = 0
    consec_losses: int = 0
    total_spent_usd: float = 0.0
    last_reset_day: str = ""
    saved_at: str = ""  # ISO-UTC of last save
    # iter-3.x 2026-05-20: persist realized PnL so the dashboard tile
    # survives bot reboots (contest iteration loop requires ≤30s
    # restarts and we don't want operators to lose visibility on what
    # the session has earned). Recomputed from artifact on rebuild.
    realized_pnl_today: float = 0.0
    wins_today: int = 0
    losses_today: int = 0


class BotStateStore:
    """File-backed state. JSON on disk, atomic write, graceful corrupt-file.

    Single-writer assumption (the bot is one process). We do not take a
    file lock — the persistence pattern mirrors ``HourlyCircuitBreaker``.
    """

    def __init__(self, path: str | Path = _DEFAULT_STATE_PATH) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    # ── Persistence ────────────────────────────────────────────────────
    def load(self) -> BotState:
        """Return persisted state. Missing file → empty; corrupt → empty + warn."""
        if not self._path.exists():
            return BotState()
        try:
            raw = json.loads(self._path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("bot_state: could not load %s (%s); starting clean", self._path, exc)
            return BotState()
        try:
            return BotState.model_validate(raw)
        except Exception as exc:  # pydantic ValidationError, etc.
            logger.warning("bot_state: state file shape invalid (%s); starting clean", exc)
            return BotState()

    def save(self, state: BotState) -> None:
        """Atomic write: serialize to .tmp, then os.replace into place."""
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(state.model_dump_json())
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("bot_state: could not persist %s: %s", self._path, exc)
            # best-effort cleanup of leaked .tmp
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    # ── Recovery hatch ─────────────────────────────────────────────────
    def rebuild_from_artifact(self, artifact_path: str | Path) -> BotState:
        """Reconstruct state from an artifact_YYYYMMDD.jsonl ledger.

        Walks the file once, building maps of position_open events keyed
        by both decision_id and (token, entry_ts). A ``position_close``
        row removes the matching open. The leftover opens become the
        recovered ``positions`` list. ``daily_trades`` counts every
        position_open; ``total_spent_usd`` sums payload.usd from
        ``mode == "live"`` opens (paper trades don't spend the wallet).
        """
        path = Path(artifact_path)
        empty = BotState()
        if not path.exists():
            return empty

        # ordered list so we can deterministically iterate; small files
        opens: list[dict[str, Any]] = []
        closed_decision_ids: set[str] = set()
        closed_keys: set[tuple[str, str]] = set()
        daily_trades = 0
        total_spent_usd = 0.0
        realized_pnl_today = 0.0
        wins_today = 0
        losses_today = 0

        try:
            with open(path, encoding="utf-8") as f:
                for line_no, raw in enumerate(f, start=1):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("bot_state: artifact line %d not JSON; skipping", line_no)
                        continue
                    kind = row.get("kind")
                    payload = row.get("payload") or {}
                    if not isinstance(payload, dict):
                        continue
                    if kind == "position_open":
                        daily_trades += 1
                        if payload.get("mode") == "live":
                            with contextlib.suppress(TypeError, ValueError):
                                total_spent_usd += float(payload.get("usd") or 0)
                        opens.append(
                            {
                                "decision_id": row.get("decision_id"),
                                "ts": row.get("ts"),
                                "payload": payload,
                            }
                        )
                    elif kind == "position_close":
                        decision_id = row.get("decision_id")
                        if isinstance(decision_id, str) and decision_id and decision_id != "stub":
                            closed_decision_ids.add(decision_id)
                        token = payload.get("token")
                        # close payload doesn't carry entry_ts, so we
                        # close the *latest* still-open match for that
                        # token below; record token only.
                        if isinstance(token, str):
                            closed_keys.add((token, ""))  # entry_ts unknown
                        # Accumulate realized PnL for the dashboard tile.
                        with contextlib.suppress(TypeError, ValueError):
                            pnl_usd = float(payload.get("pnl_usd") or 0)
                            realized_pnl_today += pnl_usd
                            if pnl_usd > 0:
                                wins_today += 1
                            elif pnl_usd < 0:
                                losses_today += 1
        except OSError as exc:
            logger.warning("bot_state: could not read artifact %s: %s", path, exc)
            return empty

        # Match closes to opens. Pass 1 — decision_id (strong).
        survivors: list[dict[str, Any]] = []
        for ev in opens:
            did = ev.get("decision_id")
            if isinstance(did, str) and did and did != "stub" and did in closed_decision_ids:
                continue  # closed
            survivors.append(ev)

        # Pass 2 — token-only fallback for legacy ("stub") opens. A
        # token-only close removes the *oldest* surviving open for that
        # token; iterates in artifact order so semantics are stable.
        pending_token_closes: dict[str, int] = {}
        for tok, _ in closed_keys:
            pending_token_closes[tok] = pending_token_closes.get(tok, 0) + 1

        # Each strong (decision_id) close also implied a token close; we
        # already removed those above, so subtract them from the
        # token-fallback budget to avoid double-counting.
        for ev in opens:
            did = ev.get("decision_id")
            if isinstance(did, str) and did and did != "stub" and did in closed_decision_ids:
                ev_tok = (ev.get("payload") or {}).get("token")
                if isinstance(ev_tok, str) and pending_token_closes.get(ev_tok, 0) > 0:
                    pending_token_closes[ev_tok] -= 1

        final: list[dict[str, Any]] = []
        for ev in survivors:
            payload = ev.get("payload") or {}
            ev_tok = payload.get("token") if isinstance(payload, dict) else None
            if isinstance(ev_tok, str) and pending_token_closes.get(ev_tok, 0) > 0:
                pending_token_closes[ev_tok] -= 1
                continue
            # Reconstruct a position dict roughly shaped like the
            # in-memory `positions` rows. Missing fields (peak_price,
            # signal_data, etc.) default to safe values; monitor_positions
            # tolerates them.
            entry_price = 0.0
            try:
                entry_price = float(payload.get("entry_price") or 0)
            except (TypeError, ValueError):
                entry_price = 0.0
            final.append(
                {
                    "token": payload.get("token") or "",
                    "symbol": payload.get("symbol") or "",
                    "entry_price": entry_price,
                    "usd": payload.get("usd") or 0,
                    "entry_ts": ev.get("ts") or "",
                    "status": "open",
                    "peak_price": entry_price,
                    "signal_data": {},
                    "mode": payload.get("mode") or "paper",
                    "recovered_from_artifact": True,
                }
            )

        return BotState(
            positions=final,
            daily_trades=daily_trades,
            consec_losses=0,  # not recoverable from artifact alone
            total_spent_usd=total_spent_usd,
            realized_pnl_today=round(realized_pnl_today, 4),
            wins_today=wins_today,
            losses_today=losses_today,
            last_reset_day=datetime.now(UTC).strftime("%Y-%m-%d"),
            saved_at=datetime.now(UTC).isoformat(),
        )


__all__ = ["BotState", "BotStateStore"]
