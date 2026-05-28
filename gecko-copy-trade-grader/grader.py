"""gecko-copy-trade-grader — pure grading library.

Self-contained: no dependencies beyond stdlib. Two surfaces:

  1. grade_trades()                  — accepts per-trade JSON, returns Scorecard
  2. grade_okx_trader_from_payload() — accepts an OKX smartmoney trader payload
                                       (with `rates` series), returns dict

Both run the same rigor stack: Sharpe + Sortino + Calmar + true max-DD +
catastrophic-rate + stability ratio + Bailey-LdP-style deflated Sharpe.

Empirically validated 2026-05-28 on live OKX top-50 leaderboard:
  - 17/50 (34%) graded D
  - 6/27 cross-period-multi-period traders are stable A/B
  - Most-overrated picks include catastrophic-rate 65% and degrading stability -12.56
"""
from __future__ import annotations

import math
import statistics as st
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


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

    @classmethod
    def from_dict(cls, d: dict) -> "Trade":
        return cls(
            entry_ts_ms=int(d["entry_ts_ms"]),
            exit_ts_ms=int(d["exit_ts_ms"]),
            symbol=d.get("symbol", "?"),
            side=d.get("side", "long"),
            entry_px=float(d["entry_px"]),
            exit_px=float(d["exit_px"]),
            size_usd=float(d.get("size_usd", 0)),
            realized_pnl_usd=float(d.get("realized_pnl_usd", 0)),
            realized_pnl_pct=float(d["realized_pnl_pct"]),
        )


@dataclass
class Scorecard:
    trader_label: str
    n_trades: int

    # Basic
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    win_loss_ratio: float
    profit_factor: float

    # Edge
    mean_pnl_pct: float
    median_pnl_pct: float
    stdev_pnl_pct: float
    sharpe_per_trade: float
    sortino_per_trade: float

    # Risk
    max_dd_pct: float
    longest_loss_streak: int
    catastrophic_rate_pct: float
    worst_trade_pct: float

    # Time/return
    total_pnl_pct: float
    days_active: float
    annualized_pct: float
    calmar: float

    # Stability
    first_half_mean_pct: float
    second_half_mean_pct: float
    stability_ratio: float

    # Selection bias
    sharpe_deflated: float
    n_assumed_leaderboard_peers: int

    # Verdict
    grade: str
    grade_rationale: list[str] = field(default_factory=list)


# ── Metrics ─────────────────────────────────────────────────────────


def _max_drawdown(cumulative_pnl_pct: list[float]) -> float:
    if not cumulative_pnl_pct:
        return 0.0
    peak = cumulative_pnl_pct[0]
    max_dd = 0.0
    for v in cumulative_pnl_pct:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    return max_dd


def _longest_neg_streak(pnls: list[float]) -> int:
    cur = best = 0
    for v in pnls:
        if v < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


# ── Trade-list grader ──────────────────────────────────────────────


