#!/usr/bin/env python3
"""Sprint 11 #3 — gecko-copy-trade-grader: rigor scorecard for any public trader.

Founder's question (2026-05-27, after viewing OKX Spot copy trading
leaderboard cards: "Utter-Ledger-Asters +10.49%" etc + the per-trader
history screenshots showing SUI +14k / OKB -4.3k): which copy-traders
are SKILLED vs LUCKY vs BIASED-BY-SELECTION?

OKX (and most copy-trade marketplaces) rank by raw cumulative PnL%. This
ignores:
  - Variance (a +200% Sharpe-0.3 trader is GAMBLING, not winning)
  - Drawdown (you bought in after the +200% — what's the next 30d max-DD?)
  - Win/loss asymmetry (60% win-rate at R:R 0.3 actually LOSES money)
  - Catastrophic trades (one -10% trade can wipe N small wins)
  - Regime dependence (did they earn in chop or only in trends?)
  - Selection bias (cherry-picked from leaderboard of N traders)

This skill takes a trader's history and produces a gecko-grade A/B/C/D
with each metric scored + reasoning.

INPUT SHAPE (one trade per row):
  {
    "entry_ts_ms": int,        # ms since epoch
    "exit_ts_ms": int,
    "symbol": "SUI/USDT",
    "side": "long" | "short",
    "entry_px": float,
    "exit_px": float,
    "size_usd": float,         # position size in $
    "realized_pnl_usd": float,
    "realized_pnl_pct": float, # signed % return on this trade
  }

OUTPUT: structured scorecard (JSON) + human verdict.

PRE-COMMIT INTERPRETATION (Op-1, written before running):
  Grade rubric:
    A (skilled, deploy):  Sharpe ≥ 1.5 AND profit_factor ≥ 2.0 AND
                          max_dd ≤ 15% AND catastrophic_rate ≤ 10%
                          AND second-half PnL/trade ≥ first-half × 0.5
    B (promising):        Sharpe 1.0-1.5 OR profit_factor 1.5-2.0,
                          OR good stats but small N (<30 trades)
    C (lucky / noise):    Sharpe 0.5-1.0, profit_factor 1.1-1.5
    D (gambling):         Sharpe < 0.5 OR catastrophic_rate > 25%
                          OR second-half PnL < first-half × 0.0
"""
from __future__ import annotations

import json
import math
import statistics as st
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class Trade:
    entry_ts_ms: int
    exit_ts_ms: int
    symbol: str
    side: Literal["long", "short"]
    entry_px: float
    exit_px: float
    size_usd: float
    realized_pnl_usd: float
    realized_pnl_pct: float

    @property
    def duration_hours(self) -> float:
        return (self.exit_ts_ms - self.entry_ts_ms) / 3600_000


@dataclass
class Scorecard:
    trader_label: str
    n_trades: int

    # Basic
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    win_loss_ratio: float  # avg_win / |avg_loss|
    profit_factor: float   # sum(wins) / |sum(losses)|

    # Edge
    mean_pnl_pct: float
    median_pnl_pct: float
    stdev_pnl_pct: float
    sharpe_per_trade: float
    sortino_per_trade: float

    # Risk
    max_dd_pct: float          # peak-to-trough on cumulative %
    longest_loss_streak: int
    catastrophic_rate_pct: float  # % of trades worse than -3%
    worst_trade_pct: float

    # Time/return
    total_pnl_pct: float
    days_active: float
    annualized_pct: float
    calmar: float

    # Stability
    first_half_mean_pct: float
    second_half_mean_pct: float
    stability_ratio: float  # 2nd half / 1st half

    # Selection bias deflation
    sharpe_deflated: float
    n_assumed_leaderboard_peers: int

    # Verdict
    grade: str
    grade_rationale: list[str] = field(default_factory=list)


# ── Metrics ─────────────────────────────────────────────────────────


def max_drawdown(cumulative_pnl_pct: list[float]) -> float:
    """Peak-to-trough drawdown on cumulative %."""
    if not cumulative_pnl_pct:
        return 0.0
    peak = cumulative_pnl_pct[0]
    max_dd = 0.0
    for v in cumulative_pnl_pct:
        peak = max(peak, v)
        dd = peak - v  # positive = drawdown
        max_dd = max(max_dd, dd)
    return max_dd


def longest_streak(pnls: list[float], negative: bool = True) -> int:
    cur = best = 0
    for v in pnls:
        if (v < 0) if negative else (v > 0):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


