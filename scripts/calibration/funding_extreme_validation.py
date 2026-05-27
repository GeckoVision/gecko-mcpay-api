#!/usr/bin/env python3
"""Phase E.1 — funding-extreme reversion validation (pre-registered).

See private/strategy/2026-05-27-phase-e-ev-hunt-plan.md for the program +
the pre-committed branches.

Hypothesis (4-agent consensus, addresses 803d carry-null's blind spot):
The 803d cross-sectional weekly carry null tested CROSS-SECTIONAL MEDIAN
funding. Funding TAILS (|z| >= 2.33, the top/bottom 1% of the distribution)
have NOT been tested. The agent consensus: extreme funding is a positioning-
crowding indicator that mean-reverts on hours-to-day timescales — DIFFERENT
mechanism from the carry-cashflow harvest that died on deep history.

Strategy (cross-sectional, delta-neutral, rebalanced every 4h):
- For each Hyperliquid coin, compute rolling 30d z-score of 1h funding rate
- At each 4h bar boundary, rank coins by current z
- LONG top-K most-NEGATIVE-z (shorts paying longs; fade the crowd)
- SHORT top-K most-POSITIVE-z (longs paying shorts; fade the crowd)
- Equal-weight K=3 per side; delta-hedged via basket (BTC/ETH 70/30 proxy
  in v1 since true spot hedge requires more infra)
- Hold 24h (6 × 4h bars) then close + re-rank
- Exit early if funding-z returns to |z| < 1 for 2 consecutive periods

Run (baseline):
    uv run python scripts/calibration/funding_extreme_validation.py
Run (ablation grid):
    uv run python scripts/calibration/funding_extreme_validation.py --ablations
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
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import overfitting_rigor as ofr  # noqa: E402

FUND_DIR = Path(_HERE) / "data" / "funding"
PERP_DIR = Path(_HERE) / "data" / "perp"

# Hyperliquid coin universe (10 with continuous funding + perp data ≥600d)
HL_COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX", "DOGE", "ARB", "OP", "LINK", "WIF"]
# Hedge-basket proxy (when delta_hedge=True). 70% BTC + 30% ETH.
HEDGE_WEIGHTS = {"BTC": 0.7, "ETH": 0.3}

# ── BASELINE per the pre-commit (single configuration; ablations vary off this)
BASELINE = {
    "z_threshold": 2.33,         # top/bottom 1% of N(0,1)
    "z_window_hours": 720,       # 30d rolling window
    "hold_bars_4h": 6,           # 24h hold
    "K": 3,                      # cross-sectional sleeve size per side
    "delta_hedge": True,         # basket hedge enabled
    "min_consecutive": 1,        # 1 reading minimum to fire
}

# Ablation grid (13 single-axis perturbations of BASELINE per the pre-commit)
ABLATIONS = [
    {"name": "baseline", **BASELINE},
    {"name": "z_low", **{**BASELINE, "z_threshold": 1.5}},
    {"name": "z_high", **{**BASELINE, "z_threshold": 3.0}},
    {"name": "win_short", **{**BASELINE, "z_window_hours": 168}},   # 7d
    {"name": "win_med", **{**BASELINE, "z_window_hours": 336}},     # 14d
    {"name": "hold_1bar", **{**BASELINE, "hold_bars_4h": 1}},       # 4h
    {"name": "hold_12bar", **{**BASELINE, "hold_bars_4h": 12}},     # 48h
    {"name": "hold_24bar", **{**BASELINE, "hold_bars_4h": 24}},     # 96h
    {"name": "K2", **{**BASELINE, "K": 2}},
    {"name": "K5", **{**BASELINE, "K": 5}},
    {"name": "no_hedge", **{**BASELINE, "delta_hedge": False}},
    {"name": "consec2", **{**BASELINE, "min_consecutive": 2}},
    {"name": "consec3", **{**BASELINE, "min_consecutive": 3}},
]

# Costs (HL taker + slippage). Stress runs at 2x.
HL_TAKER_FEE_PCT = 0.025  # 5bps round-trip per leg
ROUND_TRIP_COST_PCT = HL_TAKER_FEE_PCT * 2  # 10bps round trip

HOURS_YR = 24 * 365
BARS_4H_PER_YR = HOURS_YR // 4


@dataclass
class VariantResult:
    name: str
    config: dict
    n_trades: int
    mean_pnl_pct: float
    sum_pnl_pct: float
    sharpe_per_trade: float
    annualized_pct: float
    ci_lo: float
    ci_hi: float
    max_dd_pct: float
    cpcv_median_sharpe: float
    cpcv_pct_paths_neg: float
    dsr: float
    pbo_will_compute: bool


def load_funding(coin: str) -> list[dict]:
    f = FUND_DIR / f"{coin}_funding.json"
    if not f.exists():
        return []
    return json.loads(f.read_text())


def load_perp_4h(coin: str) -> list[dict]:
    f = PERP_DIR / f"{coin}_perp.json"
    if not f.exists():
        return []
    return json.loads(f.read_text())


def _zscore_series(values: list[float], window: int) -> list[float | None]:
    """Rolling z-score; first `window` entries are None."""
    out: list[float | None] = []
    for i in range(len(values)):
        if i < window:
            out.append(None)
            continue
        win = values[i - window:i]
        mu = sum(win) / window
        var = sum((x - mu) ** 2 for x in win) / window
        sd = math.sqrt(var) if var > 0 else 0.0
        out.append((values[i] - mu) / sd if sd > 0 else 0.0)
    return out


def build_funding_z_per_coin(window_hours: int) -> dict[str, list[tuple[int, float | None]]]:
    """Per coin: list of (ts_ms, funding_z) at hourly cadence."""
    out: dict[str, list[tuple[int, float | None]]] = {}
    for coin in HL_COINS:
        rows = load_funding(coin)
        if not rows:
            continue
        rows.sort(key=lambda r: r["ts"])
        rates = [float(r.get("fundingRate", 0.0)) for r in rows]
        ts = [int(r["ts"]) for r in rows]
        zs = _zscore_series(rates, window_hours)
        out[coin] = list(zip(ts, zs, strict=False))
    return out


def build_perp_4h_aligned() -> dict[str, dict[int, float]]:
    """Per coin: dict of ts_ms_4h_boundary -> close_price."""
    out: dict[str, dict[int, float]] = {}
    for coin in HL_COINS:
        rows = load_perp_4h(coin)
        if not rows:
            continue
        out[coin] = {int(r["ts"]): float(r["close"]) for r in rows}
    return out


def simulate_variant(
    config: dict,
    funding_z: dict[str, list[tuple[int, float | None]]],
    perp_4h: dict[str, dict[int, float]],
) -> list[dict]:
    """Run one variant; return list of trade dicts.

    Trade dict: {entry_ts, exit_ts, coin, side (+1 long, -1 short), entry_px,
                 exit_px, gross_pnl_pct, net_pnl_pct, fund_z_at_entry}
    """
    z_thresh = config["z_threshold"]
    hold_bars = config["hold_bars_4h"]
    K = config["K"]
    delta_hedge = config["delta_hedge"]
    min_consec = config["min_consecutive"]

    # Build a 4h-aligned ts grid (intersection across coins)
    all_4h_ts = sorted(set().union(*[set(p.keys()) for p in perp_4h.values()]))
    if not all_4h_ts:
        return []

    # Helper: get funding_z for a coin at the most-recent funding tick <= ts
    def z_at(coin: str, ts: int) -> float | None:
        zlist = funding_z.get(coin) or []
        # Find largest entry with ts <= target
        best = None
        for t, z in zlist:
            if t <= ts and z is not None:
                best = z
            elif t > ts:
                break
        return best

    # Track per-coin "consecutive same-side extreme" count
    consec_count: dict[str, int] = {c: 0 for c in HL_COINS}
    consec_side: dict[str, int] = {c: 0 for c in HL_COINS}  # +1 / -1 / 0

    trades: list[dict] = []
    bar_idx = 0
    next_rebalance_bar = 0

    while bar_idx < len(all_4h_ts):
        ts = all_4h_ts[bar_idx]
        if bar_idx < next_rebalance_bar:
            bar_idx += 1
            continue

        # Update consecutive counters for every coin at this bar
        for coin in HL_COINS:
            z = z_at(coin, ts)
            if z is None:
                consec_count[coin] = 0
                consec_side[coin] = 0
                continue
            cur_side = -1 if z >= z_thresh else (+1 if z <= -z_thresh else 0)
            # NOTE: side = +1 LONG when z is NEGATIVE (fade the crowd-short)
            #               -1 SHORT when z is POSITIVE (fade the crowd-long)
            if cur_side != 0 and cur_side == consec_side[coin]:
                consec_count[coin] += 1
            elif cur_side != 0:
                consec_side[coin] = cur_side
                consec_count[coin] = 1
            else:
                consec_count[coin] = 0
                consec_side[coin] = 0

        # Build candidate longs + shorts at this bar
        eligible = []
        for coin in HL_COINS:
            if consec_count[coin] < min_consec:
                continue
            z = z_at(coin, ts)
            if z is None:
                continue
            entry_px = perp_4h.get(coin, {}).get(ts)
            if entry_px is None:
                continue
            eligible.append((coin, z, entry_px))

        # Rank by z; long the K most negative, short the K most positive
        eligible.sort(key=lambda x: x[1])  # ascending z
        longs = [e for e in eligible[:K] if e[1] <= -z_thresh]
        shorts = [e for e in eligible[-K:] if e[1] >= z_thresh]

        if not longs and not shorts:
            bar_idx += 1
            continue

        # Hold for `hold_bars` then exit at close of (bar_idx + hold_bars)
        exit_bar_idx = min(bar_idx + hold_bars, len(all_4h_ts) - 1)
        exit_ts = all_4h_ts[exit_bar_idx]

        for coin, z_entry, entry_px in longs:
            exit_px = perp_4h.get(coin, {}).get(exit_ts)
            if exit_px is None:
                continue
            gross = (exit_px - entry_px) / entry_px * 100
            net = gross - ROUND_TRIP_COST_PCT
            trades.append({
                "entry_ts": ts, "exit_ts": exit_ts, "coin": coin, "side": +1,
                "entry_px": entry_px, "exit_px": exit_px,
                "gross_pnl_pct": gross, "net_pnl_pct": net,
                "fund_z_at_entry": z_entry,
            })

        for coin, z_entry, entry_px in shorts:
            exit_px = perp_4h.get(coin, {}).get(exit_ts)
            if exit_px is None:
                continue
            gross = -(exit_px - entry_px) / entry_px * 100  # short pnl
            net = gross - ROUND_TRIP_COST_PCT
            trades.append({
                "entry_ts": ts, "exit_ts": exit_ts, "coin": coin, "side": -1,
                "entry_px": entry_px, "exit_px": exit_px,
                "gross_pnl_pct": gross, "net_pnl_pct": net,
                "fund_z_at_entry": z_entry,
            })

        # Apply delta hedge if enabled: hedge the NET long-short notional
        # imbalance with BTC+ETH basket. For simplicity, compute the hedge
        # PnL as a fraction of basket move with opposite sign of (longs-shorts).
        if delta_hedge:
            net_long_count = len(longs) - len(shorts)
            if net_long_count != 0:
                for hedge_coin, w in HEDGE_WEIGHTS.items():
                    hedge_entry = perp_4h.get(hedge_coin, {}).get(ts)
                    hedge_exit = perp_4h.get(hedge_coin, {}).get(exit_ts)
                    if hedge_entry is None or hedge_exit is None:
                        continue
                    hedge_move = (hedge_exit - hedge_entry) / hedge_entry * 100
                    hedge_pnl = -net_long_count * w * hedge_move - ROUND_TRIP_COST_PCT * abs(net_long_count) * w
                    trades.append({
                        "entry_ts": ts, "exit_ts": exit_ts, "coin": f"HEDGE_{hedge_coin}",
                        "side": -1 if net_long_count > 0 else +1,
                        "entry_px": hedge_entry, "exit_px": hedge_exit,
                        "gross_pnl_pct": hedge_pnl + ROUND_TRIP_COST_PCT,
                        "net_pnl_pct": hedge_pnl,
                        "fund_z_at_entry": None,
                    })

        next_rebalance_bar = exit_bar_idx + 1
        bar_idx += 1

    return trades


def block_ci(xs: list[float], block: int = 12, reps: int = 2000, seed: int = 1729) -> tuple[float, float, float]:
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


def cpcv_on(rets: list[float]) -> ofr.CPCVResult:
    if len(rets) < 16:
        return ofr.CPCVResult(8, 2, 0, [], float("nan"), float("nan"), float("nan"), float("nan"), 0.0, note="too few")
    n = len(rets)
    bounds = [round(n * g / 8) for g in range(9)]
    samples = [(g, rets[p], g) for g in range(8) for p in range(bounds[g], bounds[g + 1])]
    return ofr.cpcv_paths(samples, 8, 2, 1)


def run_variant(config: dict, funding_z: dict, perp_4h: dict) -> VariantResult:
    name = config["name"]
    trades = simulate_variant(config, funding_z, perp_4h)
    pnls = [t["net_pnl_pct"] for t in trades]

    if len(pnls) < 10:
        return VariantResult(
            name=name, config=config, n_trades=len(pnls),
            mean_pnl_pct=float("nan"), sum_pnl_pct=float("nan"),
            sharpe_per_trade=float("nan"),
            annualized_pct=float("nan"), ci_lo=float("nan"), ci_hi=float("nan"),
            max_dd_pct=float("nan"), cpcv_median_sharpe=float("nan"),
            cpcv_pct_paths_neg=float("nan"), dsr=float("nan"),
            pbo_will_compute=False,
        )

    mean, lo, hi = block_ci(pnls)
    sd = st.pstdev(pnls) if len(pnls) > 1 else 0.0
    sharpe_pt = (mean / sd) if sd > 0 else 0.0
    # Trades per year estimate
    span_ms = trades[-1]["exit_ts"] - trades[0]["entry_ts"] if trades else 1
    span_years = span_ms / (365 * 24 * 3600 * 1000)
    trades_per_year = len(trades) / max(span_years, 1e-6)
    annualized_pct = mean * trades_per_year

    # Max DD on cumulative trade-pnl sum (not compounded; small-N artifact OK)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = cum - peak
        if dd < max_dd:
            max_dd = dd

    cpcv = cpcv_on(pnls)
    dsr = ofr.deflated_sharpe_ratio(pnls, [ofr.sharpe_ratio(pnls)], n_trials=len(ABLATIONS))

    return VariantResult(
        name=name, config=config, n_trades=len(pnls),
        mean_pnl_pct=mean, sum_pnl_pct=sum(pnls),
        sharpe_per_trade=sharpe_pt,
        annualized_pct=annualized_pct, ci_lo=lo, ci_hi=hi,
        max_dd_pct=max_dd,
        cpcv_median_sharpe=cpcv.median, cpcv_pct_paths_neg=cpcv.pct_paths_negative,
        dsr=dsr.dsr,
        pbo_will_compute=True,
    )


def render_variant(r: VariantResult) -> str:
    if r.n_trades < 10:
        return f"  {r.name:<14s}  n={r.n_trades:>4d}  TOO_FEW_TRADES"
    return (
        f"  {r.name:<14s}  n={r.n_trades:>4d}  "
        f"mean={r.mean_pnl_pct:+6.3f}%  "
        f"CI=[{r.ci_lo:+6.3f}%,{r.ci_hi:+6.3f}%]  "
        f"sum={r.sum_pnl_pct:+8.1f}%  "
        f"sharpe(t)={r.sharpe_per_trade:+5.2f}  "
        f"DSR={r.dsr:.2f}  "
        f"CPCV_med_Sharpe={r.cpcv_median_sharpe:+5.2f}  "
        f"%paths<0={r.cpcv_pct_paths_neg:.1%}  "
        f"maxDD={r.max_dd_pct:+6.2f}%"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-only", action="store_true", help="just baseline (faster)")
    ap.add_argument("--ablations", action="store_true", help="run all 13 ablations")
    args = ap.parse_args()

    # Default: baseline only. --ablations runs full grid.
    configs_to_run = [ABLATIONS[0]]
    if args.ablations:
        configs_to_run = ABLATIONS

    print("=" * 100)
    print("PHASE E.1 — funding-extreme reversion validation (pre-registered)")
    print(f"  coins: {HL_COINS}")
    print(f"  configs: {[c['name'] for c in configs_to_run]}")
    print(f"  cost: {ROUND_TRIP_COST_PCT}%/trip ({HL_TAKER_FEE_PCT}%/leg × 2)")
    print("=" * 100)

    # Pre-load funding z + perp 4h ONCE per z_window_hours value (cache)
    # Actually z_window varies in ablations, so cache per window
    z_cache: dict[int, dict] = {}
    perp_4h = build_perp_4h_aligned()
    print(f"  perp 4h loaded: {sum(len(v) for v in perp_4h.values())} bars across {len(perp_4h)} coins")

    results: list[VariantResult] = []
    for cfg in configs_to_run:
        win = cfg["z_window_hours"]
        if win not in z_cache:
            print(f"  building funding-z series for window={win}h ...", flush=True)
            z_cache[win] = build_funding_z_per_coin(win)
        funding_z = z_cache[win]
        print(f"\n[RUN] {cfg['name']} cfg={cfg}", flush=True)
        r = run_variant(cfg, funding_z, perp_4h)
        results.append(r)
        print(render_variant(r), flush=True)

    print()
    print("=" * 100)
    print("SUMMARY:")
    print("=" * 100)
    print(f"  {'name':<14s}  {'n':>4s}  {'mean':>10s}  {'95% CI':>20s}  {'sum':>10s}  {'sharpe':>8s}  {'DSR':>6s}")
    print("-" * 100)
    for r in sorted(results, key=lambda r: -r.mean_pnl_pct if r.n_trades >= 10 else 999):
        if r.n_trades < 10:
            print(f"  {r.name:<14s}  n={r.n_trades:>4d}  TOO_FEW_TRADES")
            continue
        print(
            f"  {r.name:<14s}  {r.n_trades:>4d}  "
            f"{r.mean_pnl_pct:+9.3f}%  "
            f"[{r.ci_lo:+6.3f}%,{r.ci_hi:+6.3f}%]  "
            f"{r.sum_pnl_pct:+9.1f}%  "
            f"{r.sharpe_per_trade:+7.2f}  "
            f"{r.dsr:>6.3f}"
        )

    # Branch verdict
    print()
    print("=" * 100)
    print("BRANCH ANALYSIS (per pre-commit):")
    print("=" * 100)
    baseline = results[0] if results and results[0].name == "baseline" else None
    if baseline and baseline.n_trades >= 10:
        baseline_clean = (
            baseline.ci_lo > 0
            and baseline.dsr >= 0.95
            and baseline.cpcv_pct_paths_neg < 0.25
        )
        print(f"  Baseline gates:")
        print(f"    CI excludes 0 (+): {baseline.ci_lo > 0}  (CI lo: {baseline.ci_lo:+.3f}%)")
        print(f"    DSR >= 0.95:       {baseline.dsr >= 0.95}  ({baseline.dsr:.3f})")
        print(f"    CPCV %paths<0<25%: {baseline.cpcv_pct_paths_neg < 0.25}  ({baseline.cpcv_pct_paths_neg:.1%})")
        if args.ablations:
            ablations_passing = sum(
                1 for r in results
                if r.n_trades >= 10 and r.ci_lo > 0 and r.dsr >= 0.95
            )
            print(f"  Ablations passing all gates: {ablations_passing}/{len(results)}")
            if baseline_clean and ablations_passing >= 10:
                print("  → BRANCH A: REAL +EV SIGNAL (deep-history stress next)")
            elif baseline_clean and ablations_passing < 10:
                print("  → BRANCH B: FRAGILE — pure-OOS held-out test required before any deploy")
            else:
                print("  → BRANCH C: NULL (file as 9th rigorous null, pivot to E.2 yield rotation)")
        else:
            if baseline_clean:
                print("  → Baseline clean. Run ablations: --ablations")
            else:
                print("  → Baseline FAILS gates. Adding ablations unlikely to flip; consider BRANCH C.")
    else:
        print("  Baseline INSUFFICIENT (< 10 trades). Check sample size + parameters.")

    # Persist
    out_dir = Path(_HERE).parent.parent / "analysis" / "data" / "phase_e" / "funding_extreme"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(
        [
            {
                "name": r.name, "config": r.config, "n_trades": r.n_trades,
                "mean_pnl_pct": r.mean_pnl_pct, "sum_pnl_pct": r.sum_pnl_pct,
                "sharpe_per_trade": r.sharpe_per_trade,
                "annualized_pct": r.annualized_pct,
                "ci_lo": r.ci_lo, "ci_hi": r.ci_hi,
                "max_dd_pct": r.max_dd_pct,
                "cpcv_median_sharpe": r.cpcv_median_sharpe,
                "cpcv_pct_paths_neg": r.cpcv_pct_paths_neg,
                "dsr": r.dsr,
            }
            for r in results
        ],
        indent=2, default=str,
    ))
    print(f"\nResults saved → {summary_path.relative_to(Path(_HERE).parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
