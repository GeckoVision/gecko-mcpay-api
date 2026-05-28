#!/usr/bin/env python3
"""Sprint 10 #8 — fetch 180d hourly via two 90d chunks per token.

CoinGecko `/market_chart` switches from hourly to daily at days>90. So to get
180d of hourly we use `/market_chart/range` twice per token:
  chunk A: from = now-180d, to = now-90d
  chunk B: from = now-90d,  to = now
Both return hourly (range ≤ 90d). Concatenate, dedupe, resample to 4h.

Output: data/solana_4h_180d/<SYMBOL>_4h.json (rows of ts, o, h, l, c, v).
~1080 4h bars/token (vs 360 in the 60d version).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

OUT_DIR = Path("scripts/calibration/data/solana_4h_180d")
COINGECKO = "https://api.coingecko.com/api/v3"

# Same mapping as the 60d ingest, plus majors
SYMBOL_TO_CG = {
    "APE": "apecoin", "ATH": "aethir", "BAT": "basic-attention-token",
    "BIO": "bio-protocol", "BONK": "bonk", "CAKE": "pancakeswap-token",
    "CHIP": "chips-token", "CHZ": "chiliz", "DRIFT": "drift-protocol",
    "FARTCOIN": "fartcoin", "FIDA": "bonfida", "GALA": "gala",
    "GRASS": "grass", "HOLO": "hologram-1", "IO": "io",
    "JTO": "jito-governance-token", "JUP": "jupiter-exchange-solana",
    "KMNO": "kamino", "ORCA": "orca", "ORDI": "ordinals",
    "PENGU": "pudgy-penguins", "PYTH": "pyth-network",
    "STRK": "starknet", "TRUMP": "official-trump",
    "VIRTUAL": "virtual-protocol", "WIF": "dogwifcoin",
    "ETH": "ethereum", "BTC": "bitcoin", "SOL": "solana",
}


def fetch_range_hourly(coin_id: str, from_ts: int, to_ts: int) -> dict | None:
    url = f"{COINGECKO}/coins/{coin_id}/market_chart/range"
    for attempt in range(3):
        try:
            r = httpx.get(url, params={
                "vs_currency": "usd",
                "from": from_ts,
                "to": to_ts,
            }, timeout=20.0)
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


def resample_to_4h(prices: list, volumes: list) -> list[dict]:
    if not prices:
        return []
    vol_by_ts = {int(row[0]): float(row[1]) for row in volumes}
    samples = []
    for p in prices:
        ts_ms = int(p[0])
        close = float(p[1])
        vol = vol_by_ts.get(ts_ms, 0.0)
        samples.append((ts_ms, close, vol))
    samples.sort()
    bars: dict[int, list] = {}
    for ts_ms, close, vol in samples:
        bucket_ms = (ts_ms // (4 * 3600_000)) * (4 * 3600_000)
        bars.setdefault(bucket_ms, []).append((close, vol))
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    sec_90d = 90 * 86400
    chunk_a_from = now - 180 * 86400
    chunk_a_to = now - 90 * 86400
    chunk_b_from = chunk_a_to + 1
    chunk_b_to = now

    only_symbol = os.environ.get("ONLY_SYMBOL")
    syms = [only_symbol] if only_symbol else sorted(SYMBOL_TO_CG.keys())
    successes = 0
    fails = 0

    for i, sym in enumerate(syms, 1):
        cg = SYMBOL_TO_CG.get(sym)
        if not cg:
            continue
        out = OUT_DIR / f"{sym}_4h.json"
        if out.exists() and not os.environ.get("FORCE"):
            print(f"  [{i:>2d}/{len(syms)}] {sym}: cached")
            successes += 1
            continue
        print(f"  [{i:>2d}/{len(syms)}] {sym} ({cg}): fetching 2 chunks...")

        # Chunk A
        a = fetch_range_hourly(cg, chunk_a_from, chunk_a_to)
        if not a:
            print(f"      chunk A FAIL")
            fails += 1
            time.sleep(3)
            continue
        time.sleep(2)

        # Chunk B
        b = fetch_range_hourly(cg, chunk_b_from, chunk_b_to)
        if not b:
            print(f"      chunk B FAIL")
            fails += 1
            time.sleep(3)
            continue

        prices = (a.get("prices") or []) + (b.get("prices") or [])
        volumes = (a.get("total_volumes") or []) + (b.get("total_volumes") or [])
        rows = resample_to_4h(prices, volumes)
        if len(rows) < 200:
            print(f"      only {len(rows)} bars — skip")
            fails += 1
            time.sleep(2)
            continue
        out.write_text(json.dumps(rows))
        days_covered = (rows[-1]["ts"] - rows[0]["ts"]) / 86400_000
        print(f"      wrote {len(rows)} 4h bars covering {days_covered:.0f} days")
        successes += 1
        time.sleep(2)

    print(f"\nDone: {successes} success, {fails} fail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
