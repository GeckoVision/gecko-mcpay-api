#!/usr/bin/env python3
"""Universe-carry — Binance perp + spot OHLCV ingestion via ccxt.

Driver for the universe-carry pre-reg (private/strategy/2026-05-26-carry-
universe-prereg.md) — pulls 4h OHLCV for both the USDT-perp leg AND its
paired USDT-spot leg over a deep history window. Spot+perp closes at each
funding-event timestamp give the realistic basis-PnL the optimistic carry
model assumed away (see ``carry_realistic_validation.py`` for the same
pattern on HL).

Output:
  data/perp/binance/{SYM}_perp.json    -- [{ts, open, high, low, close, volume}, ...]
  data/spot/binance/{SYM}_spot.json    -- same shape
  data/perp/binance/perp_coverage.json -- per-coin perp manifest
  data/spot/binance/spot_coverage.json -- per-coin spot manifest

Run:
  uv run python scripts/calibration/ingest_ccxt_ohlcv_universe.py [--days 730]
                                                                  [--timeframe 4h]
                                                                  [--n 50]
                                                                  [--coins BTC,ETH]
                                                                  [--leg perp,spot]

Notes:
- The frozen universe is loaded (never re-picked here — use
  ``ingest_ccxt_funding_universe.py --force-universe`` or
  ``ccxt_spine.py --pick-universe --force`` if a refresh is genuinely needed).
- --leg perp,spot (default) ingests both. Use --leg perp or --leg spot to
  run just one side (e.g. when iterating on a single leg's harness).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time

from scripts.calibration import ccxt_spine

_HERE = os.path.dirname(os.path.abspath(__file__))

LEG_TO_DIR = {
    "perp": os.path.join(_HERE, "data", "perp", "binance"),
    "spot": os.path.join(_HERE, "data", "spot", "binance"),
}
LEG_TO_VENUE = {"perp": "binance_perp", "spot": "binance_spot"}
LEG_TO_MANIFEST = {
    "perp": "perp_coverage.json",
    "spot": "spot_coverage.json",
}


def _fmt(ms: float) -> str:
    return dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _symbol_for_leg(entry: dict, leg: str) -> str:
    """Resolve the ccxt symbol for the given leg from a universe entry."""
    if leg == "perp":
        return entry["perp_symbol"]
    if leg == "spot":
        return entry["spot_symbol"]
    raise ValueError(f"unknown leg {leg!r}; expected 'perp' or 'spot'")


def run(
    days: int,
    timeframe: str,
    n: int,
    coin_filter: list[str] | None,
    legs: list[str],
) -> dict:
    universe = ccxt_spine.pick_binance_universe(n=n, force=False)
    end_ms = int(time.time() * 1000)
    since_ms = end_ms - days * 86_400_000
    filt = {c.strip().upper() for c in (coin_filter or [])} if coin_filter else None
    print("=" * 96)
    print(
        f"BINANCE OHLCV INGESTION (ccxt) — universe n={universe['n']} "
        f"timeframe={timeframe} days={days} legs={','.join(legs)}"
    )
    print("=" * 96)
    out: dict[str, dict] = {leg: {} for leg in legs}
    for entry in universe["ranking"]:
        sym = entry["symbol"]
        if filt is not None and sym not in filt:
            continue
        for leg in legs:
            venue_name = LEG_TO_VENUE[leg]
            try:
                symbol = _symbol_for_leg(entry, leg)
            except ValueError as exc:
                print(f"  {sym:8s} {leg:4s} bad leg: {exc}")
                continue
            try:
                bars = ccxt_spine.fetch_ohlcv(
                    venue_name, symbol, timeframe=timeframe, since_ms=since_ms, end_ms=end_ms
                )
            except Exception as exc:
                print(f"  {sym:8s} {leg:4s} {symbol:20s} ERROR ({type(exc).__name__}: {exc})")
                continue
            if not bars:
                print(f"  {sym:8s} {leg:4s} {symbol:20s} no bars — skip")
                continue
            out_dir = LEG_TO_DIR[leg]
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{sym}_{leg}.json")
            with open(out_path, "w") as f:
                json.dump(bars, f)
            ts = [b["ts"] for b in bars]
            out[leg][sym] = {
                "n": len(bars),
                "first_ts": ts[0],
                "last_ts": ts[-1],
                "symbol": symbol,
                "last_close": bars[-1]["close"],
            }
            print(
                f"  {sym:8s} {leg:4s} {symbol:20s} n={len(bars):5d}  "
                f"{_fmt(ts[0])} -> {_fmt(ts[-1])}  last_close={bars[-1]['close']:.6f}"
            )
    manifests: dict = {}
    for leg in legs:
        manifest = {
            "generated_at": dt.datetime.utcnow().isoformat() + "Z",
            "venue": "binance",
            "kind": f"{leg}_ohlcv",
            "timeframe": timeframe,
            "days_requested": days,
            "n_coins_requested": n,
            "n_coins_written": len(out[leg]),
            "universe_selected_at": universe["selected_at"],
            "coins": out[leg],
        }
        path = os.path.join(LEG_TO_DIR[leg], LEG_TO_MANIFEST[leg])
        with open(path, "w") as f:
            json.dump(manifest, f, indent=2)
        manifests[leg] = manifest
        print(f"wrote {path}")
    return manifests


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=730, help="History window in days (default 730)")
    ap.add_argument(
        "--timeframe",
        default="4h",
        help="ccxt timeframe — 1m/5m/15m/1h/4h/1d (default 4h, per pre-reg)",
    )
    ap.add_argument(
        "--n",
        type=int,
        default=50,
        help="Universe size if no cached universe yet (loaded otherwise)",
    )
    ap.add_argument(
        "--coins",
        default=None,
        help="Comma-separated subset of universe coins to ingest (testing)",
    )
    ap.add_argument(
        "--leg",
        default="perp,spot",
        help="Comma-separated legs to ingest (default 'perp,spot')",
    )
    a = ap.parse_args()
    coin_filter = [c.strip().upper() for c in a.coins.split(",")] if a.coins else None
    legs = [leg.strip().lower() for leg in a.leg.split(",") if leg.strip()]
    for leg in legs:
        if leg not in LEG_TO_VENUE:
            raise SystemExit(f"--leg includes unknown value {leg!r}; expected perp or spot")
    run(days=a.days, timeframe=a.timeframe, n=a.n, coin_filter=coin_filter, legs=legs)


if __name__ == "__main__":
    _cli()
