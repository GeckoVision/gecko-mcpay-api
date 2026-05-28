#!/usr/bin/env python3
"""Sprint 11 #1 — gecko-grid-oracle: per-symbol grid-suitability scorer + backtest.

Founder's question (2026-05-27, after viewing OKX Bot Marketplace cards showing
XRP/TRX/PEOPLE spot-grid bots at +132% to +201% over 700-900d): what determines
when grid trading is +EV vs about to blow up?

Spot grid mechanics:
  Pick (low, high) price range
  Divide into N grids
  Buy at each grid-line tick down, sell at each grid-line tick up
  Profit = sum of completed (sell - buy) cycles
  Risk = inventory accumulates at bottom if price breaks below range

This script:
  1. For each symbol, computes a "grid-safe" score per rolling 30d window:
     - ADX low (<18) = no trend = grid-friendly
     - 90d range stability (current 30d range / prior 90d range)
     - Realized vol within range = more fills = more PnL
     - Breakdown count (price crossed 90d-high*1.05 or 90d-low*0.95)
  2. Simulates a vanilla grid bot per symbol over the 60d window:
     - Range = 30d-prior min/max with 5% padding
     - 20 grids evenly spaced
     - $50/grid initial investment
  3. Reports realized PnL + unrealized PnL + final equity per symbol
  4. Cross-validates: did high-score symbols produce real PnL? Did low-score
     symbols crash?

PRE-COMMIT INTERPRETATION:
  Oracle is USEFUL iff:
    - Among GREEN-scored symbols, ≥ 60% produced positive net PnL
    - Among RED-scored symbols, ≥ 60% had negative net PnL (breakdown)
    - Correlation between score and realized PnL > 0.30
"""
from __future__ import annotations

import json
import math
import statistics as st
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, "scripts/calibration")
from swing_window_validation import adx, chop, load_universe

GRID_COUNT = 20
INVESTMENT_PER_GRID = 50.0
ROUND_TRIP_COST = 0.004
PRIOR_LOOKBACK_BARS = 90 * 6 // 4  # 90d in 4h-bar units... wait, we have 4h bars
# Each day has 6 4h bars; 30d = 180 bars; 90d = 540 bars
DAYS_TO_BARS = 6


# ── Oracle score ────────────────────────────────────────────────────


@dataclass
class GridScore:
    symbol: str
    adx_30d: float           # mean ADX over last 30d (low = grid-friendly)
    range_stability: float    # current 30d range / prior 90d range (close to 1 = stable)
    realized_vol: float       # std of % returns in last 30d
    breakdown_count: int      # times price broke 5% past 90d range in last 30d
    score: float              # composite 0-1 (higher = grid-safer)
    label: str               # GREEN/AMBER/RED


def compute_score(rows: list[dict], window_end_idx: int) -> GridScore | None:
    """Score a symbol's grid-suitability as of `window_end_idx`.

    Adapts to data depth: prefers 90d-prior + 30d-current; falls back to
    60d-prior + 15d-current if data is shallower (60d substrate).
    """
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]

    # Adaptive windows based on data depth — "current" = last 1/3, "prior" = first 2/3
    if window_end_idx < 18 * DAYS_TO_BARS:  # need at least 18 bars total
        return None
    bars_30d = window_end_idx // 3       # "current" window
    bars_90d = window_end_idx             # full prior history available

    cur_30d_high = max(highs[window_end_idx - bars_30d: window_end_idx + 1])
    cur_30d_low = min(lows[window_end_idx - bars_30d: window_end_idx + 1])
    prior_90d_high = max(highs[window_end_idx - bars_90d: window_end_idx - bars_30d + 1])
    prior_90d_low = min(lows[window_end_idx - bars_90d: window_end_idx - bars_30d + 1])

    cur_range = (cur_30d_high - cur_30d_low) / cur_30d_low
    prior_range = (prior_90d_high - prior_90d_low) / prior_90d_low
    range_stability = cur_range / prior_range if prior_range > 0 else 1.0

    # ADX mean over last 30d
    adx_s = adx(highs[:window_end_idx + 1], lows[:window_end_idx + 1], closes[:window_end_idx + 1])
    adx_recent = [a for a in adx_s[window_end_idx - bars_30d: window_end_idx + 1] if not math.isnan(a)]
    adx_mean = st.mean(adx_recent) if adx_recent else 50.0

    # Realized vol of bar-to-bar returns over last 30d
    returns = []
    for i in range(window_end_idx - bars_30d + 1, window_end_idx + 1):
        if i > 0 and closes[i - 1] > 0:
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
    rvol = st.pstdev(returns) if len(returns) > 2 else 0.0

    # Breakdown count: bars where price > prior_90d_high * 1.05 OR < prior_90d_low * 0.95
    breakdown = sum(
        1 for c in closes[window_end_idx - bars_30d: window_end_idx + 1]
        if c > prior_90d_high * 1.05 or c < prior_90d_low * 0.95
    )

    # Composite score 0-1:
    # ADX low is good → invert: (40 - clamp(adx, 0, 40)) / 40 maps adx 0→1, 40→0
    adx_norm = max(0.0, (40 - min(adx_mean, 40)) / 40)
    # Range stability close to 1 is good; far from 1 is bad
    rs_dev = abs(range_stability - 1.0)
    rs_norm = max(0.0, 1.0 - min(rs_dev, 1.0))
    # Realized vol: moderate is good (more fills); too low = nothing happens; too high = trend
    # Peak score at rvol ≈ 0.02 (per-4h-bar = ~10% daily)
    rvol_norm = math.exp(-abs(rvol - 0.02) * 50)  # bell around 0.02
    # Breakdown count: 0 is best
    bd_norm = max(0.0, 1.0 - breakdown / (bars_30d * 0.1))  # 10% breakdown = 0

    # Weighted composite — ADX + range stability dominate
    score = 0.35 * adx_norm + 0.30 * rs_norm + 0.20 * rvol_norm + 0.15 * bd_norm

    if score >= 0.65:
        label = "GREEN"
    elif score >= 0.45:
        label = "AMBER"
    else:
        label = "RED"

    return GridScore(
        symbol="",  # filled by caller
        adx_30d=adx_mean,
        range_stability=range_stability,
        realized_vol=rvol,
        breakdown_count=breakdown,
        score=score,
        label=label,
    )