def grade_trades(raw: list[dict], trader_label: str = "trader", n_peers: int = 100) -> Scorecard:
    trades = [Trade.from_dict(d) for d in raw]
    n = len(trades)
    if n == 0:
        raise ValueError("no trades")

    trades.sort(key=lambda t: t.entry_ts_ms)
    pnls = [t.realized_pnl_pct for t in trades]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = 100 * len(wins) / n
    avg_win = st.mean(wins) if wins else 0.0
    avg_loss = st.mean(losses) if losses else 0.0
    wl_ratio = avg_win / abs(avg_loss) if avg_loss < 0 else (float("inf") if wins else 0.0)
    sw = sum(wins) if wins else 0.0
    sl = abs(sum(losses)) if losses else 0.0
    pf = sw / sl if sl > 0 else (float("inf") if wins else 0.0)

    mean_p = st.mean(pnls)
    median_p = st.median(pnls)
    stdev_p = st.pstdev(pnls) if n > 1 else 0.0
    sharpe = mean_p / stdev_p if stdev_p > 0 else 0.0
    down = [p for p in pnls if p < 0]
    down_std = st.pstdev(down) if len(down) > 1 else 0.0
    sortino = mean_p / down_std if down_std > 0 else 0.0

    cum = []
    running = 0.0
    for p in pnls:
        running += p
        cum.append(running)
    mdd = _max_drawdown(cum)
    streak = _longest_neg_streak(pnls)

    cat = sum(1 for p in pnls if p <= -3.0)
    cat_rate = 100 * cat / n
    worst = min(pnls)

    total = sum(pnls)
    ts_first = trades[0].entry_ts_ms
    ts_last = trades[-1].exit_ts_ms
    days = (ts_last - ts_first) / 86400_000 if ts_last > ts_first else 1
    annualized = total * (365 / max(days, 1))
    calmar = annualized / mdd if mdd > 0 else 0.0

    mid = n // 2
    fh = pnls[:mid] if mid > 0 else pnls
    sh = pnls[mid:] if mid > 0 else []
    fh_mean = st.mean(fh) if fh else 0.0
    sh_mean = st.mean(sh) if sh else 0.0
    stability = sh_mean / fh_mean if fh_mean > 0 else (1.0 if sh_mean >= 0 else -1.0)

    deflation = math.sqrt(2 * math.log(max(n_peers, 2))) * (1.0 / math.sqrt(max(n, 1)))
    sharpe_def = sharpe - deflation

    rationale: list[str] = []
    A = [
        ("Sharpe ≥ 1.5", sharpe >= 1.5),
        ("profit_factor ≥ 2.0", pf >= 2.0),
        ("max_dd ≤ 15%", mdd <= 15),
        ("catastrophic_rate ≤ 10%", cat_rate <= 10),
        ("stability_ratio ≥ 0.5", stability >= 0.5),
        ("n_trades ≥ 30", n >= 30),
    ]
    B = [
        ("Sharpe ≥ 1.0", sharpe >= 1.0),
        ("profit_factor ≥ 1.5", pf >= 1.5),
        ("max_dd ≤ 25%", mdd <= 25),
        ("stability_ratio ≥ 0.2", stability >= 0.2),
    ]
    D_any = [
        ("Sharpe < 0.5", sharpe < 0.5),
        ("catastrophic_rate > 25%", cat_rate > 25),
        ("stability_ratio < 0", stability < 0),
        ("profit_factor < 1.0", pf < 1.0),
    ]

    if all(ok for _, ok in A):
        g = "A"; rationale.append("All A-gates passed")
    elif all(ok for _, ok in B):
        g = "B"; rationale.append("All B-gates passed")
        for d, ok in A:
            if not ok: rationale.append(f"miss A: {d}")
    elif any(ok for _, ok in D_any):
        g = "D"; rationale.append("Triggered D-gate")
        for d, ok in D_any:
            if ok: rationale.append(f"  → {d}")
    else:
        g = "C"; rationale.append("Between B and D — lucky/noisy/small-sample")

    if n < 10:
        rationale.append(f"NOTE: n={n} < 10 — downgrading by one letter")
        g = {"A": "B", "B": "C", "C": "D", "D": "D"}[g]

    return Scorecard(
        trader_label=trader_label, n_trades=n,
        win_rate_pct=win_rate, avg_win_pct=avg_win, avg_loss_pct=avg_loss,
        win_loss_ratio=wl_ratio, profit_factor=pf,
        mean_pnl_pct=mean_p, median_pnl_pct=median_p, stdev_pnl_pct=stdev_p,
        sharpe_per_trade=sharpe, sortino_per_trade=sortino,
        max_dd_pct=mdd, longest_loss_streak=streak,
        catastrophic_rate_pct=cat_rate, worst_trade_pct=worst,
        total_pnl_pct=total, days_active=days, annualized_pct=annualized, calmar=calmar,
        first_half_mean_pct=fh_mean, second_half_mean_pct=sh_mean, stability_ratio=stability,
        sharpe_deflated=sharpe_def, n_assumed_leaderboard_peers=n_peers,
        grade=g, grade_rationale=rationale,
    )


