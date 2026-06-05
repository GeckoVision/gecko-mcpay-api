#!/usr/bin/env python3
"""based.bid Arena — verified-safe SCORING demo (the falsifier + pitch artifact).

The Arena's wedge is NOT "who made the most money" — it's "which agent was VERIFIED
SAFE / didn't blow up." This script proves the scoring pipeline end-to-end on REAL
graduated-token OHLCV (via the based.bid feed → GeckoTerminal): for each token it
computes survival metrics (max drawdown, realized vol, return) and assigns a
BUCKETED safety band (never a raw public score — CLAUDE.md no-public-raw-floats).

Tokens here are HAND-PICKED liquid graduated Solana tokens as representative stand-ins
(real based.bid mints swap in once we have their token list). Read-only, no trades.

    uv run python scripts/calibration/basedbid_arena_score.py
"""

from __future__ import annotations

import math
import os
import sys

_CB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "contest_bot")
if _CB not in sys.path:
    sys.path.insert(0, _CB)

from strategies.basedbid_feed import BasedBidCandleProvider  # noqa: E402

# Hand-picked graduated Solana tokens (representative stand-ins for based.bid tokens —
# liquid, have GeckoTerminal pools so the feed returns real OHLCV).
HAND_PICKED: dict[str, str] = {
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "JTO": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
}


def _max_drawdown(closes: list[float]) -> float:
    """Worst peak-to-trough drop over the window, as a positive fraction."""
    peak = closes[0]
    mdd = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            mdd = max(mdd, (peak - c) / peak)
    return mdd


def _realized_vol(closes: list[float]) -> float:
    """Stdev of per-bar returns (annualization-agnostic; relative risk proxy)."""
    rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 2:
        return 0.0
    mu = sum(rets) / len(rets)
    return math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))


def _band(mdd: float, ret: float) -> str:
    """Verified-safe SURVIVAL band (bucketed, never a raw score on a public surface).
    Survival is about not blowing up; return is secondary."""
    if mdd >= 0.50:
        return "eliminated"      # >50% drawdown = blew up
    if mdd >= 0.30:
        return "at-risk"         # deep drawdown survived
    if ret >= 0:
        return "surviving+"      # contained drawdown AND not underwater
    return "surviving"           # contained drawdown, modestly underwater


def main() -> None:
    p = BasedBidCandleProvider()
    print("\n── based.bid Arena — verified-safe SURVIVAL board (5m, ~last 200 bars) ──")
    print("   (bucketed bands, not raw PnL — survival is the KPI, not max profit)\n")
    rows = []
    for sym, mint in HAND_PICKED.items():
        candles = p.get_candles(mint, bar="5m", limit=200, drop_forming=True)
        if not candles:
            print(f"  {sym:8} — no DEX pool / no data (pre-graduation?)")
            continue
        closes = [c["close"] for c in candles]
        mdd = _max_drawdown(closes)
        vol = _realized_vol(closes)
        ret = closes[-1] / closes[0] - 1.0
        band = _band(mdd, ret)
        rows.append((sym, band, mdd, vol, ret, len(closes)))
    # sort by band severity then drawdown (survival-first ranking)
    order = {"surviving+": 0, "surviving": 1, "at-risk": 2, "eliminated": 3}
    rows.sort(key=lambda r: (order.get(r[1], 9), r[2]))
    print(f"  {'token':8} {'band':12} {'max_dd':>8} {'vol':>8} {'window_ret':>11}")
    for sym, band, mdd, vol, ret, n in rows:
        print(f"  {sym:8} {band:12} {mdd:>7.1%} {vol:>7.2%} {ret:>+10.1%}  (n={n})")
    print("\n  Verdict: the SAFE agent is the one whose band stays 'surviving', not the")
    print("  one with the biggest window_ret. That distinction IS the Gecko wedge.\n")


if __name__ == "__main__":
    main()