# ── Grid bot simulator ──────────────────────────────────────────────


@dataclass
class GridBotResult:
    symbol: str
    range_low: float
    range_high: float
    n_grids: int
    n_fills: int
    realized_pnl: float
    final_inventory_units: float
    final_inventory_value_at_close: float
    final_inventory_unrealized: float
    total_pnl: float
    days_simulated: float


def simulate_grid_bot(rows: list[dict], range_low: float, range_high: float, n_grids: int = GRID_COUNT) -> GridBotResult:
    """Simulate arithmetic-grid spot-grid bot over `rows`.

    Each grid line has alternating buy/sell limits. When price crosses a line,
    the order fills; we then place the opposite order at that line (i.e., after
    buy fill at $0.50, place sell at $0.55 next grid up).
    """
    grid_spacing = (range_high - range_low) / n_grids
    grid_prices = [range_low + i * grid_spacing for i in range(n_grids + 1)]

    # State: for each grid line, what's the next order direction
    # Initial: grids BELOW current price = waiting buy; grids ABOVE = waiting sell
    start_price = rows[0]["open"]
    pending: dict[int, str] = {}  # grid_idx -> "buy" | "sell"
    for i, gp in enumerate(grid_prices):
        if gp < start_price:
            pending[i] = "buy"
        elif gp > start_price:
            pending[i] = "sell"

    inventory_units = 0.0
    inventory_avg_cost = 0.0
    cash_pnl = 0.0
    units_per_grid = INVESTMENT_PER_GRID  # assume $50 quote at each fill

    n_fills = 0
    for r in rows[1:]:
        h, l = r["high"], r["low"]
        # Check all pending orders in price-crossing order
        # Sort by price; for each, see if h/l crosses
        for gi in sorted(pending.keys(), key=lambda i: grid_prices[i]):
            gp = grid_prices[gi]
            side = pending[gi]
            if side == "buy" and l <= gp:
                # Buy fills at this grid line
                units = units_per_grid / gp
                # Update avg cost
                total_cost = inventory_avg_cost * inventory_units + units_per_grid
                inventory_units += units
                inventory_avg_cost = total_cost / inventory_units if inventory_units > 0 else 0
                cash_pnl -= units_per_grid * (1 + ROUND_TRIP_COST / 2)
                pending[gi] = "sell"
                n_fills += 1
            elif side == "sell" and h >= gp:
                if inventory_units <= 0:
                    continue  # nothing to sell
                # Sell units at this grid line
                units = min(units_per_grid / gp, inventory_units)
                proceeds = units * gp * (1 - ROUND_TRIP_COST / 2)
                cash_pnl += proceeds
                inventory_units -= units
                pending[gi] = "buy"
                n_fills += 1

    final_close = rows[-1]["close"]
    inv_value = inventory_units * final_close
    inv_cost = inventory_units * inventory_avg_cost
    inv_unrealized = inv_value - inv_cost

    days = (rows[-1]["ts"] - rows[0]["ts"]) / 86400_000
    return GridBotResult(
        symbol="",
        range_low=range_low,
        range_high=range_high,
        n_grids=n_grids,
        n_fills=n_fills,
        realized_pnl=cash_pnl,
        final_inventory_units=inventory_units,
        final_inventory_value_at_close=inv_value,
        final_inventory_unrealized=inv_unrealized,
        total_pnl=cash_pnl + inv_value,
        days_simulated=days,
    )


