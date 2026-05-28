#!/usr/bin/env python3
"""Sprint 12 #2 — grade OKX top-50 leaderboard, publish Gecko-Rank vs OKX-Rank delta.

Pulls real leaderboard via `mcp__okx-agent-trade-kit__smartmoney_get_traders_by_filter`,
then for each trader:
  - Reconstructs daily-return series from the 31-point cumulative PnL trajectory
  - Computes: Sharpe, Sortino, max-DD (true peak-to-trough), Calmar, stability,
    catastrophic-rate, deflated-Sharpe (n_peers=50 leaderboard slots)
  - Outputs Gecko-grade A/B/C/D

Then ranks traders BY Gecko criteria vs OKX criteria; surfaces the delta —
the headline being "OKX-rank-#3 actually grades C; rigor-rank-#11 grades A".

Input JSON is the verbatim output of smartmoney_get_traders_by_filter saved
to analysis/data/okx_leaderboard/raw_<period>.json.
"""
from __future__ import annotations

import json
import math
import statistics as st
from dataclasses import asdict
from pathlib import Path

# Import grader from sibling module
import sys
sys.path.insert(0, "scripts/calibration")
from copy_trade_grader import Scorecard, max_drawdown


DATA_DIR = Path("analysis/data/okx_leaderboard")


def daily_returns_from_cumulative(rates: list[dict]) -> list[float]:
    """rates is list of {statTime, value} where value is cumulative $-PnL on that day.

    Convert to per-day $ change. Note: these are cumulative against the trader's
    starting capital, so day-0 value IS the day-1 PnL.
    """
    vs = [float(r["value"]) for r in rates]
    deltas = [vs[0]]
    for i in range(1, len(vs)):
        deltas.append(vs[i] - vs[i - 1])
    return deltas


