"""Ingest deep 5m OHLCV history for the majors universe from OKX spot (Sprint 31).

This is the data spine for the two-strategy alpha search (spec
`private/specs/2026-06-03-two-strategy-alpha-search-design.md` §5.1). It pulls
MONTHS of 5m bars — well past the ~299-bar OnchainOS cap that crippled the old
backtest_entry.py — so the CPCV/PBO/DSR gate has real N.

Output (per coin): scripts/calibration/data/majors_5m/{SYM}.json
    [{ts, open, high, low, close, volume}, ...]   ascending ms, deduped
plus a coverage manifest majors_5m/coverage.json.

PI Network is CONDITIONAL (spec §1): we probe it; if OKX spot has no real 5m
history we DROP it and record the drop in the manifest — never block on it.

Usage:
    uv run python scripts/calibration/ingest_okx_majors_5m.py [--days 365]
                                                              [--coins BTC,ETH,SOL,XRP,DOGE,PI]
"""

from __future__ import annotations

import argparse
import json
import os
import time

import ccxt_spine as spine

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "majors_5m")
DEFAULT_COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "PI"]
VENUE = "okx_spot"
TF = "5m"
# A symbol is "real" only if the probe returns a meaningful number of bars.
MIN_PROBE_BARS = 50


def _symbol(coin: str) -> str:
    return f"{coin}/USDT"


def _probe_ok(coin: str) -> tuple[bool, int]:
    """Cheap recent-window probe: does OKX spot have tradeable 5m history?"""
    end = int(time.time() * 1000)
    since = end - 3 * 86_400_000  # last ~3 days
    try:
        bars = spine.fetch_ohlcv(VENUE, _symbol(coin), TF, since, end)
    except Exception as exc:
        print(f"  {coin}: probe error ({type(exc).__name__}: {exc}) → DROP")
        return False, 0
    return (len(bars) >= MIN_PROBE_BARS), len(bars)


def run(coins: list[str], days: int) -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    end_ms = int(time.time() * 1000)
    since_ms = end_ms - days * 86_400_000
    manifest: dict = {"venue": VENUE, "timeframe": TF, "days": days, "coins": {}, "dropped": {}}

    for coin in coins:
        # PI (and any thin name) is conditional — probe first, drop if no depth.
        if coin == "PI":
            ok, n = _probe_ok(coin)
            if not ok:
                print(f"  {coin}: only {n} probe bars (< {MIN_PROBE_BARS}) → DROPPED (spec §1)")
                manifest["dropped"][coin] = {"reason": "no_real_5m_history", "probe_bars": n}
                continue

        sym = _symbol(coin)
        print(f"  {coin} ({sym}) {TF}: fetching ~{days}d …", flush=True)
        try:
            bars = spine.fetch_ohlcv(VENUE, sym, TF, since_ms, end_ms)
        except Exception as exc:
            print(f"    ERROR ({type(exc).__name__}: {exc}) → skipped")
            manifest["dropped"][coin] = {"reason": f"fetch_error:{type(exc).__name__}"}
            continue
        if len(bars) < MIN_PROBE_BARS:
            print(f"    only {len(bars)} bars → DROPPED")
            manifest["dropped"][coin] = {"reason": "too_few_bars", "n": len(bars)}
            continue

        out_path = os.path.join(DATA_DIR, f"{coin}.json")
        with open(out_path, "w") as f:
            json.dump(bars, f)
        span_days = (bars[-1]["ts"] - bars[0]["ts"]) / 86_400_000 if len(bars) > 1 else 0
        manifest["coins"][coin] = {
            "symbol": sym,
            "n_bars": len(bars),
            "first_ts": bars[0]["ts"],
            "last_ts": bars[-1]["ts"],
            "span_days": round(span_days, 1),
            "path": f"majors_5m/{coin}.json",
        }
        print(f"    {len(bars)} bars over {span_days:.0f}d → {out_path}")

    with open(os.path.join(DATA_DIR, "coverage.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=365, help="History window in days (default 365)")
    ap.add_argument(
        "--coins",
        type=str,
        default=",".join(DEFAULT_COINS),
        help="Comma list (default BTC,ETH,SOL,XRP,DOGE,PI; PI is probe-or-drop)",
    )
    args = ap.parse_args()
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    print(f"OKX-spot majors 5m ingest — {len(coins)} coins, {args.days}d → {DATA_DIR}")
    m = run(coins, args.days)
    kept = list(m["coins"])
    dropped = list(m["dropped"])
    print(f"\nDone. kept={kept}  dropped={dropped}")


if __name__ == "__main__":
    _cli()