def render_scorecard(sc: Scorecard) -> str:
    out = []
    out.append("=" * 80)
    out.append(f"GECKO COPY-TRADE GRADER — {sc.trader_label}")
    out.append("=" * 80)
    out.append(f"\n  GRADE: {sc.grade}")
    for r in sc.grade_rationale:
        out.append(f"    • {r}")
    out.append(f"\n  Sample:                   n_trades={sc.n_trades}, days_active={sc.days_active:.1f}")
    out.append(f"  Edge:                     mean={sc.mean_pnl_pct:+.2f}%/trade · median={sc.median_pnl_pct:+.2f}% · stdev={sc.stdev_pnl_pct:.2f}%")
    out.append(f"  Sharpe (per-trade):       {sc.sharpe_per_trade:+.2f}  (deflated for n_peers={sc.n_assumed_leaderboard_peers}: {sc.sharpe_deflated:+.2f})")
    out.append(f"  Sortino:                  {sc.sortino_per_trade:+.2f}")
    out.append(f"  Win rate:                 {sc.win_rate_pct:.0f}% (avg win {sc.avg_win_pct:+.2f}% · avg loss {sc.avg_loss_pct:+.2f}%)")
    out.append(f"  Win/loss ratio:           {sc.win_loss_ratio:.2f}x  ·  Profit factor: {sc.profit_factor:.2f}")
    out.append(f"  Max drawdown:             {sc.max_dd_pct:.1f}% (cum-PnL terms)")
    out.append(f"  Longest losing streak:    {sc.longest_loss_streak} trades")
    out.append(f"  Catastrophic-trade rate:  {sc.catastrophic_rate_pct:.0f}% (worst single trade {sc.worst_trade_pct:+.2f}%)")
    out.append(f"  Annualized return:        {sc.annualized_pct:+.1f}%/yr · Calmar: {sc.calmar:.2f}")
    out.append(f"  Stability (2nd/1st half): {sc.stability_ratio:+.2f}  (fh mean {sc.first_half_mean_pct:+.2f}%, sh mean {sc.second_half_mean_pct:+.2f}%)")
    return "\n".join(out)


# ── OKX-specific grader (consumes daily-PnL series) ─────────────────


def _daily_returns_from_cumulative(rates: list[dict]) -> list[float]:
    vs = [float(r["value"]) for r in rates]
    deltas = [vs[0]]
    for i in range(1, len(vs)):
        deltas.append(vs[i] - vs[i - 1])
    return deltas