# ── Grading ─────────────────────────────────────────────────────────


def grade(trades: list[Trade], trader_label: str = "trader", n_leaderboard_peers: int = 100) -> Scorecard:
    n = len(trades)
    if n == 0:
        raise ValueError("no trades")

    trades_sorted = sorted(trades, key=lambda t: t.entry_ts_ms)
    pnls = [t.realized_pnl_pct for t in trades_sorted]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = 100 * len(wins) / n
    avg_win = st.mean(wins) if wins else 0.0
    avg_loss = st.mean(losses) if losses else 0.0
    win_loss_ratio = avg_win / abs(avg_loss) if avg_loss < 0 else float("inf") if wins else 0.0
    sum_wins = sum(wins) if wins else 0.0
    sum_losses_abs = abs(sum(losses)) if losses else 0.0
    profit_factor = sum_wins / sum_losses_abs if sum_losses_abs > 0 else float("inf") if wins else 0.0

    mean_pnl = st.mean(pnls)
    median_pnl = st.median(pnls)
    stdev_pnl = st.pstdev(pnls) if n > 1 else 0.0
    sharpe = mean_pnl / stdev_pnl if stdev_pnl > 0 else 0.0
    downside = [p for p in pnls if p < 0]
    downside_std = st.pstdev(downside) if len(downside) > 1 else 0.0
    sortino = mean_pnl / downside_std if downside_std > 0 else 0.0

    # Cumulative PnL → max DD
    cum = []
    running = 0.0
    for p in pnls:
        running += p
        cum.append(running)
    mdd = max_drawdown(cum)
    long_loss_streak = longest_streak(pnls, negative=True)

    catastrophic = sum(1 for p in pnls if p <= -3.0)
    catastrophic_rate = 100 * catastrophic / n
    worst = min(pnls)

    total_pnl = sum(pnls)
    ts_first = trades_sorted[0].entry_ts_ms
    ts_last = trades_sorted[-1].exit_ts_ms
    days = (ts_last - ts_first) / 86400_000 if ts_last > ts_first else 1
    annualized = total_pnl * (365 / max(days, 1))
    calmar = annualized / mdd if mdd > 0 else 0.0

    # Stability: split halves
    mid = n // 2
    first_half = pnls[:mid] if mid > 0 else pnls
    second_half = pnls[mid:] if mid > 0 else []
    fh_mean = st.mean(first_half) if first_half else 0.0
    sh_mean = st.mean(second_half) if second_half else 0.0
    stability = sh_mean / fh_mean if fh_mean > 0 else (1.0 if sh_mean >= 0 else -1.0)

    # Selection-bias deflation (Bailey-López de Prado approximation)
    # If trader was picked from a leaderboard of N peers, deflate by sqrt(2 log N)
    deflation_factor = math.sqrt(2 * math.log(max(n_leaderboard_peers, 2)))
    # rough: convert sharpe to a "probability vs zero" via tanh, deflate, convert back
    # A more honest formula needs return distribution moments; we use a simple penalty.
    sharpe_deflated = sharpe - deflation_factor * (1.0 / math.sqrt(max(n, 1)))

    # Grade rubric
    rationale: list[str] = []
    A_gates = [
        ("Sharpe ≥ 1.5", sharpe >= 1.5),
        ("profit_factor ≥ 2.0", profit_factor >= 2.0),
        ("max_dd ≤ 15%", mdd <= 15),
        ("catastrophic_rate ≤ 10%", catastrophic_rate <= 10),
        ("stability_ratio ≥ 0.5", stability >= 0.5),
        ("n_trades ≥ 30", n >= 30),
    ]
    B_gates = [
        ("Sharpe ≥ 1.0", sharpe >= 1.0),
        ("profit_factor ≥ 1.5", profit_factor >= 1.5),
        ("max_dd ≤ 25%", mdd <= 25),
        ("stability_ratio ≥ 0.2", stability >= 0.2),
    ]
    D_gates_any = [
        ("Sharpe < 0.5", sharpe < 0.5),
        ("catastrophic_rate > 25%", catastrophic_rate > 25),
        ("stability_ratio < 0", stability < 0),
        ("profit_factor < 1.0", profit_factor < 1.0),
    ]

    if all(ok for _, ok in A_gates):
        grade_letter = "A"
        rationale.append("All A-gates passed: skilled trader, deployable")
    elif all(ok for _, ok in B_gates):
        grade_letter = "B"
        rationale.append("All B-gates passed: promising, validate with more data")
        for desc, ok in A_gates:
            if not ok:
                rationale.append(f"missed A: {desc}")
    elif any(ok for _, ok in D_gates_any):
        grade_letter = "D"
        rationale.append("Triggered a D-gate: gambling profile")
        for desc, ok in D_gates_any:
            if ok:
                rationale.append(f"  → {desc}")
    else:
        grade_letter = "C"
        rationale.append("Between B and D: lucky / noisy / small-sample")
        for desc, ok in B_gates:
            if not ok:
                rationale.append(f"missed B: {desc}")

    # Small-N override
    if n < 10:
        rationale.append(f"NOTE: n={n} < 10 — sample too small for any honest grade; downgrading by one letter")
        grade_letter = {"A": "B", "B": "C", "C": "D", "D": "D"}[grade_letter]

    return Scorecard(
        trader_label=trader_label,
        n_trades=n,
        win_rate_pct=win_rate,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        win_loss_ratio=win_loss_ratio,
        profit_factor=profit_factor,
        mean_pnl_pct=mean_pnl,
        median_pnl_pct=median_pnl,
        stdev_pnl_pct=stdev_pnl,
        sharpe_per_trade=sharpe,
        sortino_per_trade=sortino,
        max_dd_pct=mdd,
        longest_loss_streak=long_loss_streak,
        catastrophic_rate_pct=catastrophic_rate,
        worst_trade_pct=worst,
        total_pnl_pct=total_pnl,
        days_active=days,
        annualized_pct=annualized,
        calmar=calmar,
        first_half_mean_pct=fh_mean,
        second_half_mean_pct=sh_mean,
        stability_ratio=stability,
        sharpe_deflated=sharpe_deflated,
        n_assumed_leaderboard_peers=n_leaderboard_peers,
        grade=grade_letter,
        grade_rationale=rationale,
    )


