#!/usr/bin/env python3
"""Refresh the Arena survival-board snapshot — the worker side of /arena/board.

Building the board hits the GeckoTerminal feed (~2 throttled calls per token), so it
must NOT run inside an HTTP request. This worker computes the board once and writes
`GECKO_STATE_DIR/arena_board.json`, which `agent_api GET /arena/board` then serves
instantly. Mirror of refresh_market_temp.py.

    # cron (e.g. every 5 min):
    uv run python refresh_arena_board.py
    # custom token list:
    GECKO_ARENA_TOKENS="WIF:EKpQ...,BONK:DezX..." uv run python refresh_arena_board.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import arena_score as asc  # noqa: E402
from strategies.basedbid_feed import BasedBidCandleProvider  # noqa: E402


def _tokens_from_env() -> dict[str, str] | None:
    raw = os.environ.get("GECKO_ARENA_TOKENS", "").strip()
    if not raw:
        return None
    return {p.split(":")[0]: p.split(":")[1] for p in raw.split(",") if ":" in p}


def main() -> None:
    toks = _tokens_from_env()
    board = asc.build_board(BasedBidCandleProvider(), toks, public=True)
    path = asc.save_board_snapshot(board)
    print(f"arena board: {len(board)} tokens → {path}")
    for r in board:
        print(f"  {r['name']:8} band={r['band']:11} risk={r['risk_bucket']:10} bars={r['bars']}")


if __name__ == "__main__":
    main()