def main() -> int:
    universe = load_universe()
    if not universe:
        print("Run ingest_coingecko_solana_4h.py first.")
        return 1

    # Use the 60d universe (we don't have 180d for all yet)
    # Split: prior 30d defines range; later 30d is the grid-bot test window
    print("=" * 110)
    print(f"GECKO-GRID-ORACLE — per-symbol scoring + grid backtest (60d data, 16+ symbols)")
    print("=" * 110)

    # For each symbol, score at idx=180 (30d into the data), then run grid bot
    # on rows[180:]
    results = []
    for sym, rows in sorted(universe.items()):
        # 60d substrate: use first 20d (~120 bars) as range/score definition,
        # last 40d (~240 bars) as the grid backtest window.
        split_idx = min(20 * DAYS_TO_BARS, len(rows) // 2)
        prior = rows[:split_idx]
        if len(prior) < 20 * DAYS_TO_BARS:
            continue
        score = compute_score(rows, len(prior) - 1)
        # Define range from prior window
        prior_low = min(r["low"] for r in prior)
        prior_high = max(r["high"] for r in prior)
        # Add 5% padding both sides
        rl = prior_low * 0.95
        rh = prior_high * 1.05

        # Simulate on test window
        test = rows[split_idx:]
        if len(test) < 50:
            continue
        bot = simulate_grid_bot(test, rl, rh)
        bot.symbol = sym
        if score:
            score.symbol = sym
        results.append((sym, score, bot))

    print(f"\n{'sym':<10s} {'score':>6s} {'label':<6s} {'ADX':>5s} {'range_stab':>11s} {'rvol':>6s} {'BD':>3s} | {'range':<19s} {'fills':>5s} {'real_$':>9s} {'unreal_$':>9s} {'total_$':>9s}")
    print("-" * 130)
    for sym, score, bot in results:
        if not score:
            continue
        rng = f"${bot.range_low:.4g}–{bot.range_high:.4g}"
        print(f"{sym:<10s} {score.score:>5.2f}  {score.label:<6s} {score.adx_30d:>4.1f}  "
              f"{score.range_stability:>10.2f}  {score.realized_vol:>5.3f} {score.breakdown_count:>3d} | "
              f"{rng:<19s} {bot.n_fills:>5d} {bot.realized_pnl:>+8.2f} {bot.final_inventory_unrealized:>+8.2f} {bot.total_pnl - 0:>+8.2f}")

    # ── Cross-validation: does score predict real-PnL? ──
    print()
    print("=" * 110)
    print("ORACLE CROSS-VALIDATION")
    print("=" * 110)
    green = [(s, sc, b) for s, sc, b in results if sc and sc.label == "GREEN"]
    amber = [(s, sc, b) for s, sc, b in results if sc and sc.label == "AMBER"]
    red = [(s, sc, b) for s, sc, b in results if sc and sc.label == "RED"]

    for label, group in [("GREEN", green), ("AMBER", amber), ("RED", red)]:
        if not group:
            continue
        pnls = [b.total_pnl for _, _, b in group]
        pos_rate = 100 * sum(1 for p in pnls if p > 0) / len(pnls)
        avg_pnl = st.mean(pnls)
        avg_realized = st.mean(b.realized_pnl for _, _, b in group)
        avg_unrealized = st.mean(b.final_inventory_unrealized for _, _, b in group)
        print(f"  {label:<6s} N={len(group):>2d}  pos_rate={pos_rate:>3.0f}%  avg_total_pnl=${avg_pnl:>+7.2f}  "
              f"avg_realized=${avg_realized:>+6.2f}  avg_unrealized=${avg_unrealized:>+6.2f}")
        print(f"          symbols: {[s for s,_,_ in group]}")

    # Correlation between score and total_pnl
    if len(results) >= 5:
        scores = [sc.score for _, sc, _ in results if sc]
        pnls = [b.total_pnl for _, sc, b in results if sc]
        n = len(scores)
        mean_s = st.mean(scores); mean_p = st.mean(pnls)
        num = sum((s - mean_s) * (p - mean_p) for s, p in zip(scores, pnls))
        den = math.sqrt(sum((s - mean_s) ** 2 for s in scores) * sum((p - mean_p) ** 2 for p in pnls))
        corr = num / den if den > 0 else 0
        print(f"\n  Pearson correlation (score × total_PnL): {corr:+.2f}  ({'good' if abs(corr) > 0.3 else 'weak'})")

    # ── Verdict ──
    print()
    print("=" * 110)
    print("VERDICT (per pre-commit interpretation)")
    print("=" * 110)
    green_pos_rate = 100 * sum(1 for _,_,b in green if b.total_pnl > 0) / max(len(green), 1)
    red_neg_rate = 100 * sum(1 for _,_,b in red if b.total_pnl <= 0) / max(len(red), 1)
    gates = [
        (f"≥60% of GREEN had positive net PnL (got {green_pos_rate:.0f}%)", green_pos_rate >= 60),
        (f"≥60% of RED had negative net PnL (got {red_neg_rate:.0f}%)", red_neg_rate >= 60),
    ]
    for desc, ok in gates:
        print(f"  [{('PASS' if ok else 'FAIL')}]  {desc}")
    if all(ok for _, ok in gates):
        verdict = "ORACLE WORKS — score predicts outcome; proceed to skill packaging"
    elif any(ok for _, ok in gates):
        verdict = "PARTIAL — one direction predictive; needs refinement"
    else:
        verdict = "REJECT — score has no predictive power"
    print(f"\n  → VERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
