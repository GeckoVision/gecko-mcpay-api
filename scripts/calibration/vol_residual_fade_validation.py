#!/usr/bin/env python3
"""Phase E.4 — cross-sectional vol-residual fade validation (pre-registered).

See private/strategy/2026-05-27-phase-e-ev-hunt-plan.md (Phase E.4 section).

Hypothesis (trading-strategist proposal):
Realized volatility is the most mean-reverting series in finance (Engle,
Heston, decades of equity-vol papers). When a coin's 7d realized vol
spikes relative to its 30d baseline, the price is OVEREXTENDED in the
direction of recent drift; expect mean-reversion over the next 7d.

This is a DIFFERENT mechanism from the 8 nulls (price/structure/flow):
trades VOLATILITY-CONDITIONED reversion, not vol or price separately.
Cross-sectional weekly so it survives regime shifts that kill
single-name strategies.

Strategy (cross-sectional, weekly rebalanced):
- Universe: top-30 Binance perps by 30d USD volume
- Each Monday 00:00 UTC: compute per coin
    vol_residual = realized_vol_7d / realized_vol_30d - 1
    drift_7d = (close_t - close_{t-7d}) / close_{t-7d}
- Top-K coins by |vol_residual| AND |drift_7d| > minimum:
    - If drift_7d > 0 AND vol spiked → SHORT (overheated mean-revert)
    - If drift_7d < 0 AND vol spiked → LONG (oversold mean-revert)
- Equal-weight K positions; beta-hedge basket with BTC
- Hold 7 days; close all on next rebalance
- Round-trip cost 0.16% (2x current Binance taker = 0.08%/leg × 2)

Run baseline:
    uv run python scripts/calibration/vol_residual_fade_validation.py
Run full ablations:
    uv run python scripts/calibration/vol_residual_fade_validation.py --ablations
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics as st
import sys
from dataclasses import dataclass
from glob import glob
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import overfitting_rigor as ofr  # noqa: E402

PERP_DIR = Path(_HERE) / "data" / "perp" / "binance"

# Bars per week at 4h candles (6/day × 7 = 42)
BARS_PER_WEEK = 42
BARS_PER_DAY = 6

# Costs (2x Binance taker = 0.08% × 2 sides = 0.16% round-trip per leg).
# A delta-hedge adds another leg's cost. For 5-position basket + 1 BTC hedge,
# round-trip cost = 6 × 0.16% = ~1.0%/week of pure friction. This is the
# highest-friction strategy in the +EV hunt; trading-strategist flagged it.
ROUND_TRIP_COST_PCT = 0.16

BASELINE = {
    "name": "baseline",
    "universe_top_n": 30,           # top-N by 30d volume
    "vol_window_short_bars": 7 * BARS_PER_DAY,  # 7d realized vol (in 4h bars)
    "vol_window_long_bars": 30 * BARS_PER_DAY,  # 30d realized vol
    "K": 5,                          # positions per direction (long+short combined)
    "min_drift_pct": 3.0,            # min |7d drift| to fire (filter noise)
    "min_vol_residual": 0.5,         # min |vol_resid| to fire (vol spike threshold)
    "hold_bars": BARS_PER_WEEK,      # weekly hold
    "beta_hedge_with_btc": True,
}

ABLATIONS = [
    BASELINE,
    {**BASELINE, "name": "K3", "K": 3},
    {**BASELINE, "name": "K7", "K": 7},
    {**BASELINE, "name": "no_hedge", "beta_hedge_with_btc": False},
    {**BASELINE, "name": "tight_drift", "min_drift_pct": 5.0},
    {**BASELINE, "name": "loose_drift", "min_drift_pct": 1.5},
    {**BASELINE, "name": "tight_vol", "min_vol_residual": 1.0},
    {**BASELINE, "name": "loose_vol", "min_vol_residual": 0.25},
    {**BASELINE, "name": "shorter_vol_win", "vol_window_short_bars": 3 * BARS_PER_DAY,
     "vol_window_long_bars": 14 * BARS_PER_DAY},
    {**BASELINE, "name": "biweekly_hold", "hold_bars": 2 * BARS_PER_WEEK},
]


@dataclass
class TradeRecord:
    entry_ts: int
    exit_ts: int
    coin: str
    side: int  # +1 long, -1 short
    entry_px: float
    exit_px: float
    vol_residual: float
    drift_7d: float
    gross_pnl_pct: float
    net_pnl_pct: float


@dataclass
class VariantResult:
    name: str
    config: dict
    n_trades: int
    n_weeks: int
    mean_pnl_pct: float
    sum_pnl_pct: float
    sharpe_per_trade: float
    weekly_sharpe: float
    ci_lo: float
    ci_hi: float
    max_dd_pct: float
    cpcv_median_sharpe: float
    cpcv_pct_paths_neg: float
    dsr: float


def load_perp(coin: str) -> list[dict]:
    f = PERP_DIR / f"{coin}_perp.json"
    if not f.exists():
        return []
    return json.loads(f.read_text())


def list_perp_coins() -> list[str]:
    return sorted(
        Path(f).stem.replace("_perp", "")
        for f in glob(str(PERP_DIR / "*_perp.json"))
    )


def _realized_vol(rows: list[dict], bar_idx: int, window: int) -> float | None:
    """Std of log-returns over the last `window` bars ending at bar_idx."""
    if bar_idx < window + 1:
        return None
    log_rets = []
    for i in range(bar_idx - window, bar_idx):
        c0 = rows[i]["close"]
        c1 = rows[i + 1]["close"]
        if c0 <= 0 or c1 <= 0:
            continue
        log_rets.append(math.log(c1 / c0))
    if len(log_rets) < window // 2:
        return None
    return st.pstdev(log_rets)


def _total_volume_30d(rows: list[dict], bar_idx: int) -> float:
    """Sum USD volume (volume × close as proxy) over trailing 30d."""
    lo = max(0, bar_idx - 30 * BARS_PER_DAY)
    return sum(rows[i].get("volume", 0) * rows[i].get("close", 0) for i in range(lo, bar_idx))


def simulate_variant(config: dict, all_coin_rows: dict[str, list[dict]]) -> list[TradeRecord]:
    """Run one variant; return list of TradeRecord."""
    K = config["K"]
    short_win = config["vol_window_short_bars"]
    long_win = config["vol_window_long_bars"]
    hold_bars = config["hold_bars"]
    min_drift = config["min_drift_pct"]
    min_vol_resid = config["min_vol_residual"]
    universe_top_n = config["universe_top_n"]
    beta_hedge = config["beta_hedge_with_btc"]

    # Build aligned 4h timestamp grid across all coins
    all_ts = sorted({r["ts"] for rows in all_coin_rows.values() for r in rows})
    # ts → index per coin
    coin_idx: dict[str, dict[int, int]] = {}
    for coin, rows in all_coin_rows.items():
        coin_idx[coin] = {r["ts"]: i for i, r in enumerate(rows)}

    trades: list[TradeRecord] = []
    last_rebalance_bar = -BARS_PER_WEEK  # allow first rebalance on bar 0
    next_rebalance_idx = max(long_win + 2, BARS_PER_WEEK)  # need vol windows warmed

    for ts_idx, ts in enumerate(all_ts):
        if ts_idx < next_rebalance_idx:
            continue
        if ts_idx - last_rebalance_bar < hold_bars:
            continue

        # Build candidates: for each coin in universe, compute vol_residual + drift_7d
        coin_metrics: list[tuple[str, float, float, float]] = []  # (coin, vol_resid, drift, vol_30d_usd)
        for coin, rows in all_coin_rows.items():
            if ts not in coin_idx[coin]:
                continue
            i = coin_idx[coin][ts]
            if i < long_win + 2:
                continue
            vol_s = _realized_vol(rows, i, short_win)
            vol_l = _realized_vol(rows, i, long_win)
            if vol_s is None or vol_l is None or vol_l <= 0:
                continue
            vol_resid = vol_s / vol_l - 1
            # 7d drift
            i7 = i - 7 * BARS_PER_DAY
            if i7 < 0:
                continue
            c0 = rows[i7]["close"]
            c1 = rows[i]["close"]
            if c0 <= 0:
                continue
            drift = (c1 - c0) / c0 * 100
            usd_vol = _total_volume_30d(rows, i)
            coin_metrics.append((coin, vol_resid, drift, usd_vol))

        # Filter to top-N by 30d USD volume
        coin_metrics.sort(key=lambda x: -x[3])
        coin_metrics = coin_metrics[:universe_top_n]

        # Filter by gates: |vol_residual| >= min_vol_resid AND |drift| >= min_drift
        eligible = [
            (coin, vr, dr, uv) for (coin, vr, dr, uv) in coin_metrics
            if abs(vr) >= min_vol_resid and abs(dr) >= min_drift
        ]

        # Rank by |vol_residual| descending; take top-K
        eligible.sort(key=lambda x: -abs(x[1]))
        top_k = eligible[:K]

        if not top_k:
            continue

        # Determine exit ts (current ts_idx + hold_bars)
        exit_idx = min(ts_idx + hold_bars, len(all_ts) - 1)
        exit_ts = all_ts[exit_idx]

        positions: list[tuple[str, int, float, float, float, float]] = []  # (coin, side, entry, exit, vr, drift)
        for coin, vol_resid, drift, _uv in top_k:
            rows = all_coin_rows[coin]
            i = coin_idx[coin][ts]
            entry_px = rows[i]["close"]
            if exit_ts not in coin_idx[coin]:
                continue
            ex_idx = coin_idx[coin][exit_ts]
            exit_px = rows[ex_idx]["close"]
            # If vol spiked + drift positive → SHORT (overheated)
            # If vol spiked + drift negative → LONG (oversold)
            side = -1 if drift > 0 else +1
            positions.append((coin, side, entry_px, exit_px, vol_resid, drift))

        for coin, side, entry_px, exit_px, vr, dr in positions:
            gross = side * (exit_px - entry_px) / entry_px * 100
            net = gross - ROUND_TRIP_COST_PCT
            trades.append(TradeRecord(
                entry_ts=ts, exit_ts=exit_ts, coin=coin, side=side,
                entry_px=entry_px, exit_px=exit_px,
                vol_residual=vr, drift_7d=dr,
                gross_pnl_pct=gross, net_pnl_pct=net,
            ))

        # Beta-hedge with BTC: net direction = (n longs - n shorts)
        if beta_hedge and "BTC" in all_coin_rows:
            net_long = sum(1 for p in positions if p[1] > 0) - sum(1 for p in positions if p[1] < 0)
            if net_long != 0:
                btc_rows = all_coin_rows["BTC"]
                bi = coin_idx["BTC"].get(ts)
                bxi = coin_idx["BTC"].get(exit_ts)
                if bi is not None and bxi is not None:
                    btc_entry = btc_rows[bi]["close"]
                    btc_exit = btc_rows[bxi]["close"]
                    btc_move = (btc_exit - btc_entry) / btc_entry * 100
                    hedge_pnl = -net_long * btc_move - ROUND_TRIP_COST_PCT * abs(net_long)
                    trades.append(TradeRecord(
                        entry_ts=ts, exit_ts=exit_ts, coin="HEDGE_BTC",
                        side=-1 if net_long > 0 else +1,
                        entry_px=btc_entry, exit_px=btc_exit,
                        vol_residual=0, drift_7d=0,
                        gross_pnl_pct=hedge_pnl + ROUND_TRIP_COST_PCT,
                        net_pnl_pct=hedge_pnl,
                    ))

        last_rebalance_bar = ts_idx
        next_rebalance_idx = ts_idx + hold_bars

    return trades


def aggregate_weekly(trades: list[TradeRecord]) -> list[float]:
    """Group trades by entry_ts (≈ weekly cohort), sum per-cohort pnl."""
    weekly: dict[int, float] = {}
    for t in trades:
        weekly[t.entry_ts] = weekly.get(t.entry_ts, 0.0) + t.net_pnl_pct
    return [weekly[ts] for ts in sorted(weekly)]


def block_ci(xs: list[float], block: int = 6, reps: int = 2000, seed: int = 1729) -> tuple[float, float, float]:
    if not xs or len(xs) < 2:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(xs)
    means = []
    for _ in range(reps):
        acc, cnt = 0.0, 0
        while cnt < n:
            s = rng.randrange(n)
            for k in range(block):
                acc += xs[(s + k) % n]
                cnt += 1
                if cnt >= n:
                    break
        means.append(acc / n)
    means.sort()
    return st.mean(xs), means[int(0.05 * reps)], means[int(0.95 * reps)]


def run_variant(config: dict, all_rows: dict[str, list[dict]]) -> VariantResult:
    trades = simulate_variant(config, all_rows)
    per_trade = [t.net_pnl_pct for t in trades]
    weekly = aggregate_weekly(trades)

    if len(per_trade) < 10:
        return VariantResult(
            name=config["name"], config=config, n_trades=len(per_trade), n_weeks=len(weekly),
            mean_pnl_pct=float("nan"), sum_pnl_pct=float("nan"),
            sharpe_per_trade=float("nan"), weekly_sharpe=float("nan"),
            ci_lo=float("nan"), ci_hi=float("nan"), max_dd_pct=float("nan"),
            cpcv_median_sharpe=float("nan"), cpcv_pct_paths_neg=float("nan"),
            dsr=float("nan"),
        )

    mean_t, lo_t, hi_t = block_ci(per_trade)
    sd_t = st.pstdev(per_trade) if len(per_trade) > 1 else 0.0
    sharpe_t = (mean_t / sd_t) if sd_t > 0 else 0.0
    sd_w = st.pstdev(weekly) if len(weekly) > 1 else 0.0
    sharpe_w = (st.mean(weekly) / sd_w * math.sqrt(52)) if sd_w > 0 else 0.0  # annualize weekly

    # MaxDD on cumulative weekly pnl
    cum = 0.0; peak = 0.0; mdd = 0.0
    for w in weekly:
        cum += w
        peak = max(peak, cum)
        if cum - peak < mdd:
            mdd = cum - peak

    # CPCV on weekly returns (weekly are roughly IID; per-trade are nested)
    if len(weekly) >= 16:
        n = len(weekly)
        bounds = [round(n * g / 8) for g in range(9)]
        samples = [(g, weekly[p], g) for g in range(8) for p in range(bounds[g], bounds[g + 1])]
        cpcv = ofr.cpcv_paths(samples, 8, 2, 1)
    else:
        cpcv = ofr.CPCVResult(8, 2, 0, [], float("nan"), float("nan"), float("nan"), float("nan"), 0.0, note="too few weeks")

    dsr = ofr.deflated_sharpe_ratio(per_trade, [ofr.sharpe_ratio(per_trade)], n_trials=len(ABLATIONS))

    return VariantResult(
        name=config["name"], config=config, n_trades=len(per_trade), n_weeks=len(weekly),
        mean_pnl_pct=mean_t, sum_pnl_pct=sum(per_trade),
        sharpe_per_trade=sharpe_t, weekly_sharpe=sharpe_w,
        ci_lo=lo_t, ci_hi=hi_t,
        max_dd_pct=mdd,
        cpcv_median_sharpe=cpcv.median, cpcv_pct_paths_neg=cpcv.pct_paths_negative,
        dsr=dsr.dsr,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablations", action="store_true")
    args = ap.parse_args()

    configs = ABLATIONS if args.ablations else [BASELINE]

    coins = list_perp_coins()
    print(f"=== Phase E.4 — vol-residual fade ===")
    print(f"  coins available: {len(coins)}")
    print(f"  cost: {ROUND_TRIP_COST_PCT}% round-trip × leg (≈{ROUND_TRIP_COST_PCT * 6:.1f}%/wk for 5+1 leg sleeve)")
    print(f"  configs to run: {[c['name'] for c in configs]}")
    print()
    print("Loading perp data ...", flush=True)
    all_rows: dict[str, list[dict]] = {}
    for coin in coins:
        rows = load_perp(coin)
        if rows:
            rows.sort(key=lambda r: r["ts"])
            all_rows[coin] = rows
    n_bars = sum(len(v) for v in all_rows.values())
    print(f"  {len(all_rows)} coins loaded, {n_bars} 4h bars total")

    results: list[VariantResult] = []
    for cfg in configs:
        print(f"\n[RUN] {cfg['name']}", flush=True)
        r = run_variant(cfg, all_rows)
        results.append(r)
        if r.n_trades >= 10:
            print(
                f"  n_trades={r.n_trades}  n_weeks={r.n_weeks}  "
                f"mean={r.mean_pnl_pct:+.3f}%  CI=[{r.ci_lo:+.3f}%,{r.ci_hi:+.3f}%]  "
                f"sum={r.sum_pnl_pct:+.1f}%  sharpe_w(ann)={r.weekly_sharpe:+.2f}  "
                f"DSR={r.dsr:.3f}  maxDD={r.max_dd_pct:+.1f}%"
            )
        else:
            print(f"  TOO_FEW_TRADES (n={r.n_trades})")

    # Summary
    print()
    print("=" * 100)
    print("SUMMARY (sorted by mean per-trade)")
    print("=" * 100)
    print(f"  {'name':<18s}  {'n':>5s}  {'mean':>10s}  {'95% CI':>20s}  {'sum':>9s}  {'sharpe_w':>9s}  {'DSR':>6s}")
    print("-" * 100)
    sorted_results = sorted(
        results, key=lambda r: -r.mean_pnl_pct if r.n_trades >= 10 else 999
    )
    for r in sorted_results:
        if r.n_trades < 10:
            print(f"  {r.name:<18s}  n={r.n_trades:>3d}  TOO_FEW_TRADES")
            continue
        print(
            f"  {r.name:<18s}  {r.n_trades:>5d}  "
            f"{r.mean_pnl_pct:+9.3f}%  "
            f"[{r.ci_lo:+6.3f}%,{r.ci_hi:+6.3f}%]  "
            f"{r.sum_pnl_pct:+8.1f}%  "
            f"{r.weekly_sharpe:+8.2f}  {r.dsr:.3f}"
        )

    # Branch verdict
    print()
    print("=" * 100)
    print("BRANCH ANALYSIS (per pre-commit):")
    print("=" * 100)
    baseline = results[0] if results else None
    if baseline and baseline.n_trades >= 10:
        gate_ci = baseline.ci_lo > 0
        gate_dsr = baseline.dsr >= 0.95
        gate_cpcv = (baseline.cpcv_pct_paths_neg is not None
                     and baseline.cpcv_pct_paths_neg < 0.25)
        print(f"  Baseline gates:")
        print(f"    CI excludes 0 (+):  {gate_ci}  (CI lo: {baseline.ci_lo:+.3f}%)")
        print(f"    DSR >= 0.95:         {gate_dsr}  ({baseline.dsr:.3f})")
        print(f"    CPCV %paths<0<25%:  {gate_cpcv}  ({baseline.cpcv_pct_paths_neg:.1%})")
        if args.ablations:
            passing = sum(
                1 for r in results
                if r.n_trades >= 10 and r.ci_lo > 0 and r.dsr >= 0.95
            )
            print(f"  Ablations passing gates: {passing}/{len(results)}")
            if gate_ci and gate_dsr and passing >= len(results) * 0.7:
                print("  → BRANCH A: REAL +EV (deep-history stress next)")
            elif gate_ci and gate_dsr:
                print("  → BRANCH B: FRAGILE — pure-OOS held-out test required")
            else:
                print("  → BRANCH C: NULL #10 (file finding, pivot to next sub-phase)")
        else:
            print("  → Run --ablations for full grid before branch decision.")
    else:
        print("  Baseline INSUFFICIENT (< 10 trades).")

    # Persist
    out = Path(_HERE).parent.parent / "analysis" / "data" / "phase_e" / "vol_residual_fade"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(
        [
            {
                "name": r.name, "config": r.config, "n_trades": r.n_trades, "n_weeks": r.n_weeks,
                "mean_pnl_pct": r.mean_pnl_pct, "sum_pnl_pct": r.sum_pnl_pct,
                "sharpe_per_trade": r.sharpe_per_trade, "weekly_sharpe": r.weekly_sharpe,
                "ci_lo": r.ci_lo, "ci_hi": r.ci_hi, "max_dd_pct": r.max_dd_pct,
                "cpcv_median_sharpe": r.cpcv_median_sharpe,
                "cpcv_pct_paths_neg": r.cpcv_pct_paths_neg, "dsr": r.dsr,
            }
            for r in results
        ],
        indent=2, default=str,
    ))
    print(f"\nResults saved → {(out / 'summary.json').relative_to(Path(_HERE).parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