def grade_okx_trader(trader: dict, n_peers: int = 50) -> dict:
    """Grade one OKX trader from the leaderboard payload."""
    nickname = trader.get("nickName", "?")
    author_id = trader.get("authorId", "?")
    aum = float(trader.get("asset", 0))
    okx_pnl = float(trader.get("pnl", 0))
    okx_pnl_ratio = float(trader.get("pnlRatio", 0))
    okx_win_rate = float(trader.get("winRate", 0))
    okx_max_dd = float(trader.get("maxDrawdown", 0))
    rates = trader.get("rates", [])

    if not rates:
        return {"nickname": nickname, "grade": "?", "reason": "no rate data"}

    # Daily $-PnL deltas
    daily_pnls = daily_returns_from_cumulative(rates)
    # Convert to per-day return on AUM (denominator)
    if aum <= 0:
        return {"nickname": nickname, "grade": "?", "reason": "no AUM"}
    daily_ret_pct = [d / aum * 100 for d in daily_pnls]

    n = len(daily_ret_pct)
    if n < 5:
        return {"nickname": nickname, "grade": "?", "reason": "too few days"}

    # Stats
    mean_d = st.mean(daily_ret_pct)
    stdev_d = st.pstdev(daily_ret_pct) if n > 1 else 0.0
    sharpe_daily = mean_d / stdev_d if stdev_d > 0 else 0.0
    sharpe_annualized = sharpe_daily * math.sqrt(365)
    downside = [r for r in daily_ret_pct if r < 0]
    downside_std = st.pstdev(downside) if len(downside) > 1 else 0.0
    sortino = (mean_d / downside_std * math.sqrt(365)) if downside_std > 0 else 0.0

    # True max drawdown from the cumulative series
    cum_vs_aum = [float(r["value"]) / aum * 100 for r in rates]
    # MDD as: peak − trough on the cumulative-%-of-AUM series
    peak = cum_vs_aum[0]
    mdd_pct = 0.0
    for v in cum_vs_aum:
        peak = max(peak, v)
        dd = peak - v
        mdd_pct = max(mdd_pct, dd)

    # Catastrophic day rate: % days worse than -3% of AUM
    catastrophic = sum(1 for r in daily_ret_pct if r <= -3.0)
    catastrophic_rate = 100 * catastrophic / n

    # Stability: split halves
    mid = n // 2
    fh_mean = st.mean(daily_ret_pct[:mid]) if mid > 0 else 0.0
    sh_mean = st.mean(daily_ret_pct[mid:]) if mid > 0 else 0.0
    stability = sh_mean / fh_mean if abs(fh_mean) > 0.01 else (1.0 if sh_mean >= 0 else -1.0)

    # Deflated sharpe (Bailey-LdP approximation, simple form):
    # sharpe_deflated ≈ sharpe - sqrt(2 * log(n_peers)) / sqrt(n)
    deflation_factor = math.sqrt(2 * math.log(max(n_peers, 2))) / math.sqrt(n)
    sharpe_deflated = sharpe_annualized - deflation_factor

    # Calmar = annualized return / max DD
    annualized_ret = mean_d * 365
    calmar = annualized_ret / mdd_pct if mdd_pct > 0 else 0.0

    # Grade
    rationale = []
    if sharpe_annualized >= 3.0 and mdd_pct <= 15 and catastrophic_rate <= 5 and stability >= 0.3:
        grade_letter = "A"
        rationale.append("Sharpe >= 3 + low DD + low catastrophic + stable")
    elif sharpe_annualized >= 1.5 and mdd_pct <= 30 and stability >= 0.0:
        grade_letter = "B"
        rationale.append("Sharpe >= 1.5; promising but watch downside")
        if sharpe_annualized < 3: rationale.append(f"  miss A: sharpe {sharpe_annualized:.2f} < 3")
        if mdd_pct > 15: rationale.append(f"  miss A: MDD {mdd_pct:.1f}% > 15")
        if catastrophic_rate > 5: rationale.append(f"  miss A: cat-rate {catastrophic_rate:.0f}% > 5")
    elif sharpe_annualized >= 0.5:
        grade_letter = "C"
        rationale.append("Marginal Sharpe; likely lucky / small-sample")
    else:
        grade_letter = "D"
        rationale.append(f"Sharpe {sharpe_annualized:.2f} < 0.5 = gambling")

    # Add penalties
    if catastrophic_rate > 15:
        grade_letter = "D"
        rationale.append(f"  override → D: catastrophic_rate {catastrophic_rate:.0f}% > 15")
    if mdd_pct > 40:
        rationale.append(f"  → caution: max DD {mdd_pct:.1f}% historically; drawdown risk severe")
    if stability < -0.3:
        rationale.append(f"  → DEGRADING: 2H/1H stability {stability:+.2f}; was earning, now losing")

    return {
        "nickname": nickname,
        "authorId": author_id,
        "aum": aum,
        "okx_pnl": okx_pnl,
        "okx_pnl_ratio": okx_pnl_ratio,
        "okx_win_rate": okx_win_rate,
        "okx_max_dd": okx_max_dd,
        "days": n,
        "mean_daily_ret_pct": mean_d,
        "stdev_daily_ret_pct": stdev_d,
        "sharpe_daily": sharpe_daily,
        "sharpe_annualized": sharpe_annualized,
        "sharpe_deflated": sharpe_deflated,
        "sortino_annualized": sortino,
        "true_max_dd_pct": mdd_pct,
        "calmar": calmar,
        "catastrophic_rate_pct": catastrophic_rate,
        "first_half_mean": fh_mean,
        "second_half_mean": sh_mean,
        "stability_ratio": stability,
        "grade": grade_letter,
        "rationale": rationale,
    }


