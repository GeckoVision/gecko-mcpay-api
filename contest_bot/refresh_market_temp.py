#!/usr/bin/env python3
"""Refresh the market-temperature snapshot — the worker side of news sourcing.

Computes a MarketTemp from an OKX `news_get_coin_sentiment` response + recent
headlines and writes the snapshot `GECKO_STATE_DIR/market_temp.json` that
`agent_api GET /market-temp` (and the bots) read.

The actual OKX fetch is the operator/cron's job (OKX news REST / the okx-agent-
trade-kit MCP `news_get_coin_sentiment` + `news_get_latest`) — this script takes
that JSON so it stays decoupled from the (founder-WIP) news-ingest plumbing.

    # cron: fetch OKX sentiment+headlines → pipe in
    uv run python refresh_market_temp.py --sentiment okx_sentiment.json --headlines headlines.txt
    # quick demo with the 2026-06-04 risk-off snapshot:
    uv run python refresh_market_temp.py --demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import market_temp as mt  # noqa: E402


def _demo_inputs() -> tuple[dict, list[str], dict]:
    # the real OKX 24h sentiment + 3d moves sourced 2026-06-04 (risk-off macro)
    resp = {"data": [{"details": [
        {"ccy": "BTC", "mentionCnt": "2749", "sentiment": {"bullishRatio": "0.23", "bearishRatio": "0.44"}},
        {"ccy": "ETH", "mentionCnt": "815", "sentiment": {"bullishRatio": "0.27", "bearishRatio": "0.38"}},
        {"ccy": "SOL", "mentionCnt": "705", "sentiment": {"bullishRatio": "0.43", "bearishRatio": "0.16"}},
        {"ccy": "XRP", "mentionCnt": "96", "sentiment": {"bullishRatio": "0.54", "bearishRatio": "0.11"}},
        {"ccy": "DOGE", "mentionCnt": "66", "sentiment": {"bullishRatio": "0.53", "bearishRatio": "0.17"}},
    ]}]}
    headlines = [
        "Bitcoin falls to pre-Iran conflict low as crypto slide extends",
        "OECD predicts spate of recessions globally if Iran conflict drags into 2027",
        "Losses from crypto hacks in May declined 90% month-over-month",
    ]
    moves = {"BTC": -9.46, "ETH": -8.04, "SOL": -10.13, "XRP": -8.09, "DOGE": -6.72}
    return resp, headlines, moves


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sentiment", help="OKX news_get_coin_sentiment response JSON file")
    ap.add_argument("--headlines", help="newline-separated recent headlines file")
    ap.add_argument("--moves", help="optional JSON {COIN: pct_move} for divergence flags")
    ap.add_argument("--demo", action="store_true", help="use the 2026-06-04 risk-off snapshot")
    args = ap.parse_args()

    if args.demo:
        resp, headlines, moves = _demo_inputs()
    else:
        if not args.sentiment:
            ap.error("--sentiment is required (or use --demo)")
        with open(args.sentiment) as f:
            resp = json.load(f)
        headlines = []
        if args.headlines:
            with open(args.headlines) as f:
                headlines = [ln.strip() for ln in f if ln.strip()]
        moves = None
        if args.moves:
            with open(args.moves) as f:
                moves = json.load(f)

    coins = mt.from_okx_sentiment(resp)
    signal = mt.compute_market_temp(coins, headlines=headlines, price_moves=moves)
    path = mt.save_snapshot(signal)
    print(f"market-temp = {signal.temp:+.2f} {signal.label.upper()} → {path}")
    print("drivers:", signal.drivers)
    for d in signal.divergences:
        print("  diverge:", d)


if __name__ == "__main__":
    main()
