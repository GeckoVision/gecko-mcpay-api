#!/usr/bin/env python3
"""Sprint 29 — One-shot ingest of cross-source oracle snapshots.

Polls Pyth Hermes + Jupiter Aggregator for the bot's symbol universe,
writes one `oracle_snapshots` row per (source, symbol) pair, and exits.

Designed to be cron'd. Default cadence: every 60 seconds via systemd
timer or */1 * * * * cron. Env-gated kill switch (GECKO_ORACLE_INGEST=1
to enable; default OFF) so a bot deployment doesn't accidentally start
hitting external APIs.

Usage:
    set -a; source .env; set +a
    GECKO_ORACLE_INGEST=1 python3 scripts/oracle/ingest_oracle_snapshots.py
    GECKO_ORACLE_INGEST=1 python3 scripts/oracle/ingest_oracle_snapshots.py --dry-run

Exit codes:
    0 — success or disabled gracefully
    1 — Mongo unreachable / sink unable to construct
    2 — partial: some sources failed (count printed)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Make contest_bot/ importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTEST_BOT = _REPO_ROOT / "contest_bot"
if str(_CONTEST_BOT) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT))

logger = logging.getLogger("ingest_oracle_snapshots")

# Default universe — matches the bot's INSTRUMENTS list. Override via
# GECKO_ORACLE_INGEST_SYMBOLS=SYM1,SYM2,...
DEFAULT_SYMBOLS = ["SOL", "USDC", "PYTH", "WIF"]


def _ingest_enabled() -> bool:
    return os.environ.get("GECKO_ORACLE_INGEST", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _symbols() -> list[str]:
    raw = os.environ.get("GECKO_ORACLE_INGEST_SYMBOLS", "").strip()
    if raw:
        return [s.strip().upper() for s in raw.split(",") if s.strip()]
    return DEFAULT_SYMBOLS


def run(dry_run: bool = False) -> int:
    if not _ingest_enabled():
        print("Ingest disabled: GECKO_ORACLE_INGEST=0 (default). Set to 1 to enable.")
        return 0

    from oracle.jupiter_client import JupiterPriceRestClient
    from oracle.pyth_client import PythHermesRestClient
    from oracle.snapshot_sink import OracleSnapshotSink, build_snapshot_doc

    symbols = _symbols()
    print(f"Polling {len(symbols)} symbols: {', '.join(symbols)}")

    pyth = PythHermesRestClient()
    jupiter = JupiterPriceRestClient()

    pyth_snaps = pyth.fetch(symbols)
    jup_snaps = jupiter.fetch(symbols)
    print(f"  pyth: {len(pyth_snaps)} symbols returned")
    print(f"  jupiter: {len(jup_snaps)} symbols returned")

    docs_to_write: list[dict] = []
    for sym, snap in pyth_snaps.items():
        docs_to_write.append(
            build_snapshot_doc(
                source="pyth",
                symbol=sym,
                price=snap.price,
                spread_pct=snap.spread_pct,
                confidence=snap.confidence,
                ts=snap.publish_time,
                extras={"feed_id": snap.feed_id},
            )
        )
    for sym, snap in jup_snaps.items():
        docs_to_write.append(
            build_snapshot_doc(
                source="jupiter",
                symbol=sym,
                price=snap.price,
                extras={"mint": snap.mint},
            )
        )

    if not docs_to_write:
        print("Nothing fetched; both sources returned 0 symbols.")
        return 2

    if dry_run:
        for d in docs_to_write[:6]:
            print(f"  [{d['source']}] {d['symbol']}: ${d['price']:.6f}")
        if len(docs_to_write) > 6:
            print(f"  ... + {len(docs_to_write) - 6} more")
        print(f"Dry-run; would have upserted {len(docs_to_write)} rows.")
        return 0

    sink = OracleSnapshotSink.from_env(async_writes=False)
    if sink is None:
        logger.error("OracleSnapshotSink.from_env returned None (MONGODB_URI?)")
        return 1

    ok = 0
    for d in docs_to_write:
        try:
            sink.record(d)
            ok += 1
        except Exception as exc:
            logger.warning("ingest.record_failed src=%s sym=%s err=%s",
                           d.get("source"), d.get("symbol"), exc)

    print(f"Done. wrote={ok}/{len(docs_to_write)}")
    return 0 if ok == len(docs_to_write) else 2


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="don't write Mongo")
    args = parser.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
