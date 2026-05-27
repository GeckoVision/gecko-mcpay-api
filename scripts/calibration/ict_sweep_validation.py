#!/usr/bin/env python3
"""Phase E.5 — ICT swing-sweep reclaim + HTF EMA gate validation (pre-registered).

See private/strategy/2026-05-27-phase-e-ev-hunt-plan.md (E.5 section).

Hypothesis (data-scientist proposal):
The 2026-05-25 ICT null tested swing-sweeps WITHOUT HTF trend or volume
filters. Sweeps WITH trend agreement are continuation entries after a
liquidity grab; AGAINST trend are counter-trend traps. The HTF gate
materially shifts the prior. This re-attempts the ICT mechanism with
the missing structural filters.

Strategy:
- Universe: top-30 Binance perps by 30d USD volume
- F1: swing sweep + reclaim (close back inside after wicking beyond)
- F2: HTF EMA50/EMA200 trend agreement (daily); only fire WITH trend
- F3: volume quartile gate (sweep candle in top 25% of trailing 60-bar vol)
- Triple-barrier exit: +2R / -1R / 12-bar (48h) time stop
- One position per coin, sized equal-risk

Run baseline:
    uv run python scripts/calibration/ict_sweep_validation.py
Run ablations:
    uv run python scripts/calibration/ict_sweep_validation.py --ablations
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

BARS_PER_DAY = 6  # 4h candles
ROUND_TRIP_COST_PCT = 0.10  # 2x Binance taker (0.04 → 0.05/leg × 2)

BASELINE = {
    "name": "baseline",
    "universe_top_n": 30,
    "fractal_bars": 3,                  # n-bar fractal for swing detection
    "max_unmitigated_swings": 5,        # track last 5 swing extremes
    "vol_window_bars": 60,              # 10d on 4h candles
    "vol_quartile": 0.75,               # top quartile = q ≥ 0.75
    "ema_separation_pct": 2.0,          # require |EMA50-EMA200|/close ≥ 2%
    "stop_buffer_atr": 0.25,            # stop = swept extreme - 0.25*ATR
    "atr_window_bars": 14,
    "tp_r_multiple": 2.0,               # triple-barrier +2R
    "max_hold_bars": 12,                # 48h max hold
}

ABLATIONS = [
    BASELINE,
    {**BASELINE, "name": "no_htf_gate", "ema_separation_pct": 0.0},   # disable HTF gate
    {**BASELINE, "name": "no_vol_gate", "vol_quartile": 0.0},          # disable vol gate
    {**BASELINE, "name": "tight_vol", "vol_quartile": 0.90},
    {**BASELINE, "name": "loose_htf", "ema_separation_pct": 0.5},
    {**BASELINE, "name": "tight_htf", "ema_separation_pct": 3.0},
    {**BASELINE, "name": "fractal_5", "fractal_bars": 5},
    {**BASELINE, "name": "tp_1.5R", "tp_r_multiple": 1.5},
    {**BASELINE, "name": "tp_3R", "tp_r_multiple": 3.0},
    {**BASELINE, "name": "longer_hold", "max_hold_bars": 24},
]


@dataclass
class Trade:
    entry_ts: int
    entry_idx: int
    exit_ts: int
    exit_idx: int
    coin: str
    side: int  # +1 long, -1 short
    entry_px: float
    stop_px: float
    tp_px: float
    exit_px: float
    exit_reason: str
    gross_pnl_pct: float
    net_pnl_pct: float
    r_realized: float
    hold_bars: int


@dataclass
class VariantResult:
    name: str
    config: dict
    n_trades: int
    mean_pnl_pct: float
    sum_pnl_pct: float
    mean_r: float
    sharpe_t: float
    weekly_sharpe_ann: float
    ci_lo: float
    ci_hi: float
    max_dd_pct: float
    cpcv_median_sharpe: float
    cpcv_pct_paths_neg: float
    dsr: float
    by_exit_reason: dict


def load_perp(coin: str) -> list[dict]:
    f = PERP_DIR / f"{coin}_perp.json"
    if not f.exists():
        return []
    return json.loads(f.read_text())


def list_coins() -> list[str]:
    return sorted(
        Path(f).stem.replace("_perp", "")
        for f in glob(str(PERP_DIR / "*_perp.json"))
    )


def _atr(rows: list[dict], i: int, window: int) -> float | None:
    """ATR over the last `window` bars ending at bar i."""
    if i < window:
        return None
    trs = []
    for j in range(i - window, i):
        if j == 0:
            tr = rows[j]["high"] - rows[j]["low"]
        else:
            h, l, c_prev = rows[j]["high"], rows[j]["low"], rows[j - 1]["close"]
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    return sum(trs) / window if trs else None


def _ema(rows: list[dict], i: int, period: int, key: str = "close") -> float | None:
    """Simple EMA from start of available data through bar i."""
    if i < period:
        return None
    alpha = 2.0 / (period + 1)
    # Seed with SMA of first `period` bars
    series = [rows[k][key] for k in range(min(len(rows), i + 1))]
    if len(series) < period:
        return None
    ema = sum(series[:period]) / period
    for v in series[period:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def _detect_swings(rows: list[dict], end_idx: int, fractal: int, n_keep: int) -> tuple[list[float], list[float]]:
    """Find recent unmitigated swing highs / lows up to bar end_idx (confirmed by t+fractal).

    Returns (swing_highs_unmitigated, swing_lows_unmitigated). Most-recent first.
    """
    if end_idx < 2 * fractal:
        return [], []
    highs_found = []
    lows_found = []
    for i in range(fractal, end_idx - fractal + 1):
        is_swing_high = all(rows[i]["high"] >= rows[i + d]["high"] for d in range(-fractal, fractal + 1) if d != 0)
        is_swing_low = all(rows[i]["low"] <= rows[i + d]["low"] for d in range(-fractal, fractal + 1) if d != 0)
        if is_swing_high:
            highs_found.append(rows[i]["high"])
        if is_swing_low:
            lows_found.append(rows[i]["low"])
    # Unmitigated = not yet swept. Approx: keep swings ABOVE the current price for highs (haven't been swept)
    # and BELOW for lows.
    cur_high = rows[end_idx]["high"]
    cur_low = rows[end_idx]["low"]
    unmit_highs = sorted([h for h in highs_found if h > cur_high], reverse=True)[:n_keep]
    unmit_lows = sorted([l for l in lows_found if l < cur_low])[:n_keep]
    return unmit_highs, unmit_lows


def _htf_trend(daily_closes: list[float], daily_idx: int, ema_sep_pct: float) -> int:
    """Return +1 trend-up / -1 trend-down / 0 mixed-or-disabled.

    daily_closes: list of daily-resampled closes
    daily_idx: index into daily_closes for current day
    ema_sep_pct: minimum |EMA50 - EMA200|/close × 100 to trust the trend
    """
    if daily_idx < 200:
        return 0
    alpha50 = 2 / 51
    alpha200 = 2 / 201
    ema50 = sum(daily_closes[:50]) / 50
    ema200 = sum(daily_closes[:200]) / 200
    for v in daily_closes[50:daily_idx + 1]:
        ema50 = alpha50 * v + (1 - alpha50) * ema50
    for v in daily_closes[200:daily_idx + 1]:
        ema200 = alpha200 * v + (1 - alpha200) * ema200
    cur = daily_closes[daily_idx]
    if cur <= 0:
        return 0
    sep = abs(ema50 - ema200) / cur * 100
    if ema_sep_pct > 0 and sep < ema_sep_pct:
        return 0
    if ema50 > ema200 and cur > ema50:
        return +1
    if ema50 < ema200 and cur < ema50:
        return -1
    return 0


def _resample_daily(rows: list[dict]) -> list[float]:
    """Group 4h bars into daily closes (UTC day, ts = midnight)."""
    day_groups: dict[int, list[float]] = {}
    for r in rows:
        ts = int(r["ts"])
        day_ts = ts - (ts % (24 * 3600 * 1000))
        day_groups.setdefault(day_ts, []).append(r["close"])
    return [day_groups[d][-1] for d in sorted(day_groups)]


def _vol_quartile(rows: list[dict], i: int, window: int, q: float) -> bool:
    """Return True if rows[i].volume is in top q-quartile of the trailing window."""
    if q <= 0:
        return True  # gate disabled
    if i < window:
        return False
    vols = sorted([rows[k].get("volume", 0) for k in range(i - window, i)])
    if not vols:
        return False
    threshold_idx = int(len(vols) * q)
    threshold = vols[min(threshold_idx, len(vols) - 1)]
    return rows[i].get("volume", 0) >= threshold


def simulate_coin(rows: list[dict], coin: str, config: dict) -> list[Trade]:
    if len(rows) < 200 + config["fractal_bars"] * 2:
        return []
    fractal = config["fractal_bars"]
    vol_win = config["vol_window_bars"]
    vol_q = config["vol_quartile"]
    ema_sep = config["ema_separation_pct"]
    stop_buf = config["stop_buffer_atr"]
    atr_win = config["atr_window_bars"]
    tp_r = config["tp_r_multiple"]
    max_hold = config["max_hold_bars"]

    daily_closes = _resample_daily(rows)
    # Map each 4h bar to its day index (for HTF gate)
    ts_to_day_idx: dict[int, int] = {}
    sorted_days = sorted({int(r["ts"]) - (int(r["ts"]) % (86_400_000)) for r in rows})
    for i, d in enumerate(sorted_days):
        ts_to_day_idx[d] = i

    trades: list[Trade] = []
    i = 250  # warmup
    last_exit_bar = -1
    while i < len(rows) - 1:
        if i <= last_exit_bar:
            i += 1
            continue

        atr = _atr(rows, i, atr_win)
        if atr is None or atr <= 0:
            i += 1
            continue

        # Detect swings using bars up to i-fractal (confirmed)
        unmit_highs, unmit_lows = _detect_swings(rows, i - fractal, fractal, config["max_unmitigated_swings"])

        # Check sweep at bar i: did high wick > nearest swing high AND close < swing high (reclaim)?
        # OR did low wick < nearest swing low AND close > swing low (bullish reclaim)?
        sweep_dir = 0
        swept_level = None
        if unmit_highs:
            nearest_high = unmit_highs[0]  # closest above
            if rows[i]["high"] > nearest_high and rows[i]["close"] < nearest_high:
                sweep_dir = -1  # bearish reclaim
                swept_level = nearest_high
        if sweep_dir == 0 and unmit_lows:
            nearest_low = unmit_lows[0]
            if rows[i]["low"] < nearest_low and rows[i]["close"] > nearest_low:
                sweep_dir = +1  # bullish reclaim
                swept_level = nearest_low

        if sweep_dir == 0:
            i += 1
            continue

        # HTF gate: trend must agree with reclaim direction
        bar_day = int(rows[i]["ts"]) - (int(rows[i]["ts"]) % 86_400_000)
        day_idx = ts_to_day_idx.get(bar_day, 0)
        htf = _htf_trend(daily_closes, day_idx, ema_sep)
        if htf != sweep_dir:
            i += 1
            continue

        # Volume gate
        if not _vol_quartile(rows, i, vol_win, vol_q):
            i += 1
            continue

        # Entry at next bar open (i+1) — avoid same-bar look-ahead
        if i + 1 >= len(rows):
            break
        entry_idx = i + 1
        entry_px = rows[entry_idx]["open"]

        # Stop = swept_level ± buffer (long: swept_low - buffer; short: swept_high + buffer)
        if sweep_dir == +1:
            stop_px = swept_level - stop_buf * atr
            r = entry_px - stop_px
            if r <= 0:
                i += 1
                continue
            tp_px = entry_px + tp_r * r
        else:
            stop_px = swept_level + stop_buf * atr
            r = stop_px - entry_px
            if r <= 0:
                i += 1
                continue
            tp_px = entry_px - tp_r * r

        # Walk forward up to max_hold bars
        exit_idx = None
        exit_reason = "time_stop"
        exit_px = entry_px
        for fwd in range(1, max_hold + 1):
            j = entry_idx + fwd
            if j >= len(rows):
                exit_idx = len(rows) - 1
                exit_px = rows[exit_idx]["close"]
                break
            bar_h = rows[j]["high"]
            bar_l = rows[j]["low"]
            bar_c = rows[j]["close"]
            if sweep_dir == +1:
                # Long
                if bar_l <= stop_px:
                    exit_idx = j; exit_px = stop_px; exit_reason = "stop"; break
                if bar_h >= tp_px:
                    exit_idx = j; exit_px = tp_px; exit_reason = "tp"; break
            else:
                # Short
                if bar_h >= stop_px:
                    exit_idx = j; exit_px = stop_px; exit_reason = "stop"; break
                if bar_l <= tp_px:
                    exit_idx = j; exit_px = tp_px; exit_reason = "tp"; break
        if exit_idx is None:
            exit_idx = min(entry_idx + max_hold, len(rows) - 1)
            exit_px = rows[exit_idx]["close"]
            exit_reason = "time_stop"

        gross = sweep_dir * (exit_px - entry_px) / entry_px * 100
        net = gross - ROUND_TRIP_COST_PCT
        r_realized = (exit_px - entry_px) / r if sweep_dir == +1 else (entry_px - exit_px) / r

        trades.append(Trade(
            entry_ts=int(rows[entry_idx]["ts"]), entry_idx=entry_idx,
            exit_ts=int(rows[exit_idx]["ts"]), exit_idx=exit_idx,
            coin=coin, side=sweep_dir, entry_px=entry_px,
            stop_px=stop_px, tp_px=tp_px, exit_px=exit_px,
            exit_reason=exit_reason, gross_pnl_pct=gross, net_pnl_pct=net,
            r_realized=r_realized, hold_bars=exit_idx - entry_idx,
        ))
        last_exit_bar = exit_idx
        i = exit_idx + 1
    return trades


def block_ci(xs: list[float], block: int = 8, reps: int = 2000, seed: int = 1729) -> tuple[float, float, float]:
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


def aggregate_weekly(trades: list[Trade]) -> list[float]:
    weekly: dict[int, float] = {}
    for t in trades:
        week_ts = t.entry_ts - (t.entry_ts % (7 * 86_400_000))
        weekly[week_ts] = weekly.get(week_ts, 0.0) + t.net_pnl_pct
    return [weekly[ts] for ts in sorted(weekly)]


def run_variant(config: dict, all_rows: dict[str, list[dict]]) -> VariantResult:
    all_trades: list[Trade] = []
    for coin, rows in all_rows.items():
        trades = simulate_coin(rows, coin, config)
        all_trades.extend(trades)

    pnls = [t.net_pnl_pct for t in all_trades]
    rs = [t.r_realized for t in all_trades]
    if len(pnls) < 10:
        return VariantResult(
            name=config["name"], config=config, n_trades=len(pnls),
            mean_pnl_pct=float("nan"), sum_pnl_pct=float("nan"), mean_r=float("nan"),
            sharpe_t=float("nan"), weekly_sharpe_ann=float("nan"),
            ci_lo=float("nan"), ci_hi=float("nan"), max_dd_pct=float("nan"),
            cpcv_median_sharpe=float("nan"), cpcv_pct_paths_neg=float("nan"),
            dsr=float("nan"), by_exit_reason={},
        )

    mean_t, lo_t, hi_t = block_ci(pnls)
    sd_t = st.pstdev(pnls) if len(pnls) > 1 else 0.0
    sharpe_t = (mean_t / sd_t) if sd_t > 0 else 0.0
    weekly = aggregate_weekly(all_trades)
    sd_w = st.pstdev(weekly) if len(weekly) > 1 else 0.0
    sharpe_w_ann = (st.mean(weekly) / sd_w * math.sqrt(52)) if sd_w > 0 and weekly else 0.0

    cum = 0.0; peak = 0.0; mdd = 0.0
    for w in weekly:
        cum += w
        peak = max(peak, cum)
        if cum - peak < mdd:
            mdd = cum - peak

    if len(weekly) >= 16:
        n = len(weekly)
        bounds = [round(n * g / 8) for g in range(9)]
        samples = [(g, weekly[p], g) for g in range(8) for p in range(bounds[g], bounds[g + 1])]
        cpcv = ofr.cpcv_paths(samples, 8, 2, 1)
    else:
        cpcv = ofr.CPCVResult(8, 2, 0, [], float("nan"), float("nan"), float("nan"), float("nan"), 0.0, note="too few weeks")

    dsr = ofr.deflated_sharpe_ratio(pnls, [ofr.sharpe_ratio(pnls)], n_trials=len(ABLATIONS))

    er = {}
    for t in all_trades:
        er[t.exit_reason] = er.get(t.exit_reason, 0) + 1

    return VariantResult(
        name=config["name"], config=config, n_trades=len(pnls),
        mean_pnl_pct=mean_t, sum_pnl_pct=sum(pnls), mean_r=st.mean(rs) if rs else 0,
        sharpe_t=sharpe_t, weekly_sharpe_ann=sharpe_w_ann,
        ci_lo=lo_t, ci_hi=hi_t, max_dd_pct=mdd,
        cpcv_median_sharpe=cpcv.median, cpcv_pct_paths_neg=cpcv.pct_paths_negative,
        dsr=dsr.dsr, by_exit_reason=er,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablations", action="store_true")
    args = ap.parse_args()

    print("=" * 100)
    print("Phase E.5 — ICT swing-sweep + HTF EMA gate (pre-registered)")
    print(f"  universe: top-{BASELINE['universe_top_n']} Binance perps")
    print(f"  cost: {ROUND_TRIP_COST_PCT}% round-trip")
    print(f"  configs: {[c['name'] for c in (ABLATIONS if args.ablations else [BASELINE])]}")
    print("=" * 100)

    coins = list_coins()
    print(f"Loading {len(coins)} coins...")
    all_rows: dict[str, list[dict]] = {}
    for coin in coins:
        rows = load_perp(coin)
        if rows:
            rows.sort(key=lambda r: r["ts"])
            # Filter to top-N by trailing 30d volume — use last bar's lookback
            all_rows[coin] = rows
    # Restrict to top-N by recent volume (mean of last 30d volume)
    if len(all_rows) > BASELINE["universe_top_n"]:
        vol_means = []
        for coin, rows in all_rows.items():
            last_30d = rows[-30 * BARS_PER_DAY:] if len(rows) > 30 * BARS_PER_DAY else rows
            mean_vol = st.mean([r.get("volume", 0) * r.get("close", 0) for r in last_30d])
            vol_means.append((coin, mean_vol))
        vol_means.sort(key=lambda x: -x[1])
        keep = {c for c, _ in vol_means[:BASELINE["universe_top_n"]]}
        all_rows = {c: r for c, r in all_rows.items() if c in keep}
    print(f"  {len(all_rows)} coins after volume filter")

    configs = ABLATIONS if args.ablations else [BASELINE]
    results: list[VariantResult] = []
    for cfg in configs:
        print(f"\n[RUN] {cfg['name']}", flush=True)
        r = run_variant(cfg, all_rows)
        results.append(r)
        if r.n_trades >= 10:
            print(
                f"  n={r.n_trades}  mean={r.mean_pnl_pct:+.3f}%  CI=[{r.ci_lo:+.3f}%,{r.ci_hi:+.3f}%]  "
                f"sum={r.sum_pnl_pct:+.1f}%  mean_R={r.mean_r:+.2f}  "
                f"sharpe_w_ann={r.weekly_sharpe_ann:+.2f}  DSR={r.dsr:.3f}  exits={r.by_exit_reason}"
            )
        else:
            print(f"  TOO_FEW_TRADES (n={r.n_trades})")

    print()
    print("=" * 100)
    print("SUMMARY (sorted by mean per-trade)")
    print("=" * 100)
    print(f"  {'name':<18s}  {'n':>5s}  {'mean':>10s}  {'95% CI':>22s}  {'sum':>9s}  {'mean_R':>7s}  {'sharpe_w':>9s}  {'DSR':>6s}")
    print("-" * 110)
    for r in sorted(results, key=lambda r: -r.mean_pnl_pct if r.n_trades >= 10 else 999):
        if r.n_trades < 10:
            print(f"  {r.name:<18s}  n={r.n_trades:>3d}  TOO_FEW_TRADES")
            continue
        print(
            f"  {r.name:<18s}  {r.n_trades:>5d}  {r.mean_pnl_pct:+9.3f}%  "
            f"[{r.ci_lo:+7.3f}%,{r.ci_hi:+7.3f}%]  {r.sum_pnl_pct:+8.1f}%  "
            f"{r.mean_r:+6.2f}  {r.weekly_sharpe_ann:+8.2f}  {r.dsr:.3f}"
        )

    print()
    print("=" * 100)
    print("BRANCH ANALYSIS:")
    print("=" * 100)
    baseline = results[0] if results else None
    if baseline and baseline.n_trades >= 10:
        gate_ci = baseline.ci_lo > 0
        gate_dsr = baseline.dsr >= 0.95
        gate_cpcv = baseline.cpcv_pct_paths_neg < 0.25
        print(f"  Baseline gates: CI>0={gate_ci} ({baseline.ci_lo:+.3f}%)  "
              f"DSR≥0.95={gate_dsr} ({baseline.dsr:.3f})  "
              f"CPCV%paths<0<25%={gate_cpcv} ({baseline.cpcv_pct_paths_neg:.1%})")
        if args.ablations:
            passing = sum(1 for r in results if r.n_trades >= 10 and r.ci_lo > 0 and r.dsr >= 0.95)
            print(f"  Ablations passing: {passing}/{len(results)}")
            if gate_ci and gate_dsr and passing >= len(results) * 0.7:
                print("  → BRANCH A: REAL +EV signal")
            elif gate_ci and gate_dsr:
                print("  → BRANCH B: FRAGILE; pure-OOS required")
            else:
                print("  → BRANCH C: NULL #12 — file findings, continue hunt or step back")

    out = Path(_HERE).parent.parent / "analysis" / "data" / "phase_e" / "ict_sweep"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(
        [{"name": r.name, "config": r.config, "n_trades": r.n_trades,
          "mean_pnl_pct": r.mean_pnl_pct, "sum_pnl_pct": r.sum_pnl_pct,
          "mean_r": r.mean_r, "ci_lo": r.ci_lo, "ci_hi": r.ci_hi,
          "weekly_sharpe_ann": r.weekly_sharpe_ann, "dsr": r.dsr,
          "by_exit_reason": r.by_exit_reason} for r in results],
        indent=2, default=str,
    ))
    print(f"\nResults → {(out / 'summary.json').relative_to(Path(_HERE).parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
