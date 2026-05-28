#!/usr/bin/env python3
"""Sprint 9 — fetch 60d hourly OHLCV for 40 Solana tokens, resample to 4h.

Phase D #1 ingested DAILY granularity (close proxied into O/H/L). For the
swing-window backtest (Sprint 9) we need REAL 4h OHLCV with volume so MFI
can be computed.

Strategy:
  - CoinGecko `/coins/{id}/market_chart?days=60&interval=hourly` returns hourly
    close + volume (no O/H/L). Resample to 4h:
        open  = first close in the 4h window
        high  = max close
        low   = min close
        close = last close
        volume= sum
  - That's "good-enough" proxy OHLC at 4h granularity (since each 4h is 4
    hourly closes, the resampled range captures intra-4h movement honestly).

Outputs: data/solana_4h/<SYMBOL>_4h.json (rows of ts, o, h, l, c, v).

Free-tier respectful: 1 fetch/sec, 40 symbols → ~40s end-to-end.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

DATA_DIR = Path("scripts/calibration/data/solana")
OUT_DIR = Path("scripts/calibration/data/solana_4h")
COINGECKO = "https://api.coingecko.com/api/v3"

# Map our universe symbols to CoinGecko IDs — copied from Phase D mapping
SYMBOL_TO_CG = {
    "APE": "apecoin",
    "ATH": "aethir",
    "BAT": "basic-attention-token",
    "BIO": "bio-protocol",
    "BONK": "bonk",
    "CAKE": "pancakeswap-token",
    "CHIP": "chips-token",
    "CHZ": "chiliz",
    "DRIFT": "drift-protocol",
    "FARTCOIN": "fartcoin",
    "FIDA": "bonfida",
    "GALA": "gala",
    "GRASS": "grass",
    "HIMSON": "himson",
    "HOLO": "hologram-1",
    "IO": "io",
    "JTO": "jito-governance-token",
    "JUP": "jupiter-exchange-solana",
    "KMNO": "kamino",
    "MUON": "muon-network",
    "ORCA": "orca",
    "ORDI": "ordinals",
    "PENGU": "pudgy-penguins",
    "PRIME": "echelon-prime",
    "PYTH": "pyth-network",
    "STRK": "starknet",
    "TRUMP": "official-trump",
    "VIRTUAL": "virtual-protocol",
    "WIF": "dogwifcoin",
    "WLFI": "world-liberty-financial",
    "ZAMA": "zama",
    "ZEC": "zcash",
    "GUN": "gun",
    "PENGU": "pudgy-penguins",
    # Stables + odd-tickers we skip (low signal, low volume, or wrapped)
    # AUSD, CASH, USDCV, USDGO, USDTB → stablecoin proxies skip
    # TBTC, GALA, GOOGLX → may not have clean CG IDs / not Solana-native
}


def fetch_hourly_60d(coin_id: str) -> dict | None:
    """CoinGecko /market_chart?days=60&interval=hourly returns close + volume hourly.

    Returns: {"prices": [[ts_ms, close], ...], "total_volumes": [[ts_ms, vol], ...]}
    or None on persistent failure.
    """
    url = f"{COINGECKO}/coins/{coin_id}/market_chart"
    for attempt in range(3):
        try:
            r = httpx.get(url, params={"vs_currency": "usd", "days": 60, "interval": "hourly"}, timeout=15.0)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"      429 — sleep {wait}s")
                time.sleep(wait)
                continue
            print(f"      HTTP {r.status_code}")
            return None
        except Exception as e:
            print(f"      {type(e).__name__}: {e}")
            return None
    return None


def resample_hourly_to_4h(prices: list[list], volumes: list[list]) -> list[dict]:
    """Resample hourly close+volume to 4h OHLCV bars.

    Each 4h bucket = 4 hourly samples. Open=first close, High=max, Low=min,
    Close=last, Volume=sum. Buckets aligned to UTC 00:00 / 04:00 / 08:00 / ...
    """
    if not prices:
        return []
    # Build vol lookup
    vol_by_ts = {int(row[0]): float(row[1]) for row in volumes}
    # Pair (ts_sec, close, volume)
    samples = []
    for p in prices:
        ts_ms = int(p[0])
        close = float(p[1])
        vol = vol_by_ts.get(ts_ms, 0.0)
        samples.append((ts_ms, close, vol))
    samples.sort()
    # Bucket by 4h aligned to UTC
    bars: dict[int, list] = {}
    for ts_ms, close, vol in samples:
        bucket_ms = (ts_ms // (4 * 3600_000)) * (4 * 3600_000)
        bars.setdefault(bucket_ms, []).append((close, vol))
    # Build bar rows in time order
    rows = []
    for bucket_ms in sorted(bars.keys()):
        bar = bars[bucket_ms]
        closes = [c for c, _ in bar]
        vols = [v for _, v in bar]
        rows.append({
            "ts": bucket_ms,
            "open": closes[0],
            "high": max(closes),
            "low": min(closes),
            "close": closes[-1],
            "volume": sum(vols),
        })
    return rows


def main() -> int:
    only_symbol = os.environ.get("ONLY_SYMBOL")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    successes = 0
    skips = 0
    fails = 0
    syms = [only_symbol] if only_symbol else sorted(SYMBOL_TO_CG.keys())
    for i, sym in enumerate(syms, 1):
        coin_id = SYMBOL_TO_CG.get(sym)
        if not coin_id:
            print(f"  [{i:>2d}/{len(syms)}] {sym}: no CG id mapped — skip")
            skips += 1
            continue
        out = OUT_DIR / f"{sym}_4h.json"
        if out.exists() and not os.environ.get("FORCE"):
            print(f"  [{i:>2d}/{len(syms)}] {sym}: cached ({out})")
            successes += 1
            continue
        print(f"  [{i:>2d}/{len(syms)}] {sym} ({coin_id}): fetching…")
        chart = fetch_hourly_60d(coin_id)
        if not chart:
            print(f"      FAIL")
            fails += 1
            time.sleep(2.0)
            continue
        rows = resample_hourly_to_4h(chart.get("prices") or [], chart.get("total_volumes") or [])
        if len(rows) < 60:  # need at least 60 4h bars ≈ 10 days
            print(f"      only {len(rows)} 4h bars — skip")
            skips += 1
            continue
        out.write_text(json.dumps(rows))
        print(f"      wrote {len(rows)} 4h bars → {out}")
        successes += 1
        time.sleep(1.5)
    print(f"\nDone: {successes} success, {skips} skip, {fails} fail")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
