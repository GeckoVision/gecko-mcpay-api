#!/usr/bin/env python3
"""One-shot backfill of `bot_behaviors` from historical artifacts + bot_state.

Two sources:

  1. `contest_bot/bot_state.json` — the 44 closed positions. Each one has
     entry_ts, exit_ts, pnl_pct, exit_reason, decision_id (when available).
     For each, we synthesise an action="act" behavior row.

  2. `contest_bot/artifact_2026*.jsonl` (last ~7d) — log of `local_panel`,
     `candidate_blocked`, `position_open`, `position_close` events. Each
     `local_panel` row → an action row keyed on coordinator.action.

We DO NOT embed during backfill (deferred to lazy embed on first read, per
the build brief: "too expensive for initial — embed lazily on first read").
Voyage cost for 5K rows at 250 tokens would be ~$0.15 but it's not the
critical path; this script ships data into Mongo so analytics queries can
run today.

Idempotent: keyed on `decision_id` (or a synthesized one from symbol+ts when
absent in the source). Re-running is safe.

Dry-run by default. `--apply` writes.

Usage:
    uv run python scripts/backfill/backfill_bot_behaviors.py
    uv run python scripts/backfill/backfill_bot_behaviors.py --apply
    uv run python scripts/backfill/backfill_bot_behaviors.py --apply --since 2026-05-25
    uv run python scripts/backfill/backfill_bot_behaviors.py --apply --source artifacts
    uv run python scripts/backfill/backfill_bot_behaviors.py --apply --source bot_state

Requires:
    MONGODB_URI in env for `--apply`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "contest_bot"))

from decision_store.behavior_sink import build_behavior_doc  # noqa: E402

logger = logging.getLogger("backfill_bot_behaviors")

BOT_STATE_PATH = _REPO_ROOT / "contest_bot" / "bot_state.json"
ARTIFACT_GLOB = "artifact_2026*.jsonl"
ARTIFACT_DIR = _REPO_ROOT / "contest_bot"


@dataclass
class BackfillStats:
    scanned_positions: int = 0
    scanned_artifacts: int = 0
    built: int = 0
    upserted: int = 0
    skipped_no_id: int = 0
    failed: int = 0

    def summary(self) -> str:
        return (
            f"scanned_positions={self.scanned_positions} "
            f"scanned_artifacts={self.scanned_artifacts} "
            f"built={self.built} upserted={self.upserted} "
            f"skipped_no_id={self.skipped_no_id} failed={self.failed}"
        )


# ── ID synthesis (when source row lacks a decision_id) ─────────────────


def _synth_decision_id(symbol: str, ts: str, kind: str) -> str:
    """Deterministic ID for rows that didn't carry one (early artifacts).

    Idempotent: re-running yields the same ID → upsert dedupes.
    """
    h = hashlib.sha256(f"{symbol}|{ts}|{kind}".encode()).hexdigest()[:32]
    return h


# ── Source 1: closed positions from bot_state.json ─────────────────────


def _positions_to_decisions(
    bot_state: dict,
    *,
    run_id: str,
    code_commit: str | None,
    since_iso: str | None = None,
) -> Iterable[dict]:
    for pos in bot_state.get("positions", []):
        entry_ts = pos.get("entry_ts")
        if since_iso and entry_ts and entry_ts < since_iso:
            continue
        decision_id = pos.get("decision_id") or _synth_decision_id(
            pos.get("symbol", "?"), entry_ts or "0", "position"
        )
        sig = pos.get("signal_data") or {}
        regime_1h = sig.get("regime_1h") or ""
        outcome = None
        if pos.get("status") == "closed":
            outcome = {
                "pnl_pct": pos.get("pnl_pct"),
                "pnl_usd": pos.get("pnl_usd"),
                "exit_reason": pos.get("exit_reason"),
                "entry_price": pos.get("entry_price"),
                "exit_price": pos.get("exit_price"),
                "peak_pct": None,
            }
            if pos.get("entry_ts") and pos.get("exit_ts"):
                try:
                    e = datetime.fromisoformat(pos["entry_ts"])
                    x = datetime.fromisoformat(pos["exit_ts"])
                    outcome["duration_min"] = round((x - e).total_seconds() / 60.0, 2)
                except Exception:
                    pass

        decision = {
            "decision_id": decision_id,
            "run_id": run_id,
            "ts": entry_ts,
            "symbol": (pos.get("symbol") or "").split("-")[0],
            "symbol_group": "majors",
            "signal": {
                "type": sig.get("primitive") or sig.get("signal") or "?",
                "fired": True,
                "multiplier_observed": sig.get("multiplier_observed"),
            },
            "indicators": {
                "price": pos.get("entry_price"),
                "regime_1h": regime_1h,
            },
            "voices": [],
            "oracle": None,
            "coordinator": {
                "action": "act",
                "rule": "backfilled_from_bot_state",
                "note": pos.get("mode", "paper"),
            },
            "market_context": {},
            "outcome": outcome,
            "code_commit": code_commit,
        }
        yield decision


# ── Source 2: artifact JSONL events ────────────────────────────────────


def _artifacts_to_decisions(
    artifact_path: Path,
    *,
    run_id: str,
    code_commit: str | None,
    since_iso: str | None = None,
) -> Iterable[dict]:
    if not artifact_path.exists():
        return
    with artifact_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = row.get("kind")
            ts = row.get("ts")
            if since_iso and ts and ts < since_iso:
                continue
            payload = row.get("payload") or {}

            if kind == "local_panel":
                action = (payload.get("action") or "decline").lower()
                decision_id = row.get("decision_id") or _synth_decision_id(
                    payload.get("instrument", "?"), ts or "0", "panel"
                )
                yield {
                    "decision_id": decision_id,
                    "run_id": run_id,
                    "ts": ts,
                    "symbol": payload.get("instrument"),
                    "symbol_group": "majors",
                    "signal": {},
                    "indicators": {},
                    "voices": payload.get("voices") or [],
                    "oracle": None,
                    "coordinator": {
                        "action": action,
                        "rule": payload.get("coordinator_rule_fired"),
                        "note": payload.get("reason"),
                    },
                    "market_context": {},
                    "code_commit": code_commit,
                }
            elif kind == "candidate_blocked":
                decision_id = row.get("decision_id") or _synth_decision_id(
                    payload.get("symbol", "?"), ts or "0", "blocked"
                )
                sd = payload.get("signal_data") or {}
                yield {
                    "decision_id": decision_id,
                    "run_id": run_id,
                    "ts": ts,
                    "symbol": payload.get("symbol", "").split("-")[0],
                    "symbol_group": "majors",
                    "signal": {
                        "type": sd.get("primitive") or sd.get("signal"),
                        "fired": True,
                        "multiplier_observed": sd.get("multiplier_observed"),
                    },
                    "indicators": {
                        "regime_1h": payload.get("regime_1h"),
                    },
                    "voices": [],
                    "oracle": None,
                    "coordinator": {
                        "action": "candidate_blocked",
                        "rule": payload.get("stage"),
                        "note": ",".join(payload.get("reasons", [])),
                    },
                    "market_context": {
                        "net_flow_1h_usd": (payload.get("net_flow") or {}).get("net_flow_usd"),
                    },
                    "code_commit": code_commit,
                }


# ── Main backfill ──────────────────────────────────────────────────────


def run_backfill(
    *,
    collection: Any | None,
    bot_state_path: Path = BOT_STATE_PATH,
    artifact_dir: Path = ARTIFACT_DIR,
    artifact_glob: str = ARTIFACT_GLOB,
    source: str = "all",
    since: str | None = None,
    run_id: str = "backfill-historical",
    code_commit: str | None = None,
    apply: bool = False,
    log: Any = None,
) -> BackfillStats:
    say = log or print
    stats = BackfillStats()

    iters: list[Iterable[dict]] = []

    if source in ("all", "bot_state") and bot_state_path.exists():
        try:
            state = json.loads(bot_state_path.read_text())
        except Exception as exc:
            say(f"[backfill] cannot read {bot_state_path}: {exc}")
            state = {"positions": []}
        positions = list(_positions_to_decisions(
            state, run_id=run_id, code_commit=code_commit, since_iso=since
        ))
        stats.scanned_positions = len(positions)
        iters.append(positions)

    if source in ("all", "artifacts"):
        for path in sorted(artifact_dir.glob(artifact_glob)):
            rows = list(_artifacts_to_decisions(
                path, run_id=run_id, code_commit=code_commit, since_iso=since
            ))
            stats.scanned_artifacts += len(rows)
            iters.append(rows)

    for it in iters:
        for d in it:
            try:
                doc = build_behavior_doc(d, run_id=run_id, code_commit=code_commit)
            except Exception as exc:
                stats.failed += 1
                say(f"[backfill] build failed: {exc}")
                continue
            stats.built += 1
            decision_id = doc.get("decision_id")
            if not decision_id:
                stats.skipped_no_id += 1
                continue
            if not apply or collection is None:
                continue
            try:
                collection.update_one(
                    {"decision_id": decision_id},
                    {
                        "$set": doc,
                        "$setOnInsert": {"created_at": datetime.now(UTC)},
                    },
                    upsert=True,
                )
                stats.upserted += 1
            except Exception as exc:
                stats.failed += 1
                say(f"[backfill] upsert failed for {decision_id}: {exc}")

    say(f"[backfill] {stats.summary()}")
    if not apply:
        say("[backfill] dry-run (default) — pass --apply to write")
    return stats


def _get_collection() -> Any | None:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None
    try:
        from pymongo import MongoClient

        return MongoClient(uri, serverSelectionTimeoutMS=3000)[
            os.environ.get("MONGODB_DB", "gecko")
        ][os.environ.get("MONGODB_BEHAVIOR_COLL", "bot_behaviors")]
    except Exception as exc:
        print(f"[backfill] mongo unavailable: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="backfill_bot_behaviors",
        description="Backfill bot_behaviors from bot_state.json + artifact JSONL.",
    )
    p.add_argument("--apply", action="store_true", help="actually upsert (default: dry-run)")
    p.add_argument("--source", choices=("all", "bot_state", "artifacts"), default="all")
    p.add_argument("--since", default=None, help="ISO date — skip rows older than this")
    p.add_argument("--run-id", default="backfill-historical")
    p.add_argument("--code-commit", default=None)
    args = p.parse_args(argv)

    coll = _get_collection() if args.apply else None
    if args.apply and coll is None:
        print("[backfill] MONGODB_URI not set — cannot --apply", file=sys.stderr)
        return 2

    stats = run_backfill(
        collection=coll,
        source=args.source,
        since=args.since,
        run_id=args.run_id,
        code_commit=args.code_commit,
        apply=args.apply,
    )
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
