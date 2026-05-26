#!/usr/bin/env python3
"""WS1(b) — forward candle collector for the trading universe.

onchainos `get_candles` caps at 299 bars/call, so a deep historical tape can't be
pulled in one shot. This collector FORWARD-APPENDS: each run fetches the latest 299
closed bars per (symbol, timeframe) and appends ONLY bars newer than the tape's
current max ts — never overwriting historical bars (so a re-source can't corrupt the
existing deep 1H tapes). Run it on a cadence (the overnight loop / cron) and the tape
grows toward a rich multi-TF, multi-symbol, multi-regime foundation.

Output: scripts/calibration/data/tape/{SYM}_{TF}.json  ->  [{ts,open,high,low,close,volume,vol_usd}]
ascending by ts. Plus a coverage line per tape.

Run: uv run python scripts/calibration/ingest_universe_candles.py [--tfs 5m,15m,1H,4H]
Reuses contest_bot/onchainos.py (the bot's own market feed) + universe.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
_CB = os.path.join(_HERE, "..", "..", "contest_bot")
if _CB not in sys.path:
    sys.path.insert(0, _CB)

import universe  # noqa: E402

TAPE_DIR = os.path.join(_HERE, "data", "tape")
DEFAULT_TFS = ["5m", "15m", "1H", "4H"]
KEEP = ("ts", "open", "high", "low", "close", "volume", "vol_usd")


def _fmt(ms: float) -> str:
    return dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def load_tape(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def merge_forward(existing: list[dict], fresh: list[dict]) -> tuple[list[dict], int]:
    """Append only bars strictly newer than the existing max ts. Never overwrites
    historical bars. Returns (merged, n_added)."""
    max_ts = max((float(c["ts"]) for c in existing), default=float("-inf"))
    add = [{k: c.get(k, 0) for k in KEEP} for c in fresh if float(c.get("ts", 0)) > max_ts]
    add.sort(key=lambda c: float(c["ts"]))
    return existing + add, len(add)


def collect(symbols: list[str], tfs: list[str], limit: int = 299) -> dict:
    from onchainos import OnchainOS  # lazy: needs the onchainos CLI

    oc = OnchainOS(chain="solana")
    os.makedirs(TAPE_DIR, exist_ok=True)
    report: dict = {}
    for sym in symbols:
        mint = universe.mint_for(sym)
        if not mint:
            print(f"  {sym}: no mint — skip")
            continue
        for tf in tfs:
            path = os.path.join(TAPE_DIR, f"{sym}_{tf}.json")
            existing = load_tape(path)
            try:
                fresh = oc.get_candles(mint, tf, limit=limit)
            except Exception as e:
                print(f"  {sym} {tf}: fetch error ({type(e).__name__}) — skip")
                continue
            if not fresh:
                print(f"  {sym} {tf}: no candles returned — skip")
                continue
            merged, added = merge_forward(existing, fresh)
            with open(path, "w") as f:
                json.dump(merged, f)
            ts = [float(c["ts"]) for c in merged]
            report[f"{sym}_{tf}"] = {
                "n": len(merged),
                "added": added,
                "first": min(ts),
                "last": max(ts),
            }
            print(
                f"  {sym:5} {tf:3}  n={len(merged):5}  +{added:<4} new  "
                f"{_fmt(min(ts))} -> {_fmt(max(ts))}"
            )
    return report


def run(tfs: list[str]) -> dict:
    symbols = list(universe.SYMBOL_TO_MINT.keys())
    print("=" * 88)
    print(f"WS1(b) FORWARD CANDLE COLLECTOR — {len(symbols)} symbols x {len(tfs)} TFs")
    print(f"  symbols: {symbols}")
    print("=" * 88)
    report = collect(symbols, tfs)
    # coverage manifest (forward-appended foundation tape)
    manifest = os.path.join(TAPE_DIR, "universe_coverage.json")
    with open(manifest, "w") as f:
        json.dump(
            {"generated": dt.datetime.utcnow().isoformat() + "Z", "tapes": report}, f, indent=2
        )
    print(f"\nwrote coverage manifest: {manifest}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfs", default=",".join(DEFAULT_TFS), help="comma-separated timeframes")
    a = ap.parse_args()
    run([t.strip() for t in a.tfs.split(",") if t.strip()])
