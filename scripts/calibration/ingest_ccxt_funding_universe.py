#!/usr/bin/env python3
"""Universe-carry — Binance USDT-perp 8h funding ingestion via ccxt.

Driver for the universe-carry pre-reg (private/strategy/2026-05-26-carry-
universe-prereg.md). Loads the frozen Binance USDT-perp universe (via
``ccxt_spine.pick_binance_universe``) and pulls each coin's funding event
stream over a deep history window. Output shape mirrors the HL funding
ingest (``ingest_hyperliquid_funding.py``) so downstream carry harnesses
read either source uniformly.

Output:
  data/binance_universe.json                     -- frozen universe (selected once)
  data/funding/binance/{SYM}_funding.json        -- [{ts, fundingRate, premium}, ...]
  data/funding/binance/funding_coverage.json     -- manifest with per-coin span + ann mean

Run:
  uv run python scripts/calibration/ingest_ccxt_funding_universe.py [--days 730]
                                                                    [--n 50]
                                                                    [--coins BTC,ETH]
                                                                    [--force-universe]

Notes:
- Default window 730d targets ≥1 stress regime per the pre-reg's
  deep-history mandate. Use --days to widen or narrow.
- --coins filters the frozen universe to a subset (for testing) but does
  NOT mutate the universe.json file.
- --force-universe re-picks the universe; rare; explicit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import ccxt_spine  # noqa: E402  flat import matches sibling carry_*_validation.py pattern

OUT_DIR = os.path.join(_HERE, "data", "funding", "binance")
MANIFEST_PATH = os.path.join(OUT_DIR, "funding_coverage.json")


def _fmt(ms: float) -> str:
    return dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _annualized_mean_pct(rates: list[float]) -> float:
    """Funding rate is per 8h event on Binance USDT-perp. Annualize the mean
    to comparable basis points / year. 3 funding events per day * 365 days."""
    if not rates:
        return 0.0
    return sum(rates) / len(rates) * 3 * 365 * 100


def run(days: int, n: int, coin_filter: list[str] | None, force_universe: bool) -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)
    universe = ccxt_spine.pick_binance_universe(n=n, force=force_universe)
    print("=" * 96)
    print(
        f"BINANCE FUNDING INGESTION (ccxt) — universe n={universe['n']} "
        f"selected_at={universe['selected_at']}  days={days}"
    )
    print("=" * 96)
    end_ms = int(time.time() * 1000)
    since_ms = end_ms - days * 86_400_000
    report: dict = {}
    filt = {c.strip().upper() for c in (coin_filter or [])} if coin_filter else None
    for entry in universe["ranking"]:
        sym = entry["symbol"]
        if filt is not None and sym not in filt:
            continue
        perp_sym = entry["perp_symbol"]
        try:
            recs = ccxt_spine.fetch_funding_history(
                "binance_perp", perp_sym, since_ms=since_ms, end_ms=end_ms
            )
        except Exception as exc:
            print(f"  {sym:8s} {perp_sym:20s} ERROR ({type(exc).__name__}: {exc}) — skip")
            continue
        if not recs:
            print(f"  {sym:8s} {perp_sym:20s} no data — skip")
            continue
        out_path = os.path.join(OUT_DIR, f"{sym}_funding.json")
        with open(out_path, "w") as f:
            json.dump(recs, f)
        rates = [r["fundingRate"] for r in recs]
        ts = [r["ts"] for r in recs]
        ann = _annualized_mean_pct(rates)
        report[sym] = {
            "n": len(recs),
            "first_ts": ts[0],
            "last_ts": ts[-1],
            "ann_mean_pct": round(ann, 3),
            "perp_symbol": perp_sym,
        }
        rates_sorted = sorted(rates)
        print(
            f"  {sym:8s} n={len(recs):5d}  "
            f"{_fmt(ts[0])} -> {_fmt(ts[-1])}  "
            f"ann_mean={ann:+7.2f}%  "
            f"per-event[min/med/max]=[{min(rates):+0.5f}/{rates_sorted[len(rates) // 2]:+0.5f}/{max(rates):+0.5f}]"
        )
    manifest = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "venue": "binance",
        "kind": "funding",
        "days_requested": days,
        "n_coins_requested": n,
        "n_coins_written": len(report),
        "universe_selected_at": universe["selected_at"],
        "coins": report,
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nwrote {MANIFEST_PATH}")
    return manifest


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=730, help="History window in days (default 730)")
    ap.add_argument(
        "--n",
        type=int,
        default=50,
        help="Universe size used only when picking for the first time",
    )
    ap.add_argument(
        "--coins",
        default=None,
        help="Comma-separated subset of universe coins to ingest (testing)",
    )
    ap.add_argument(
        "--force-universe",
        action="store_true",
        help="Re-pick the Binance universe (rare; explicit override)",
    )
    a = ap.parse_args()
    coin_filter = [c.strip().upper() for c in a.coins.split(",")] if a.coins else None
    run(days=a.days, n=a.n, coin_filter=coin_filter, force_universe=a.force_universe)


if __name__ == "__main__":
    _cli()