def render_scorecard(sc: Scorecard) -> str:
    out = []
    out.append("=" * 80)
    out.append(f"GECKO COPY-TRADE GRADER — {sc.trader_label}")
    out.append("=" * 80)
    out.append("")
    out.append(f"  GRADE: {sc.grade}")
    for r in sc.grade_rationale:
        out.append(f"    • {r}")
    out.append("")
    out.append(f"  Sample:                   n_trades={sc.n_trades}, days_active={sc.days_active:.1f}")
    out.append(f"  Edge:                     mean={sc.mean_pnl_pct:+.2f}%/trade · median={sc.median_pnl_pct:+.2f}% · stdev={sc.stdev_pnl_pct:.2f}%")
    out.append(f"  Sharpe (per-trade):       {sc.sharpe_per_trade:+.2f}  (deflated for leaderboard peers={sc.n_assumed_leaderboard_peers}: {sc.sharpe_deflated:+.2f})")
    out.append(f"  Sortino:                  {sc.sortino_per_trade:+.2f}")
    out.append(f"  Win rate:                 {sc.win_rate_pct:.0f}% (avg win {sc.avg_win_pct:+.2f}% · avg loss {sc.avg_loss_pct:+.2f}%)")
    out.append(f"  Win/loss ratio:           {sc.win_loss_ratio:.2f}x  ·  Profit factor: {sc.profit_factor:.2f}")
    out.append(f"  Max drawdown:             {sc.max_dd_pct:.1f}% (cum-PnL terms)")
    out.append(f"  Longest losing streak:    {sc.longest_loss_streak} trades")
    out.append(f"  Catastrophic-trade rate:  {sc.catastrophic_rate_pct:.0f}% (worst single trade {sc.worst_trade_pct:+.2f}%)")
    out.append(f"  Annualized return:        {sc.annualized_pct:+.1f}%/yr · Calmar: {sc.calmar:.2f}")
    out.append(f"  Stability (2nd/1st half): {sc.stability_ratio:+.2f}  (fh mean {sc.first_half_mean_pct:+.2f}%, sh mean {sc.second_half_mean_pct:+.2f}%)")
    return "\n".join(out)


# ── Demo from the OKX screenshots founder shared ────────────────────