def grade_okx_trader_from_payload(trader: dict, n_peers: int = 50) -> dict:
    """Grade an OKX trader from the smartmoney_get_traders_by_filter payload."""
    nickname = trader.get("nickName", "?")
    author_id = trader.get("authorId", "?")
    aum = float(trader.get("asset", 0))
    okx_pnl = float(trader.get("pnl", 0))
    okx_pnl_ratio = float(trader.get("pnlRatio", 0))
    okx_win_rate = float(trader.get("winRate", 0))
    okx_max_dd = float(trader.get("maxDrawdown", 0))
    rates = trader.get("rates", [])

    if not rates or aum <= 0:
        return {"nickname": nickname, "authorId": author_id, "grade": "?",
                "reason": "no rates or no AUM"}

    daily_pnls = _daily_returns_from_cumulative(rates)
    daily_ret_pct = [d / aum * 100 for d in daily_pnls]
    n = len(daily_ret_pct)
    if n < 5:
        return {"nickname": nickname, "authorId": author_id, "grade": "?",
                "reason": "<5 days of data"}

    mean_d = st.mean(daily_ret_pct)
    stdev_d = st.pstdev(daily_ret_pct) if n > 1 else 0.0
    sharpe_d = mean_d / stdev_d if stdev_d > 0 else 0.0
    sharpe_annualized = sharpe_d * math.sqrt(365)
    down = [r for r in daily_ret_pct if r < 0]
    down_std = st.pstdev(down) if len(down) > 1 else 0.0
    sortino = (mean_d / down_std * math.sqrt(365)) if down_std > 0 else 0.0

    cum_pct = [float(r["value"]) / aum * 100 for r in rates]
    peak = cum_pct[0]
    mdd_pct = 0.0
    for v in cum_pct:
        peak = max(peak, v)
        mdd_pct = max(mdd_pct, peak - v)

    cat = sum(1 for r in daily_ret_pct if r <= -3.0)
    cat_rate = 100 * cat / n

    mid = n // 2
    fh = st.mean(daily_ret_pct[:mid]) if mid > 0 else 0.0
    sh = st.mean(daily_ret_pct[mid:]) if mid > 0 else 0.0
    stability = sh / fh if abs(fh) > 0.01 else (1.0 if sh >= 0 else -1.0)

    deflation = math.sqrt(2 * math.log(max(n_peers, 2))) / math.sqrt(n)
    sharpe_def = sharpe_annualized - deflation

    annualized_ret = mean_d * 365
    calmar = annualized_ret / mdd_pct if mdd_pct > 0 else 0.0

    rationale = []
    if sharpe_annualized >= 3.0 and mdd_pct <= 15 and cat_rate <= 5 and stability >= 0.3:
        g = "A"; rationale.append("Sharpe ≥ 3 + low DD + low cat + stable")
    elif sharpe_annualized >= 1.5 and mdd_pct <= 30 and stability >= 0.0:
        g = "B"; rationale.append("Sharpe ≥ 1.5; promising")
        if sharpe_annualized < 3: rationale.append(f"  miss A: sharpe {sharpe_annualized:.2f}")
        if mdd_pct > 15: rationale.append(f"  miss A: MDD {mdd_pct:.1f}% > 15")
        if cat_rate > 5: rationale.append(f"  miss A: cat-rate {cat_rate:.0f}% > 5")
    elif sharpe_annualized >= 0.5:
        g = "C"; rationale.append("Marginal — lucky/small-sample")
    else:
        g = "D"; rationale.append(f"Sharpe {sharpe_annualized:.2f} < 0.5 = gambling")

    if cat_rate > 15:
        g = "D"; rationale.append(f"  override → D: cat-rate {cat_rate:.0f}% > 15")
    if mdd_pct > 40:
        rationale.append(f"  → max DD {mdd_pct:.1f}% — drawdown risk severe")
    if stability < -0.3:
        rationale.append(f"  → DEGRADING: stability {stability:+.2f}")

    return {
        "nickname": nickname, "authorId": author_id, "aum": aum,
        "okx_pnl": okx_pnl, "okx_pnl_ratio": okx_pnl_ratio,
        "okx_win_rate": okx_win_rate, "okx_max_dd": okx_max_dd,
        "days": n,
        "mean_daily_ret_pct": mean_d, "stdev_daily_ret_pct": stdev_d,
        "sharpe_daily": sharpe_d, "sharpe_annualized": sharpe_annualized,
        "sharpe_deflated": sharpe_def, "sortino_annualized": sortino,
        "true_max_dd_pct": mdd_pct, "calmar": calmar,
        "catastrophic_rate_pct": cat_rate,
        "first_half_mean": fh, "second_half_mean": sh, "stability_ratio": stability,
        "grade": g, "rationale": rationale,
    }


