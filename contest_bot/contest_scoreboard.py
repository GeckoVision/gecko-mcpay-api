#!/usr/bin/env python3
"""Bot-contest scoreboard — rank the paper bots by realized PnL + survival.

Reads each contestant's bot_state.json (GECKO_STATE_DIR-isolated). Paper only;
these strategies are −EV per the gauntlet, so this measures BEHAVIOR / least-bad,
NOT validated alpha. "Best until tomorrow wins" = top realized paper PnL with a
survival check (not blown up).

    uv run python contest_scoreboard.py            # one-shot table
    uv run python contest_scoreboard.py --json      # machine snapshot
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

_HERE = os.path.dirname(os.path.abspath(__file__))

# label -> state file. Legacy Setup-C bot keeps state in contest_bot/bot_state.json.
CONTESTANTS = {
    "trend_breakout": f"{_HERE}/state/contest/trend_breakout/bot_state.json",
    "mean_reversion": f"{_HERE}/state/contest/mean_reversion/bot_state.json",
    "range_fade": f"{_HERE}/state/contest/range_fade/bot_state.json",
    "legacy_gate": f"{_HERE}/bot_state.json",
}
START_USD = 100.0


def _score(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        d = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        return None
    pos = d.get("positions", []) or []
    closed = [p for p in pos if p.get("exit_ts") or p.get("status") in ("closed", "exited")]
    openp = [p for p in pos if p not in closed]
    pnl = round(sum(float(p.get("pnl_usd") or 0.0) for p in closed), 4)
    wins = sum(1 for p in closed if float(p.get("pnl_usd") or 0.0) > 0)
    # liveness
    saved = d.get("saved_at")
    age_min = None
    if saved:
        try:
            age_min = round((datetime.now(UTC) - datetime.fromisoformat(saved)).total_seconds() / 60, 1)
        except (ValueError, TypeError):
            pass
    return {
        "pnl_usd": pnl,
        "pnl_pct": round(100 * pnl / START_USD, 2),
        "trades": len(closed),
        "open": len(openp),
        "win_rate": round(100 * wins / len(closed), 1) if closed else None,
        "poll": d.get("poll_count"),
        "age_min": age_min,  # minutes since last state write (freshness)
        "alive": (age_min is not None and age_min < 10),
    }


def main() -> int:
    rows = {name: _score(p) for name, p in CONTESTANTS.items()}
    if "--json" in sys.argv:
        print(json.dumps({"as_of": datetime.now(UTC).isoformat(), "board": rows}, indent=2))
        return 0
    live = {k: v for k, v in rows.items() if v}
    ranked = sorted(live.items(), key=lambda kv: kv[1]["pnl_usd"], reverse=True)
    print(f"\n=== BOT CONTEST — {datetime.now(UTC):%Y-%m-%d %H:%M UTC} (paper; least-bad wins) ===")
    print(f"{'rank':<5}{'strategy':<18}{'pnl$':>9}{'pnl%':>8}{'trades':>8}{'open':>6}{'win%':>7}{'fresh':>8}")
    for i, (name, s) in enumerate(ranked, 1):
        fresh = "live" if s["alive"] else (f"{s['age_min']}m" if s["age_min"] is not None else "—")
        wr = f"{s['win_rate']}" if s["win_rate"] is not None else "—"
        print(f"{i:<5}{name:<18}{s['pnl_usd']:>9.2f}{s['pnl_pct']:>7.1f}%{s['trades']:>8}{s['open']:>6}{wr:>7}{fresh:>8}")
    missing = [k for k, v in rows.items() if not v]
    if missing:
        print(f"(not started / no state yet: {', '.join(missing)})")
    if ranked:
        lead = ranked[0]
        print(f"\nLEADER: {lead[0]}  {lead[1]['pnl_usd']:+.2f} USD ({lead[1]['trades']} trades)")
    print("Note: −EV per gauntlet — this is behavior data, not validated alpha.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