def demo_from_screenshots() -> int:
    """Grade the two traders visible in the founder's screenshots."""
    # Trader from screenshot 2 (SUI + ONDO discretionary; 6 trades visible)
    trader_a_trades = [
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,9,21,15).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,10,18,12).timestamp()*1000),
              symbol="SUI/USDT", side="long", entry_px=1.0827, exit_px=1.3410,
              size_usd=73422.58, realized_pnl_usd=14052.88, realized_pnl_pct=23.70),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,8,21,46).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,9,9,19).timestamp()*1000),
              symbol="SUI/USDT", side="long", entry_px=1.0676, exit_px=1.0535,
              size_usd=24606.74, realized_pnl_usd=-365.15, realized_pnl_pct=-1.47),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,8,21,42).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,9,9,19).timestamp()*1000),
              symbol="SUI/USDT", side="long", entry_px=1.0592, exit_px=1.0535,
              size_usd=4883.37, realized_pnl_usd=-33.83, realized_pnl_pct=-0.69),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,8,21,41).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,9,9,19).timestamp()*1000),
              symbol="SUI/USDT", side="long", entry_px=1.0596, exit_px=1.0535,
              size_usd=17202.10, realized_pnl_usd=-124.74, realized_pnl_pct=-0.73),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,8,14,30).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,9,9,18).timestamp()*1000),
              symbol="ONDO/USDT", side="long", entry_px=0.4249, exit_px=0.4234,
              size_usd=46385.79, realized_pnl_usd=-238.07, realized_pnl_pct=-0.52),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,8,22,18).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,8,22,19).timestamp()*1000),
              symbol="ONDO/USDT", side="long", entry_px=0.4623, exit_px=0.4576,
              size_usd=31531.22, realized_pnl_usd=-371.49, realized_pnl_pct=-1.17),
    ]

    # Trader from screenshot 3 (OKB + ZEC + SUI mix; 7 trades visible)
    trader_b_trades = [
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,27,6,41).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,27,18,56).timestamp()*1000),
              symbol="OKB/USDT", side="long", entry_px=90.11, exit_px=86.33,
              size_usd=95347.61, realized_pnl_usd=-4317.57, realized_pnl_pct=-4.34),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,27,6,39).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,27,18,56).timestamp()*1000),
              symbol="OKB/USDT", side="long", entry_px=90.05, exit_px=88.16,
              size_usd=5465.05, realized_pnl_usd=-124.78, realized_pnl_pct=-2.24),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,27,0,32).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,27,5,29).timestamp()*1000),
              symbol="OKB/USDT", side="long", entry_px=88.60, exit_px=89.09,
              size_usd=98955.60, realized_pnl_usd=410.81, realized_pnl_pct=0.41),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,26,1,9).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,26,12,57).timestamp()*1000),
              symbol="OKB/USDT", side="long", entry_px=89.74, exit_px=92.73,
              size_usd=70271.65, realized_pnl_usd=2179.81, realized_pnl_pct=3.20),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,25,8,40).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,25,11,42).timestamp()*1000),
              symbol="ZEC/USDT", side="long", entry_px=669.81, exit_px=677.60,
              size_usd=92706.49, realized_pnl_usd=941.43, realized_pnl_pct=1.02),
        # SUI big winner (same as trader A's, suggesting both copy from a common signal source)
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,9,21,15).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,10,18,12).timestamp()*1000),
              symbol="SUI/USDT", side="long", entry_px=1.0827, exit_px=1.3410,
              size_usd=73422.58, realized_pnl_usd=14052.88, realized_pnl_pct=23.70),
        Trade(entry_ts_ms=int(__import__("datetime").datetime(2026,5,8,21,46).timestamp()*1000),
              exit_ts_ms=int(__import__("datetime").datetime(2026,5,9,9,19).timestamp()*1000),
              symbol="SUI/USDT", side="long", entry_px=1.0676, exit_px=1.0535,
              size_usd=24606.74, realized_pnl_usd=-365.15, realized_pnl_pct=-1.47),
    ]

    sc_a = grade(trader_a_trades, "Trader A (SUI+ONDO scalper, screenshot 2)", n_leaderboard_peers=200)
    sc_b = grade(trader_b_trades, "Trader B (OKB+ZEC+SUI mix, screenshot 3)", n_leaderboard_peers=200)

    print(render_scorecard(sc_a))
    print()
    print(render_scorecard(sc_b))

    out_dir = Path("analysis/data/copy_trade_grader")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "trader_a.json").write_text(json.dumps(asdict(sc_a), indent=2))
    (out_dir / "trader_b.json").write_text(json.dumps(asdict(sc_b), indent=2))
    print(f"\nSaved scorecards → {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(demo_from_screenshots())