def render_okx_scorecard(results: list[dict], okx_sort_key: str = "okx_pnl_ratio") -> str:
    """Render the Gecko-Rank vs OKX-Rank delta table."""
    by_okx = sorted([r for r in results if "okx_pnl_ratio" in r],
                    key=lambda r: -r.get(okx_sort_key, -999))
    by_gecko = sorted([r for r in results if "sharpe_deflated" in r],
                      key=lambda r: -r.get("sharpe_deflated", -999))
    gecko_rank_by_id = {r["authorId"]: gi + 1 for gi, r in enumerate(by_gecko)}

    lines = []
    lines.append(f"{'OKX#':>4s} {'Gecko#':>6s} {'Δrank':>6s} | {'name':<22s} "
                 f"{'AUM$':>10s} {'OKX_PnL%':>8s} {'TrueDD':>7s} {'Sharpe':>7s} "
                 f"{'Defl_Sh':>8s} {'CatRate':>7s} {'Stable':>7s} {'Grade':>6s}")
    lines.append("-" * 130)
    for i, r in enumerate(by_okx, 1):
        if "authorId" not in r:
            continue
        gr = gecko_rank_by_id.get(r["authorId"], 0)
        delta = i - gr
        delta_s = f"{delta:+d}" if delta != 0 else "0"
        lines.append(f"{i:>4d} {gr:>6d} {delta_s:>6s} | "
                     f"{r['nickname'][:21]:<22s} "
                     f"${r.get('aum', 0) / 1000:>8.0f}K "
                     f"{r.get('okx_pnl_ratio', 0) * 100:>+7.1f}% "
                     f"{-r.get('true_max_dd_pct', 0):>+6.1f}% "
                     f"{r.get('sharpe_annualized', 0):>+6.2f} "
                     f"{r.get('sharpe_deflated', 0):>+7.2f} "
                     f"{r.get('catastrophic_rate_pct', 0):>6.0f}% "
                     f"{r.get('stability_ratio', 0):>+6.2f} "
                     f"{r.get('grade', '?'):>6s}")
    grades = Counter(r.get("grade", "?") for r in results)
    lines.append(f"\nGrade distribution: {dict(grades)}")
    return "\n".join(lines)


def cross_period_stability(graded_by_period: dict[str, list[dict]]) -> str:
    """Compare grades for the same trader across periods (e.g. 30d vs 90d)."""
    periods = list(graded_by_period.keys())
    by_id_by_period: dict[str, dict[str, dict]] = {}
    for period, results in graded_by_period.items():
        for r in results:
            aid = r.get("authorId")
            if aid:
                by_id_by_period.setdefault(aid, {})[period] = r

    multi = [aid for aid, by_p in by_id_by_period.items() if len(by_p) >= 2]
    grade_rank = {"A": 4, "B": 3, "C": 2, "D": 1, "?": 0}

    lines = [f"Traders in ≥2 periods: {len(multi)} of {len(by_id_by_period)} total\n"]
    lines.append(f"{'nickname':<22s} | " + " | ".join(f"{p:>8s}" for p in periods) + " | tag")
    lines.append("-" * (24 + 11 * len(periods) + 12))
    stable_hi = stable_lo = flip = 0
    for aid in multi:
        rec = by_id_by_period[aid]
        nickname = next(iter(rec.values())).get("nickname", "?")
        grades = {p: rec[p].get("grade", "?") for p in periods if p in rec}
        grade_set = set(grades.values())
        ranks = {grade_rank.get(g, 0) for g in grade_set}
        if max(ranks) - min(ranks) >= 2:
            flip += 1; tag = "FLIP"
        elif all(grade_rank.get(g, 0) >= 3 for g in grade_set):
            stable_hi += 1; tag = "stable A/B"
        elif all(grade_rank.get(g, 0) <= 2 for g in grade_set):
            stable_lo += 1; tag = "stable C/D"
        else:
            tag = "adjacent"
        cells = [f"{grades.get(p, '—'):>8s}" for p in periods]
        lines.append(f"{nickname[:21]:<22s} | " + " | ".join(cells) + f" | {tag}")

    n = len(multi)
    lines.append(f"\nSummary: STABLE-A/B {stable_hi} | STABLE-C/D {stable_lo} | FLIP {flip} (of {n})")
    if n > 0:
        pct_stable = 100 * (stable_hi + stable_lo) / n
        lines.append(f"Cross-period stability: {pct_stable:.0f}% of multi-period traders are stably classified")
    return "\n".join(lines)
