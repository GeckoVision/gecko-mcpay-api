#!/usr/bin/env python3
"""WS-carry — Hyperliquid funding-rate ingestion (the +EV pivot off meme-spot OHLCV).

Seven nulls proved per-trade DIRECTION is unpredictable on Solana-meme spot. Carry
(funding) is NON-directional — you harvest the funding a delta-hedged position earns,
so direction stops being the binding constraint. This pulls per-coin HOURLY funding
history from the Hyperliquid public info API (no key; free market data) for a liquid
universe, into tapes for carry research (persistence, cross-sectional, tail risk).

HL `fundingHistory` caps ~500 records/call (~20 days hourly), so this paginates in
windows and dedups by timestamp. Output:
  scripts/calibration/data/funding/{COIN}_funding.json -> [{ts, fundingRate, premium}]
ascending by ts. Plus a coverage manifest.

Run: uv run python scripts/calibration/ingest_hyperliquid_funding.py [--days 180] [--coins BTC,ETH,...]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(_HERE, "data", "funding")
HL_INFO = "https://api.hyperliquid.xyz/info"
DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX", "DOGE", "WIF", "ARB", "OP", "LINK"]
WINDOW_DAYS = 15  # per-call window (< the ~500-record/~20d cap, with margin)


def _fmt(ms: float) -> str:
    return dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _post(payload: dict) -> object:
    req = urllib.request.Request(
        HL_INFO, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 — fixed HTTPS host
        return json.loads(r.read().decode())


def funding_history(coin: str, days: int) -> list[dict]:
    """Paginated hourly funding history for `coin` over the last `days`. Dedup by ts."""
    now = int(time.time() * 1000)
    start = now - days * 86_400_000
    by_ts: dict[int, dict] = {}
    cursor = start
    while cursor < now:
        end = min(cursor + WINDOW_DAYS * 86_400_000, now)
        try:
            recs = _post(
                {"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end}
            )
        except Exception as e:  # noqa: BLE001 — one bad window must not abort the coin
            print(f"    {coin}: window {cursor} error ({type(e).__name__}); skipping window")
            cursor = end
            continue
        if isinstance(recs, list):
            for r in recs:
                t = int(r.get("time", 0))
                if t:
                    by_ts[t] = {
                        "ts": t,
                        "fundingRate": float(r.get("fundingRate", 0) or 0),
                        "premium": float(r.get("premium", 0) or 0),
                    }
        cursor = end
        time.sleep(0.12)  # politeness vs HL rate limits
    return [by_ts[t] for t in sorted(by_ts)]


def run(coins: list[str], days: int) -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 92)
    print(f"HYPERLIQUID FUNDING INGESTION — {len(coins)} coins x {days}d hourly")
    print("=" * 92)
    report: dict = {}
    for coin in coins:
        recs = funding_history(coin, days)
        if not recs:
            print(f"  {coin:6} no data (not a HL perp?) — skip")
            continue
        with open(os.path.join(OUT_DIR, f"{coin}_funding.json"), "w") as f:
            json.dump(recs, f)
        rates = [r["fundingRate"] for r in recs]
        ts = [r["ts"] for r in recs]
        ann = sum(rates) / len(rates) * 24 * 365 * 100  # mean hourly -> annualized %
        report[coin] = {"n": len(recs), "first": ts[0], "last": ts[-1], "ann_mean_pct": ann}
        print(
            f"  {coin:6} n={len(recs):5}  {_fmt(ts[0])} -> {_fmt(ts[-1])}  "
            f"mean-funding annualized={ann:+.1f}%  "
            f"(hrly min/med/max=[{min(rates):+.5f}/{sorted(rates)[len(rates) // 2]:+.5f}/{max(rates):+.5f}])"
        )
    manifest = os.path.join(OUT_DIR, "funding_coverage.json")
    with open(manifest, "w") as f:
        json.dump(
            {"generated": dt.datetime.utcnow().isoformat() + "Z", "days": days, "coins": report},
            f,
            indent=2,
        )
    print(f"\nwrote {manifest}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--coins", default=",".join(DEFAULT_COINS))
    a = ap.parse_args()
    run([c.strip().upper() for c in a.coins.split(",") if c.strip()], a.days)
