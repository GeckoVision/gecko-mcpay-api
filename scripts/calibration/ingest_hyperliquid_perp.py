#!/usr/bin/env python3
"""Hyperliquid perp 1h close-price ingestion (for the realistic carry basis PnL).

Pulls per-coin hourly perp candles (HL candleSnapshot) -> data/perp/{COIN}_perp.json
([{ts, close}]). Combined with the funding `premium` (already ingested) this gives the
basis PnL the optimistic carry assumed away. Paginated + dedup.

Run: uv run python scripts/calibration/ingest_hyperliquid_perp.py [--days 180] [--coins BTC,ETH,...]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(_HERE, "data", "perp")
HL_INFO = "https://api.hyperliquid.xyz/info"
DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX", "DOGE", "WIF", "ARB", "OP", "LINK"]
WINDOW_DAYS = 40  # per-call window (< the ~5000-candle cap)


def _fmt(ms: float) -> str:
    return dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _post(payload: dict) -> object:
    req = urllib.request.Request(
        HL_INFO, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def perp_candles(coin: str, days: int) -> list[dict]:
    now = int(time.time() * 1000)
    cursor = now - days * 86_400_000
    by_ts: dict[int, float] = {}
    while cursor < now:
        end = min(cursor + WINDOW_DAYS * 86_400_000, now)
        try:
            recs = _post(
                {
                    "type": "candleSnapshot",
                    "req": {"coin": coin, "interval": "1h", "startTime": cursor, "endTime": end},
                }
            )
        except Exception as e:
            print(f"    {coin}: window error ({type(e).__name__}); skip")
            cursor = end
            continue
        if isinstance(recs, list):
            for r in recs:
                t = int(r.get("t", 0))
                if t:
                    by_ts[t] = float(r.get("c", 0) or 0)
        cursor = end
        time.sleep(0.12)
    return [{"ts": t, "close": by_ts[t]} for t in sorted(by_ts)]


def run(coins: list[str], days: int) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 88)
    print(f"HYPERLIQUID PERP-CANDLE INGESTION — {len(coins)} coins x {days}d hourly")
    print("=" * 88)
    for coin in coins:
        recs = perp_candles(coin, days)
        if not recs:
            print(f"  {coin:6} no data — skip")
            continue
        with open(os.path.join(OUT_DIR, f"{coin}_perp.json"), "w") as f:
            json.dump(recs, f)
        ts = [r["ts"] for r in recs]
        print(
            f"  {coin:6} n={len(recs):5}  {_fmt(ts[0])} -> {_fmt(ts[-1])}  last_close={recs[-1]['close']}"
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--coins", default=",".join(DEFAULT_COINS))
    a = ap.parse_args()
    run([c.strip().upper() for c in a.coins.split(",") if c.strip()], a.days)
