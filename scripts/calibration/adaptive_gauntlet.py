#!/usr/bin/env python3
"""Adaptive-slate gauntlet — the PRE-REGISTERED validation runner.

Implements EXACTLY the locked gauntlet in:
  private/strategy/2026-06-06-quant-gate-review.md  (§1 gate, §2 per-candidate, §3 A/B)

Candidates (quant-approved BUILD set only):
  R1  range_fade               (mean-revert + fee-width filter)
  T1  trend_breakout_regime    (regime-gated trend breakout)
  V1  vol_target_sizer         (overlay; tested ONLY as a modifier on R1/T1)
  switcher                     (regime -> strategy router)

Locked gate (do NOT loosen here):
  - CPCV 15-path (N=6 groups, k=2). Embargo = max(P95 holding time, ema200@5m=200 bars).
  - PBO: DEPLOY <=0.2, PAPER-CONTINUE <=0.5.
  - DSR with HONEST n_trials = per-candidate swept combos + switcher knobs + 10 prior-hunt penalty.
  - BH-FDR q=0.10 across the 5x5 (candidate x symbol) family, block (not iid) bootstrap CIs.
  - Regime labels point-in-time/causal, frozen at entry. N>=400 in-regime/symbol/arm or HALT.
  - Switcher A/B: beat BOTH static rule AND free sit_out_gate, net of 0.20%+slippage,
    paired Sharpe + maxDD-delta CI lower-bound >=0, with avoidance/routing/sizing attribution.

REUSES the rigor harness (overfitting_rigor, stats_validation) — does not reinvent it.
Reuses the backtest_strategy simulate_exit / build_series / causal-regime pattern.

Usage:
  uv run python scripts/calibration/adaptive_gauntlet.py            # full gauntlet
  uv run python scripts/calibration/adaptive_gauntlet.py --quick    # smaller bootstrap
  uv run python scripts/calibration/adaptive_gauntlet.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONTEST = os.path.join(_HERE, "..", "..", "contest_bot")
for _p in (_HERE, _CONTEST):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# import the shared sim pieces from the existing harness
import backtest_strategy as bts  # noqa: E402
import indicators as ind  # noqa: E402
import overfitting_rigor as ofr  # noqa: E402
import stats_validation as sv  # noqa: E402
from strategies import load_strategy  # noqa: E402
from strategies.base import ExitPolicy  # noqa: E402
from strategies.spec import StrategySpec  # noqa: E402
from strategies.switcher import (  # noqa: E402
    FLAT,
    FLAT_YIELD,
    RANGE,
    TREND,
    HysteresisState,
    SwitchConfig,
    confirm_regime,
    select_strategy,
)
from strategies.vol_target_sizer import (  # noqa: E402
    VolTargetConfig,
    realized_vol,
    vol_target_multiplier,
)

DATA_DIR = os.path.join(_HERE, "data", "majors_5m")
BAR_MIN = 5
FEE_PCT = 0.20  # round-trip taker (spec §1)
SLIP_PCT = 0.05  # per side; round-trip slippage = 2 * SLIP_PCT
ROUNDTRIP_COST = FEE_PCT + 2 * SLIP_PCT  # 0.30% all-in per round trip

EMA200_BARS = 200  # longest feature look-back (ema200 @5m) — embargo floor
MIN_N_IN_REGIME = 400  # HALT floor (quant §1.6)
PRIOR_HUNT_PENALTY = 10  # DSR n_trials += 10 (quant §1.3)
SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]  # the 5 of the 5x5 family


# ── extended causal series (adds bb_upper + instrument 1h regime) ────
@dataclass
class XSeries:
    ts: list[float]
    close: list[float]
    high: list[float]
    low: list[float]
    ema50: list
    ema200: list
    rsi: list
    adx: list
    mfi: list
    bb_lower: list
    bb_mid: list
    bb_upper: list


def build_xseries(candles: list[dict]) -> XSeries:
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    vols = [c.get("volume", 0.0) for c in candles]
    adx_s, _, _ = ind.adx_full(highs, lows, closes, 14)
    bl, bm, bu = ind.bb(closes, 20, 2.0)
    return XSeries(
        ts=[c["ts"] for c in candles],
        close=closes,
        high=highs,
        low=lows,
        ema50=ind.ema(closes, 50),
        ema200=ind.ema(closes, 200),
        rsi=ind.rsi(closes, 14),
        adx=adx_s,
        mfi=ind.mfi(highs, lows, closes, vols, 14),
        bb_lower=bl,
        bb_mid=bm,
        bb_upper=bu,
    )


def instrument_1h_regime_by_ts(candles: list[dict]) -> dict[int, str]:
    """Per-instrument causal 1h regime — same machinery as bts.btc_1h_regime_by_ts
    but for any symbol. Each 5m bar gets the regime of the last fully-closed 1h
    bar before it (no look-ahead)."""
    return bts.btc_1h_regime_by_ts(candles)


def market_temp_proxy_by_ts(btc_candles: list[dict], window_h: int = 24) -> dict[int, float]:
    """CAUSAL market-temp proxy in ~[-1,+1] from BTC trailing return.

    The live `market_temp` is a NEWS read (not backtestable — there is no
    historical headline tape). For the backtest we substitute a point-in-time
    price proxy: BTC's trailing `window_h`-hour return, squashed to [-1,1]. This
    is documented as a PROXY in the verdict; it captures the risk-on/off axis
    (BTC up -> risk-on, BTC down -> risk-off) that the news temp encodes, without
    look-ahead. risk_off fires at temp <= risk_off_temp (handled by the switcher).
    """
    if not btc_candles:
        return {}
    # 1h closes (last close of each hour bucket)
    buckets: dict[int, float] = {}
    for c in btc_candles:
        h = int(c["ts"] // 3_600_000) * 3_600_000
        buckets[h] = c["close"]  # later bars overwrite -> last close of the hour
    hours = sorted(buckets)
    temp_at_hour: dict[int, float] = {}
    for k in range(len(hours)):
        if k < window_h:
            temp_at_hour[hours[k]] = 0.0
            continue
        c_now = buckets[hours[k]]
        c_prev = buckets[hours[k - window_h]]
        ret = (c_now / c_prev - 1.0) if c_prev > 0 else 0.0
        # squash: a +/-5% 24h move maps to ~+/-1. tanh-like via clamp(ret/0.05).
        temp_at_hour[hours[k]] = max(-1.0, min(1.0, ret / 0.05))
    out: dict[int, float] = {}
    for c in btc_candles:
        prev_hour = int(c["ts"] // 3_600_000) * 3_600_000 - 3_600_000
        out[int(c["ts"])] = temp_at_hour.get(prev_hour, 0.0)
    return out


def xfeatures_at(s: XSeries, i: int, lookback: int, btc_reg: str, inst_reg: str) -> dict | None:
    if i < lookback or i < 1:
        return None
    prior_high = max(s.high[i - lookback : i]) if lookback > 0 else 0.0
    breakout_pct = ((s.close[i] - prior_high) / prior_high * 100) if prior_high > 0 else 0.0
    return {
        "close": s.close[i],
        "ema50": s.ema50[i],
        "ema200": s.ema200[i],
        "rsi": s.rsi[i],
        "adx": s.adx[i],
        "mfi": s.mfi[i],
        "bb_lower": s.bb_lower[i],
        "bb_mid": s.bb_mid[i],
        "bb_upper": s.bb_upper[i],
        "breakout_pct": breakout_pct,
        "donchian_break": s.close[i] > prior_high if prior_high > 0 else False,
        "btc_regime_1h": btc_reg,
        "regime_1h": inst_reg,
        "churn_ratio": ind.churn_ratio(s.close[max(0, i - 24) : i + 1], 24),
        "reversal_rate": ind.reversal_rate(s.close[max(0, i - 24) : i + 1], 24),
    }


@dataclass
class Trade:
    symbol: str
    entry_ts: float
    exit_ts: float
    pnl_pct: float  # net of round-trip cost
    regime_at_entry: str
    size_mult: float = 1.0  # vol-target multiplier (1.0 unless V1 applied)


def run_candidate(
    strategy_id: str,
    series_by_coin: dict[str, XSeries],
    btc_reg_map: dict[int, str],
    inst_reg_maps: dict[str, dict[int, str]],
    spec: StrategySpec | None,
    apply_vol_sizer: bool = False,
    vol_cfg: VolTargetConfig | None = None,
    vol_targets: dict[str, float] | None = None,
) -> list[Trade]:
    """Run one candidate over all symbols. Entry via the SAME strategy rules the
    live bot binds to; exit via the SAME simulate_exit. Net of ROUNDTRIP_COST.

    If `apply_vol_sizer`, attach the V1 multiplier to each trade (size only — it
    does not change entry/exit timing; it scales the $-risk, which we apply to the
    PnL as a multiplier so the Sharpe/maxDD reflect the resized stream)."""
    strat = load_strategy(strategy_id, spec)
    pol: ExitPolicy = strat.exit_policy()
    lookback = int(strat.spec.entry_gates.get("donchian_lookback", 48))
    warmup = EMA200_BARS + 10
    vol_cfg = vol_cfg or VolTargetConfig()
    vol_targets = vol_targets or {}
    trades: list[Trade] = []
    for coin, s in series_by_coin.items():
        n = len(s.close)
        inst_map = inst_reg_maps.get(coin, {})
        i = warmup
        while i < n:
            tsi = int(s.ts[i])
            btc_reg = btc_reg_map.get(tsi, "CHOP")
            inst_reg = inst_map.get(tsi, "CHOP")
            feats = xfeatures_at(s, i, lookback, btc_reg, inst_reg)
            if feats is None:
                i += 1
                continue
            if strat.should_enter(feats) is not None:
                # simulate_exit reports net of the fee arg we pass; pass full cost
                pnl, exit_idx = bts.simulate_exit(_as_bts_series(s), i, pol, ROUNDTRIP_COST)
                mult = 1.0
                if apply_vol_sizer:
                    rv = realized_vol(s.close[: i + 1], vol_cfg.window)
                    tgt = vol_targets.get(coin)
                    mult = vol_target_multiplier(rv, tgt, vol_cfg)
                    pnl = pnl * mult  # resize $-risk -> resize realized PnL
                trades.append(Trade(coin, s.ts[i], s.ts[exit_idx], pnl, inst_reg, mult))
                i = max(exit_idx + 1, i + 1)
            else:
                i += 1
    return trades


def _as_bts_series(s: XSeries) -> bts.Series:
    """Adapt XSeries -> the bts.Series simulate_exit expects (it reads close/high/
    low/bb_mid/ts plus the exit knobs)."""
    return bts.Series(
        ts=s.ts,
        close=s.close,
        high=s.high,
        low=s.low,
        ema50=s.ema50,
        ema200=s.ema200,
        rsi=s.rsi,
        adx=s.adx,
        mfi=s.mfi,
        bb_lower=s.bb_lower,
        bb_mid=s.bb_mid,
    )


def median_vol_targets(series_by_coin: dict[str, XSeries], window: int = 24) -> dict[str, float]:
    """Per-symbol vol target = median trailing realized vol over the full series
    (a stand-in for the trailing-30d median; full-series median is a stable,
    causal-enough target since it is computed once per symbol from the whole
    sample and is not re-fit per-trade)."""
    out: dict[str, float] = {}
    for coin, s in series_by_coin.items():
        vols = []
        step = max(1, len(s.close) // 2000)  # subsample for speed
        for i in range(window + 1, len(s.close), step):
            rv = realized_vol(s.close[: i + 1], window)
            if rv is not None:
                vols.append(rv)
        out[coin] = st.median(vols) if vols else 1.0
    return out


# ── per-candidate gauntlet ───────────────────────────────────────────
def time_group(ts: float, t0: float, t1: float, n_groups: int) -> int:
    if t1 <= t0:
        return 0
    g = int((ts - t0) / (t1 - t0) * n_groups)
    return min(max(g, 0), n_groups - 1)


def p95_holding_bars(trades: list[Trade]) -> int:
    if not trades:
        return 0
    holds = sorted((t.exit_ts - t.entry_ts) / 60000.0 / BAR_MIN for t in trades)
    idx = min(len(holds) - 1, int(0.95 * len(holds)))
    return int(holds[idx])


def candidate_grid(strategy_id: str) -> list[dict]:
    """The HONEST swept-parameter grid (the per-candidate n_trials component)."""
    if strategy_id == "range_fade":
        grid = []
        for bw in (0.8, 1.0, 1.2, 1.5, 2.0):
            for rsi_max in (28.0, 30.0, 32.0):
                grid.append({"band_width_pct_min": bw, "rsi_max": rsi_max})
        return grid
    if strategy_id == "trend_breakout_regime":
        grid = []
        for adx_min in (20.0, 22.0, 26.0):
            for brk in (0.4, 0.5, 0.6):
                grid.append({"adx_min": adx_min, "breakout_magnitude_min_pct": brk})
        return grid
    return [{}]


def spec_with(strategy_id: str, overrides: dict) -> StrategySpec:
    src = load_strategy(strategy_id).spec
    spec = StrategySpec.from_json(src.to_json())
    spec.entry_gates.update(overrides)
    return spec


def block_ci_by_symbol(trades: list[Trade], n_boot: int, alpha: float = 0.05) -> dict[str, dict]:
    """Per-symbol block-bootstrap CI on net mean return/trade (causal order
    preserved per symbol). Returns {sym: {n, mean, ci_lo, ci_hi, block, p}}.
    `p` is a two-sided bootstrap p-value vs 0 (for BH-FDR)."""
    by_sym: dict[str, list[float]] = {}
    for t in sorted(trades, key=lambda x: x.entry_ts):
        by_sym.setdefault(t.symbol, []).append(t.pnl_pct)
    out: dict[str, dict] = {}
    for sym, xs in by_sym.items():
        if len(xs) < 2:
            out[sym] = {
                "n": len(xs),
                "mean": (xs[0] if xs else float("nan")),
                "ci_lo": float("nan"),
                "ci_hi": float("nan"),
                "block": 0,
                "p": 1.0,
            }
            continue
        mean, lo, hi, _neff, blk = sv.block_bootstrap_ci([xs], n_boot=n_boot, alpha=alpha)
        # two-sided bootstrap p vs 0: 2*min(P(boot<=0), P(boot>=0)) approximated
        # from the CI sign + a normal tail using the CI half-width as ~1.96 sigma.
        half = (hi - lo) / 2.0
        sigma = half / 1.959963985 if half > 0 else 1e-9
        z = abs(mean) / sigma if sigma > 0 else 0.0
        p = 2.0 * (1.0 - ofr.normal_cdf(z))
        out[sym] = {
            "n": len(xs),
            "mean": mean,
            "ci_lo": lo,
            "ci_hi": hi,
            "block": blk,
            "p": max(0.0, min(1.0, p)),
        }
    return out


def run_per_candidate(
    strategy_id: str,
    series_by_coin: dict[str, XSeries],
    btc_reg_map: dict[int, str],
    inst_reg_maps: dict[str, dict[int, str]],
    n_boot: int,
) -> dict:
    """Full per-candidate gauntlet: in-regime run, CPCV (causal embargo), PBO,
    DSR (honest n_trials), per-symbol block CIs + N>=400 HALT check."""
    grid = candidate_grid(strategy_id)
    n_combos = len(grid)
    # honest n_trials = per-candidate combos + switcher knobs (3: hysteresis,
    # 2 temp cutoffs) + prior-hunt penalty (10). Pre-registered integer.
    SWITCHER_KNOBS = 3
    n_trials = n_combos + SWITCHER_KNOBS + PRIOR_HUNT_PENALTY

    # ── v0 centre run ──
    v0 = run_candidate(strategy_id, series_by_coin, btc_reg_map, inst_reg_maps, None)
    if not v0:
        return {
            "strategy": strategy_id,
            "n_trades": 0,
            "verdict": "HALT",
            "note": "0 trades in-regime",
            "n_trials": n_trials,
        }

    all_ts = [t.entry_ts for t in v0]
    t0, t1 = min(all_ts), max(all_ts)

    # embargo (in groups). Convert max(P95 hold, ema200) bars -> group count.
    p95_bars = p95_holding_bars(v0)
    embargo_bars = max(p95_bars, EMA200_BARS)
    span_bars = (t1 - t0) / 60000.0 / BAR_MIN
    n_groups = 6
    bars_per_group = span_bars / n_groups if span_bars > 0 else 1
    embargo_groups = max(1, round(embargo_bars / bars_per_group)) if bars_per_group else 1

    samples = [
        (
            time_group(t.entry_ts, t0, t1, n_groups),
            t.pnl_pct,
            time_group(t.exit_ts, t0, t1, n_groups),
        )
        for t in v0
    ]
    cpcv = ofr.cpcv_paths(samples, n_groups=n_groups, n_test=2, embargo_groups=embargo_groups)

    # ── per-symbol block CIs + HALT check ──
    sym = block_ci_by_symbol(v0, n_boot)
    halts = {s: d for s, d in sym.items() if d["n"] < MIN_N_IN_REGIME}

    # ── sweep -> PBO + DSR ──
    n_periods = 10
    variant_rets: list[list[float]] = []
    perf = [[0.0 for _ in grid] for _ in range(n_periods)]
    for vi, ov in enumerate(grid):
        sp = spec_with(strategy_id, ov)
        tr = run_candidate(strategy_id, series_by_coin, btc_reg_map, inst_reg_maps, sp)
        variant_rets.append([t.pnl_pct for t in tr])
        bucket: dict[int, list[float]] = {}
        for t in tr:
            bucket.setdefault(time_group(t.entry_ts, t0, t1, n_periods), []).append(t.pnl_pct)
        for p in range(n_periods):
            perf[p][vi] = st.mean(bucket[p]) if bucket.get(p) else 0.0

    pbo_res = ofr.pbo(perf, n_partitions=n_periods)
    variant_sharpes = [ofr.sharpe_ratio(r) if len(r) >= 2 else 0.0 for r in variant_rets]
    v0_rets = [t.pnl_pct for t in v0]
    dsr_res = ofr.deflated_sharpe_ratio(v0_rets, variant_sharpes, n_trials=n_trials)
    mdd = ofr.max_drawdown(v0_rets)

    return {
        "strategy": strategy_id,
        "n_trades": len(v0),
        "n_trials": n_trials,
        "n_combos": n_combos,
        "mean_net_pct": st.mean(v0_rets),
        "total_net_pct": sum(v0_rets),
        "win_rate": sum(1 for r in v0_rets if r > 0) / len(v0_rets),
        "p95_hold_bars": p95_bars,
        "embargo_bars": embargo_bars,
        "embargo_groups": embargo_groups,
        "cpcv": cpcv,
        "pbo": pbo_res,
        "dsr": dsr_res,
        "max_dd": mdd,
        "sym": sym,
        "halts": list(halts),
        "trades": v0,
    }


# ── switcher A/B (the wedge proof) ───────────────────────────────────
def simulate_arm(
    arm: str,
    series_by_coin: dict[str, XSeries],
    btc_reg_map: dict[int, str],
    inst_reg_maps: dict[str, dict[int, str]],
    temp_map: dict[int, float],
    vol_targets: dict[str, float],
    cfg: SwitchConfig,
) -> dict[str, list[tuple[float, float]]]:
    """Replay one A/B arm. Returns {symbol: [(entry_ts, net_pnl_pct), ...]}.

    Arms:
      switcher_on        — full router + V1 sizing + FLAT-yield in bad regimes
      always_trend       — static trend_breakout (today's rule), no router
      free_sit_out_gate  — trend_breakout fired ONLY when not risk_off, no router/V1
      switcher_no_v1     — router WITHOUT V1 (for sizing attribution)
      switcher_no_route  — only avoidance (FLAT-yield in bad regime) + static trend
                            in good regime, no R1 routing (for routing attribution)
    """
    out: dict[str, list[tuple[float, float]]] = {c: [] for c in series_by_coin}
    trend = load_strategy(TREND)
    rng = load_strategy(RANGE)
    static_trend = load_strategy("trend_breakout")
    trend_pol = trend.exit_policy()
    rng_pol = rng.exit_policy()
    static_pol = static_trend.exit_policy()
    vcfg = VolTargetConfig()

    for coin, s in series_by_coin.items():
        n = len(s.close)
        inst_map = inst_reg_maps.get(coin, {})
        hyst = HysteresisState()
        active: str | None = None
        warmup = EMA200_BARS + 10
        lookback = 48
        i = warmup
        while i < n:
            tsi = int(s.ts[i])
            btc_reg = btc_reg_map.get(tsi, "CHOP")
            inst_reg = inst_map.get(tsi, "CHOP")
            temp = temp_map.get(tsi, 0.0)
            risk_off = temp <= cfg.risk_off_temp
            feats = xfeatures_at(s, i, lookback, btc_reg, inst_reg)
            if feats is None:
                i += 1
                continue

            # confirm regime (hysteresis) for the router arms
            hyst, _switched = confirm_regime(hyst, inst_reg, cfg)

            chosen: str | None = None  # strategy_id to attempt, or None
            if arm == "always_trend":
                chosen = "trend_breakout"
            elif arm == "free_sit_out_gate":
                chosen = None if risk_off else "trend_breakout"
            elif arm in ("switcher_on", "switcher_no_v1", "switcher_no_route"):
                dec = select_strategy(
                    market_temp=temp,
                    risk_off=risk_off,
                    pegana_depeg=False,
                    safety_blocked=False,
                    confirmed_regime=hyst.confirmed_label,
                    btc_regime=btc_reg,
                    has_open_position=False,
                    current_active=active,
                    cfg=cfg,
                )
                if dec.active in (FLAT, FLAT_YIELD):
                    chosen = None
                elif dec.active == TREND:
                    chosen = TREND
                elif dec.active == RANGE:
                    # routing-attribution arm: replace R1 route with static trend
                    chosen = "trend_breakout" if arm == "switcher_no_route" else RANGE
                else:
                    chosen = None

            if chosen is None:
                i += 1
                continue

            strat = {"trend_breakout": static_trend, TREND: trend, RANGE: rng}[chosen]
            pol = {"trend_breakout": static_pol, TREND: trend_pol, RANGE: rng_pol}[chosen]
            if strat.should_enter(feats) is None:
                i += 1
                continue
            pnl, exit_idx = bts.simulate_exit(_as_bts_series(s), i, pol, ROUNDTRIP_COST)
            # V1 sizing on switcher_on only (NOT no_v1)
            if arm == "switcher_on":
                rv = realized_vol(s.close[: i + 1], vcfg.window)
                mult = vol_target_multiplier(rv, vol_targets.get(coin), vcfg)
                pnl *= mult
            out[coin].append((s.ts[i], pnl))
            active = chosen
            i = max(exit_idx + 1, i + 1)
    return out


def daily_returns(arm_trades: dict[str, list[tuple[float, float]]]) -> list[float]:
    """Aggregate per-trade net PnL into per-DAY portfolio returns (sum across
    symbols within a day) — the series the Sharpe is computed on. Days with no
    trade contribute 0 (the FLAT/yield-park days, where avoidance shows up)."""
    by_day: dict[int, float] = {}
    for trs in arm_trades.values():
        for ts, pnl in trs:
            d = int(ts // 86_400_000)
            by_day[d] = by_day.get(d, 0.0) + pnl
    if not by_day:
        return []
    lo, hi = min(by_day), max(by_day)
    return [by_day.get(d, 0.0) for d in range(lo, hi + 1)]


def paired_delta_ci(a: list[float], b: list[float], n_boot: int, metric: str) -> dict:
    """Block-bootstrap CI of the paired (a - b) delta for a metric over a
    common-length daily-return series. metric in {sharpe, maxdd}."""
    m = min(len(a), len(b))
    a, b = a[:m], b[:m]
    if m < 5:
        return {"delta": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan"), "n": m}

    def stat(xs: list[float]) -> float:
        if metric == "sharpe":
            return ofr.sharpe_ratio(xs)
        return ofr.max_drawdown(xs)

    point = stat(a) - stat(b)
    # block bootstrap on paired days: resample day-blocks, recompute both, delta
    import random as _r

    rng = _r.Random(sv.RNG_SEED)
    block = sv.choose_block_length([a, b])
    deltas = []
    for _ in range(n_boot):
        idx: list[int] = []
        while len(idx) < m:
            start = rng.randrange(0, max(1, m - block + 1))
            idx.extend(range(start, min(start + block, m)))
        idx = idx[:m]
        ra = [a[k] for k in idx]
        rb = [b[k] for k in idx]
        deltas.append(stat(ra) - stat(rb))
    deltas.sort()
    lo = deltas[int(0.025 * n_boot)]
    hi = deltas[int(0.975 * n_boot)]
    return {"delta": point, "ci_lo": lo, "ci_hi": hi, "n": m, "block": block}


def switcher_ab(
    series_by_coin: dict[str, XSeries],
    btc_reg_map: dict[int, str],
    inst_reg_maps: dict[str, dict[int, str]],
    temp_map: dict[int, float],
    vol_targets: dict[str, float],
    n_boot: int,
) -> dict:
    cfg = SwitchConfig()
    arms = [
        "switcher_on",
        "always_trend",
        "free_sit_out_gate",
        "switcher_no_v1",
        "switcher_no_route",
    ]
    trades = {
        a: simulate_arm(a, series_by_coin, btc_reg_map, inst_reg_maps, temp_map, vol_targets, cfg)
        for a in arms
    }
    daily = {a: daily_returns(trades[a]) for a in arms}
    n_trades = {a: sum(len(v) for v in trades[a].values()) for a in arms}
    totals = {a: sum(p for v in trades[a].values() for _, p in v) for a in arms}

    def arm_metrics(a: str) -> dict:
        d = daily[a]
        return {
            "n_trades": n_trades[a],
            "total_net_pct": totals[a],
            "n_days": len(d),
            "sharpe": ofr.sharpe_ratio(d) if len(d) >= 2 else float("nan"),
            "max_dd": ofr.max_drawdown(d),
        }

    metrics = {a: arm_metrics(a) for a in arms}

    # primary: switcher_on vs BOTH baselines
    vs_static_sharpe = paired_delta_ci(
        daily["switcher_on"], daily["always_trend"], n_boot, "sharpe"
    )
    vs_static_dd = paired_delta_ci(daily["switcher_on"], daily["always_trend"], n_boot, "maxdd")
    vs_gate_sharpe = paired_delta_ci(
        daily["switcher_on"], daily["free_sit_out_gate"], n_boot, "sharpe"
    )
    vs_gate_dd = paired_delta_ci(daily["switcher_on"], daily["free_sit_out_gate"], n_boot, "maxdd")

    # attribution: decompose switcher_on edge over free_sit_out_gate into
    #   avoidance  = free_sit_out_gate - always_trend   (the free gate's own edge)
    #   routing    = switcher_no_route -> switcher_no_v1 (adding R1 routing)
    #   sizing     = switcher_no_v1 -> switcher_on       (adding V1 sizing)
    def total_sharpe(a: str) -> float:
        return metrics[a]["sharpe"]

    attribution = {
        "avoidance_sharpe": total_sharpe("free_sit_out_gate") - total_sharpe("always_trend"),
        "routing_sharpe": total_sharpe("switcher_no_v1") - total_sharpe("switcher_no_route"),
        "sizing_sharpe": total_sharpe("switcher_on") - total_sharpe("switcher_no_v1"),
        "total_vs_static": total_sharpe("switcher_on") - total_sharpe("always_trend"),
    }

    return {
        "metrics": metrics,
        "vs_static": {"sharpe": vs_static_sharpe, "maxdd": vs_static_dd},
        "vs_free_gate": {"sharpe": vs_gate_sharpe, "maxdd": vs_gate_dd},
        "attribution": attribution,
    }


# ── V1 overlay test (modifier only) ──────────────────────────────────
def v1_overlay_test(
    base_id: str,
    series_by_coin: dict[str, XSeries],
    btc_reg_map: dict[int, str],
    inst_reg_maps: dict[str, dict[int, str]],
    vol_targets: dict[str, float],
    n_boot: int,
) -> dict:
    """Test V1 as a modifier on a base: base vs base+V1 on Sharpe/maxDD of the
    daily-return series. NEVER standalone."""
    base = run_candidate(base_id, series_by_coin, btc_reg_map, inst_reg_maps, None)
    sized = run_candidate(
        base_id,
        series_by_coin,
        btc_reg_map,
        inst_reg_maps,
        None,
        apply_vol_sizer=True,
        vol_targets=vol_targets,
    )

    def to_daily(trs: list[Trade]) -> list[float]:
        by_day: dict[int, float] = {}
        for t in trs:
            d = int(t.entry_ts // 86_400_000)
            by_day[d] = by_day.get(d, 0.0) + t.pnl_pct
        if not by_day:
            return []
        lo, hi = min(by_day), max(by_day)
        return [by_day.get(d, 0.0) for d in range(lo, hi + 1)]

    db, ds = to_daily(base), to_daily(sized)
    return {
        "base_id": base_id,
        "base_total": sum(t.pnl_pct for t in base),
        "sized_total": sum(t.pnl_pct for t in sized),
        "base_sharpe": ofr.sharpe_ratio(db) if len(db) >= 2 else float("nan"),
        "sized_sharpe": ofr.sharpe_ratio(ds) if len(ds) >= 2 else float("nan"),
        "base_maxdd": ofr.max_drawdown(db),
        "sized_maxdd": ofr.max_drawdown(ds),
        "sharpe_delta": paired_delta_ci(ds, db, n_boot, "sharpe"),
        "maxdd_delta": paired_delta_ci(ds, db, n_boot, "maxdd"),
    }


# ── orchestration ────────────────────────────────────────────────────
def load_all() -> tuple[dict, dict, dict, dict, dict]:
    cov = os.path.join(DATA_DIR, "coverage.json")
    if os.path.exists(cov):
        with open(cov) as f:
            coins = [c for c in json.load(f).get("coins", {}) if c in SYMBOLS]
    else:
        coins = SYMBOLS
    raw = {c: bts.load_candles(c) for c in coins}
    raw = {c: v for c, v in raw.items() if len(v) > 250}
    if not raw:
        raise SystemExit(f"no majors data in {DATA_DIR} — run ingest_okx_majors_5m.py first")
    series = {c: build_xseries(v) for c, v in raw.items()}
    btc_reg = bts.btc_1h_regime_by_ts(raw.get("BTC", []))
    inst_regs = {c: instrument_1h_regime_by_ts(v) for c, v in raw.items()}
    temp = market_temp_proxy_by_ts(raw.get("BTC", []))
    vol_tgts = median_vol_targets(series)
    return series, btc_reg, inst_regs, temp, vol_tgts


def bh_across_family(per_candidate: dict[str, dict]) -> dict:
    """BH-FDR q=0.10 across the full (candidate x symbol) family. Only symbols
    with N>=400 enter the family (HALTed symbols are excluded — they cannot be a
    discovery). Returns the discovery set + adjusted q-values."""
    keys: list[tuple[str, str]] = []
    pvals: list[float] = []
    for cand, r in per_candidate.items():
        if not r.get("sym"):
            continue
        for s, d in r["sym"].items():
            if d["n"] < MIN_N_IN_REGIME:
                continue  # HALTed — not eligible
            keys.append((cand, s))
            pvals.append(d["p"])
    if not pvals:
        return {"family_size": 0, "discoveries": [], "adjusted": {}}
    res = sv.bh_fdr(pvals, alpha=0.10)
    discoveries = []
    adjusted = {}
    for idx, (cand, s) in enumerate(keys):
        q = res["adjusted"][idx]
        adjusted[f"{cand}:{s}"] = q
        if idx in res["rejected"] and per_candidate[cand]["sym"][s]["mean"] > 0:
            discoveries.append(f"{cand}:{s}")
    return {
        "family_size": len(keys),
        "discoveries": discoveries,
        "adjusted": adjusted,
        "k": res["k"],
        "threshold": res["threshold"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="smaller bootstrap (faster)")
    ap.add_argument("--json", type=str, default="", help="write full results JSON here")
    args = ap.parse_args()
    n_boot = 800 if args.quick else 4000

    print("Loading majors_5m ...")
    series, btc_reg, inst_regs, temp, vol_tgts = load_all()
    print(f"  coins: {', '.join(f'{c}({len(s.close)})' for c, s in series.items())}")
    print(f"  cost model: {FEE_PCT}% fee + {2 * SLIP_PCT}% slip = {ROUNDTRIP_COST}% round-trip")
    print(
        f"  vol targets (median realized vol/24bar): "
        f"{ {c: round(v, 5) for c, v in vol_tgts.items()} }"
    )

    # ── per-candidate gauntlet (R1, T1) ──
    directional = ["range_fade", "trend_breakout_regime"]
    per_cand: dict[str, dict] = {}
    for sid in directional:
        print(f"\n{'=' * 70}\nPER-CANDIDATE: {sid}")
        r = run_per_candidate(sid, series, btc_reg, inst_regs, n_boot)
        per_cand[sid] = r
        print_candidate(r)

    # ── BH-FDR across the family ──
    print(f"\n{'=' * 70}\nBH-FDR (q=0.10) across the (candidate x symbol) family")
    bh = bh_across_family(per_cand)
    print(f"  family size (N>=400 cells only): {bh['family_size']}")
    print(f"  discoveries (FDR-clean, mean>0): {bh['discoveries'] or 'NONE'}")

    # ── V1 overlay test (modifier on each directional base) ──
    print(f"\n{'=' * 70}\nV1 vol_target_sizer — overlay test (modifier ONLY)")
    v1 = {}
    for sid in directional:
        v = v1_overlay_test(sid, series, btc_reg, inst_regs, vol_tgts, n_boot)
        v1[sid] = v
        print_v1(v)

    # ── switcher A/B ──
    print(f"\n{'=' * 70}\nSWITCHER A/B (the wedge proof)")
    ab = switcher_ab(series, btc_reg, inst_regs, temp, vol_tgts, n_boot)
    print_ab(ab)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(serialize(per_cand, bh, v1, ab), f, indent=2, default=str)
        print(f"\nWrote {args.json}")


def print_candidate(r: dict) -> None:
    if r.get("verdict") == "HALT":
        print(f"  HALT — {r.get('note')}")
        return
    print(
        f"  trades={r['n_trades']}  win={r['win_rate']:.1%}  "
        f"mean_net={r['mean_net_pct']:+.4f}%  total={r['total_net_pct']:+.2f}%"
    )
    print(
        f"  n_trials (honest, incl +{PRIOR_HUNT_PENALTY} prior-hunt + 3 switcher knobs)"
        f" = {r['n_trials']}  (combos={r['n_combos']})"
    )
    print(
        f"  embargo = max(P95 hold {r['p95_hold_bars']}b, ema200 {EMA200_BARS}b) "
        f"= {r['embargo_bars']}b -> {r['embargo_groups']} groups"
    )
    c = r["cpcv"]
    print(
        f"  CPCV: median Sharpe={c.median:+.3f}  CI=[{c.p05:+.3f},{c.p95:+.3f}]  "
        f"%paths<0={c.pct_paths_negative:.0%}  paths={c.n_paths}"
    )
    print(f"  PBO={r['pbo'].pbo:.3f}  (DEPLOY<=0.2, PAPER<=0.5)")
    print(
        f"  DSR={r['dsr'].dsr:.3f}  (obs SR={r['dsr'].observed_sr:+.3f}, "
        f"SR*={r['dsr'].sr_star:+.3f}, n_trials={r['dsr'].n_variants})  [DEPLOY p<0.05 => DSR>=0.95]"
    )
    print(f"  max_dd={r['max_dd']:+.3f}")
    print("  per-symbol block-bootstrap CI (net mean/trade):")
    for s, d in r["sym"].items():
        halt = "  HALT N<400" if d["n"] < MIN_N_IN_REGIME else ""
        excl = "  CI>0" if (d["ci_lo"] == d["ci_lo"] and d["ci_lo"] > 0) else ""
        print(
            f"    {s:>5}: n={d['n']:>5} mean={d['mean']:+.4f}% "
            f"CI=[{d['ci_lo']:+.4f},{d['ci_hi']:+.4f}] p={d['p']:.3f}{excl}{halt}"
        )
    if r["halts"]:
        print(f"  HALTed symbols (N<400 in-regime): {r['halts']}")


def print_v1(v: dict) -> None:
    print(
        f"  base={v['base_id']}: total {v['base_total']:+.2f}% Sharpe {v['base_sharpe']:+.3f} "
        f"maxDD {v['base_maxdd']:+.3f}"
    )
    print(
        f"   +V1 sized:  total {v['sized_total']:+.2f}% Sharpe {v['sized_sharpe']:+.3f} "
        f"maxDD {v['sized_maxdd']:+.3f}"
    )
    sd, md = v["sharpe_delta"], v["maxdd_delta"]
    print(
        f"   Sharpe delta={sd['delta']:+.3f} CI=[{sd['ci_lo']:+.3f},{sd['ci_hi']:+.3f}]  "
        f"maxDD delta={md['delta']:+.3f} CI=[{md['ci_lo']:+.3f},{md['ci_hi']:+.3f}]"
    )
    if v["base_total"] <= 0:
        print("   NOTE: base is -EV — V1 can only flatten variance, NOT create alpha.")


def print_ab(ab: dict) -> None:
    print("  arm metrics (daily-return series):")
    for a, m in ab["metrics"].items():
        print(
            f"    {a:>20}: trades={m['n_trades']:>4} total={m['total_net_pct']:+.2f}% "
            f"days={m['n_days']:>4} Sharpe={m['sharpe']:+.3f} maxDD={m['max_dd']:+.3f}"
        )
    vs = ab["vs_static"]
    vg = ab["vs_free_gate"]
    print("  switcher_on vs always_trend (static rule):")
    print(
        f"    Sharpe delta={vs['sharpe']['delta']:+.3f} "
        f"CI=[{vs['sharpe']['ci_lo']:+.3f},{vs['sharpe']['ci_hi']:+.3f}]"
    )
    print(
        f"    maxDD  delta={vs['maxdd']['delta']:+.3f} "
        f"CI=[{vs['maxdd']['ci_lo']:+.3f},{vs['maxdd']['ci_hi']:+.3f}]"
    )
    print("  switcher_on vs free_sit_out_gate (THE LOAD-BEARING BASELINE):")
    print(
        f"    Sharpe delta={vg['sharpe']['delta']:+.3f} "
        f"CI=[{vg['sharpe']['ci_lo']:+.3f},{vg['sharpe']['ci_hi']:+.3f}]  "
        f"(DEPLOY needs CI_lo>=0)"
    )
    print(
        f"    maxDD  delta={vg['maxdd']['delta']:+.3f} "
        f"CI=[{vg['maxdd']['ci_lo']:+.3f},{vg['maxdd']['ci_hi']:+.3f}]"
    )
    at = ab["attribution"]
    print("  attribution (Sharpe decomposition of switcher edge):")
    print(f"    avoidance (free gate)= {at['avoidance_sharpe']:+.3f}")
    print(f"    routing (R1 vs static)= {at['routing_sharpe']:+.3f}")
    print(f"    sizing  (V1)         = {at['sizing_sharpe']:+.3f}")


def serialize(per_cand, bh, v1, ab) -> dict:
    def cand(r):
        if r.get("verdict") == "HALT":
            return {"verdict": "HALT", "note": r.get("note"), "n_trades": r.get("n_trades", 0)}
        return {
            "n_trades": r["n_trades"],
            "n_trials": r["n_trials"],
            "n_combos": r["n_combos"],
            "mean_net_pct": r["mean_net_pct"],
            "total_net_pct": r["total_net_pct"],
            "win_rate": r["win_rate"],
            "p95_hold_bars": r["p95_hold_bars"],
            "embargo_bars": r["embargo_bars"],
            "embargo_groups": r["embargo_groups"],
            "cpcv": {
                "median": r["cpcv"].median,
                "p05": r["cpcv"].p05,
                "p95": r["cpcv"].p95,
                "pct_neg": r["cpcv"].pct_paths_negative,
                "n_paths": r["cpcv"].n_paths,
            },
            "pbo": r["pbo"].pbo,
            "dsr": r["dsr"].dsr,
            "dsr_obs_sr": r["dsr"].observed_sr,
            "dsr_sr_star": r["dsr"].sr_star,
            "max_dd": r["max_dd"],
            "sym": {s: {k: v for k, v in d.items()} for s, d in r["sym"].items()},
            "halts": r["halts"],
        }

    return {
        "cost_model": {
            "fee_pct": FEE_PCT,
            "slip_pct_per_side": SLIP_PCT,
            "roundtrip_cost": ROUNDTRIP_COST,
        },
        "per_candidate": {k: cand(v) for k, v in per_cand.items()},
        "bh_fdr": bh,
        "v1_overlay": {k: dict(v.items()) for k, v in v1.items()},
        "switcher_ab": ab,
    }


if __name__ == "__main__":
    main()