def main(input_path: str = None) -> int:
    if not input_path:
        input_path = str(DATA_DIR / "raw_30d.json")
    raw = json.loads(Path(input_path).read_text())
    traders = raw.get("data", []) if isinstance(raw, dict) else raw

    results = []
    for t in traders:
        try:
            r = grade_okx_trader(t)
            results.append(r)
        except Exception as e:
            results.append({"nickname": t.get("nickName", "?"), "grade": "?", "reason": f"err: {e}"})

    # Output ranked by Gecko criteria (deflated Sharpe DESC)
    by_gecko = sorted(results, key=lambda r: -r.get("sharpe_deflated", -999))
    by_okx = sorted(results, key=lambda r: -r.get("okx_pnl_ratio", -999))

    # Print main table
    print("=" * 160)
    print("OKX LEADERBOARD — Gecko Grader vs OKX's own ranking (30d, sortBy=pnlRatio)")
    print("=" * 160)
    print(f"{'OKX#':>4s} {'Gecko#':>6s} {'Δrank':>6s} | {'name':<22s} {'AUM$':>10s} {'OKX_PnL%':>8s} "
          f"{'OKX_DD':>7s} {'TrueDD':>7s} {'Sharpe':>7s} {'Defl_Sh':>8s} {'CatRate':>7s} "
          f"{'Stable':>7s} {'Grade':>6s}")
    print("-" * 160)
    gecko_rank_by_id = {r["authorId"]: gi + 1 for gi, r in enumerate(by_gecko)}
    for i, r in enumerate(by_okx, 1):
        if "authorId" not in r:
            continue
        gecko_rank = gecko_rank_by_id.get(r["authorId"], 0)
        delta = i - gecko_rank
        delta_str = f"{delta:+d}" if delta != 0 else "0"
        print(f"{i:>4d} {gecko_rank:>6d} {delta_str:>6s} | "
              f"{r['nickname'][:21]:<22s} "
              f"${r['aum']/1000:>8.0f}K {r['okx_pnl_ratio']*100:>+7.1f}% "
              f"{r['okx_max_dd']*100:>+6.1f}% {-r['true_max_dd_pct']:>+6.1f}% "
              f"{r['sharpe_annualized']:>+6.2f} {r['sharpe_deflated']:>+7.2f} "
              f"{r['catastrophic_rate_pct']:>6.0f}% {r['stability_ratio']:>+6.2f} "
              f"{r['grade']:>6s}")

    # Distribution by grade
    print()
    from collections import Counter
    grades = Counter(r["grade"] for r in results if "grade" in r)
    print(f"Grade distribution: {dict(grades)}")

    # Biggest rank deltas (most-overrated by OKX)
    print()
    print("=" * 80)
    print("MOST OVERRATED by OKX (Gecko rank MUCH lower than OKX rank)")
    print("=" * 80)
    deltas = []
    for okx_i, r in enumerate(by_okx, 1):
        if "authorId" not in r: continue
        gecko_i = gecko_rank_by_id.get(r["authorId"], 999)
        deltas.append((gecko_i - okx_i, r, okx_i, gecko_i))
    deltas.sort(key=lambda t: -t[0])  # most-overrated first
    for delta, r, okx_i, gecko_i in deltas[:5]:
        print(f"  OKX #{okx_i} → Gecko #{gecko_i} (Δ {delta:+d})  {r['nickname']:<22s}  Grade {r['grade']}")
        for line in r.get("rationale", [])[:3]:
            print(f"      {line}")

    print()
    print("=" * 80)
    print("MOST UNDERRATED by OKX (Gecko rank MUCH higher than OKX rank)")
    print("=" * 80)
    deltas.sort(key=lambda t: t[0])  # most-underrated first
    for delta, r, okx_i, gecko_i in deltas[:5]:
        if delta >= 0:
            break
        print(f"  OKX #{okx_i} → Gecko #{gecko_i} (Δ {delta:+d})  {r['nickname']:<22s}  Grade {r['grade']}")
        for line in r.get("rationale", [])[:3]:
            print(f"      {line}")

    # Save full results
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "graded.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nSaved → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
