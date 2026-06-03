#!/usr/bin/env python3
"""Strategy backtest harness — the VERDICT AUTHORITY for Sprint 31.

Pattern-C kill: this harness does NOT reimplement entry/exit. It calls the SAME
`strategies/` rules and the SAME `indicators.py` functions the LIVE bot calls, so
a backtest pass actually binds the live runner.

  - entry:   strategies.load_strategy(id).should_enter(features)   ← identical to live
  - features: built from indicators.py series (ema/rsi/adx/mfi/bb) — same code as
              indicators.compute_latest, just indexed per-bar (all causal)
  - exit:    strategies.<S>.exit_policy() simulated bar-by-bar
  - rigor:   overfitting_rigor.{cpcv_paths, pbo, worst_in_worst_out_pbo,
              deflated_sharpe_ratio, make_verdict}

Returns are net of a round-trip fee (default 0.20% OKX spot taker, spec §1).

Two gates are reported per strategy:
  • DEPLOY gate (quant-backtest-rigor skill): DSR>=0.95 AND PBO<0.20 AND %paths<0<25%.
  • §5 PAPER-CONTINUE gate (spec): DSR>0 AND PBO<0.5 AND fee-adj mean-return CI
    excludes 0 on >=3 symbols. A §5 pass keeps the live-PAPER process running; it
    is NOT a real-money green light.

Usage:
  uv run python contest_bot/backtest_strategy.py --strategy trend_breakout
  uv run python contest_bot/backtest_strategy.py --strategy mean_reversion
  uv run python contest_bot/backtest_strategy.py --both        # + orthogonality rho
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics as st
import sys
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_RIGOR = os.path.join(_HERE, "..", "scripts", "calibration")
if _RIGOR not in sys.path:
    sys.path.insert(0, _RIGOR)

import indicators as ind  # noqa: E402  same indicators the live bot uses
import overfitting_rigor as ofr  # noqa: E402
from strategies import load_strategy  # noqa: E402
from strategies.base import ExitPolicy  # noqa: E402
from strategies.spec import StrategySpec  # noqa: E402

DATA_DIR = os.path.join(_RIGOR, "data", "majors_5m")
BAR_MIN = 5
DEFAULT_FEE_PCT = 0.20  # OKX spot round-trip taker (spec §1)


# ── data + series ────────────────────────────────────────────────────
def load_candles(coin: str) -> list[dict]:
    path = os.path.join(DATA_DIR, f"{coin}.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


@dataclass
class Series:
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


def build_series(candles: list[dict]) -> Series:
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    vols = [c.get("volume", 0.0) for c in candles]
    adx_s, _, _ = ind.adx_full(highs, lows, closes, 14)
    bl, bm, _bu = ind.bb(closes, 20, 2.0)
    return Series(
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
    )


def btc_1h_regime_by_ts(btc_candles: list[dict]) -> dict[int, str]:
    """Map each BTC 5m bar ts (ms) → the most-recent CLOSED 1h regime.

    Resample 5m→1h, classify each 1h bar via the live compute_regime_1h over its
    trailing window, then assign every 5m bar the regime of the last fully-closed
    1h bar before it (causal — no look-ahead)."""
    if not btc_candles:
        return {}
    # bucket 5m bars into 1h OHLCV (3_600_000 ms)
    buckets: dict[int, list[dict]] = {}
    for c in btc_candles:
        h = int(c["ts"] // 3_600_000) * 3_600_000
        buckets.setdefault(h, []).append(c)
    hours = sorted(buckets)
    bars_1h = []
    for h in hours:
        rows = buckets[h]
        bars_1h.append(
            {
                "ts": h,
                "open": rows[0]["open"],
                "high": max(r["high"] for r in rows),
                "low": min(r["low"] for r in rows),
                "close": rows[-1]["close"],
                "volume": sum(r.get("volume", 0.0) for r in rows),
            }
        )
    # regime at the close of each 1h bar, from its trailing 60-bar window
    regime_at_hour: dict[int, str] = {}
    for k in range(len(bars_1h)):
        window = bars_1h[max(0, k - 60) : k + 1]
        regime_at_hour[bars_1h[k]["ts"]] = ind.compute_regime_1h(window)
    # assign each 5m ts the regime of the PREVIOUS closed hour
    out: dict[int, str] = {}
    for c in btc_candles:
        prev_hour = int(c["ts"] // 3_600_000) * 3_600_000 - 3_600_000
        out[int(c["ts"])] = regime_at_hour.get(prev_hour, "CHOP")
    return out


def features_at(s: Series, i: int, lookback: int, btc_reg: str) -> dict | None:
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
        "breakout_pct": breakout_pct,
        "donchian_break": s.close[i] > prior_high if prior_high > 0 else False,
        "btc_regime_1h": btc_reg,
        # S33 churn/noise — same window the live bot uses (causal, last ~25 closes)
        "churn_ratio": ind.churn_ratio(s.close[max(0, i - 24) : i + 1], 24),
        "reversal_rate": ind.reversal_rate(s.close[max(0, i - 24) : i + 1], 24),
    }


# ── exit simulation (drives off ExitPolicy; net of fee) ──────────────
def simulate_exit(
    s: Series, entry_idx: int, ep_pol: ExitPolicy, fee_pct: float
) -> tuple[float, int]:
    """Return (net_pnl_pct, exit_idx). Conservative: SL checked before TP intrabar."""
    ep = s.close[entry_idx]
    if ep <= 0:
        return 0.0, entry_idx
    peak = ep
    last_new_high = entry_idx
    n = len(s.close)
    sg_bars = (ep_pol.stall_green_age_min or 0) // BAR_MIN
    fs_nnh_bars = (ep_pol.flat_stall_no_new_high_min or 0) // BAR_MIN
    ts_bars = ep_pol.time_stop_min // BAR_MIN

    def net(gross: float) -> float:
        return gross - fee_pct

    for j in range(entry_idx + 1, n):
        hi, lo, cl = s.high[j], s.low[j], s.close[j]
        age = j - entry_idx
        if hi > peak:
            peak = hi
            last_new_high = j
        pnl = (cl - ep) / ep * 100
        peak_pct = (peak - ep) / ep * 100
        no_new_high = j - last_new_high
        # hard stop loss (conservative: before TP)
        if (lo - ep) / ep * 100 <= -ep_pol.sl_pct:
            return net(-ep_pol.sl_pct), j
        # take profit (intrabar touch)
        if (hi - ep) / ep * 100 >= ep_pol.tp_pct:
            return net(ep_pol.tp_pct), j
        # mean-reversion target: revert to the mid band
        if ep_pol.revert_to_mean and s.bb_mid[j] is not None and cl >= s.bb_mid[j]:
            return net(pnl), j
        # trailing stack
        if ep_pol.use_trailing:
            if ep_pol.trail_floor_pct and pnl <= -ep_pol.trail_floor_pct:
                return net(pnl), j
            if (
                ep_pol.trail_activate_pct > 0
                and peak_pct >= ep_pol.trail_activate_pct
                and (peak - cl) / peak * 100 >= ep_pol.trail_give_pct
            ):
                return net(pnl), j
        # stall-green
        if sg_bars and age >= sg_bars and pnl >= ep_pol.stall_green_min_pct:
            return net(pnl), j
        # flat-stall
        if (
            fs_nnh_bars
            and no_new_high >= fs_nnh_bars
            and ep_pol.flat_stall_lo <= pnl <= ep_pol.flat_stall_hi
        ):
            return net(pnl), j
        # time stop
        if age >= ts_bars:
            return net(pnl), j
    return net((s.close[-1] - ep) / ep * 100), n - 1


@dataclass
class Trade:
    symbol: str
    entry_ts: float
    exit_ts: float
    pnl_pct: float  # net of fee


def run_strategy(strategy_id, data, series_by_coin, btc_reg_map, spec, fee_pct) -> list[Trade]:
    strat = load_strategy(strategy_id, spec)
    pol = strat.exit_policy()
    lookback = int(strat.spec.entry_gates.get("donchian_lookback", 48))
    warmup = 210  # EMA200 + ADX warm-up
    trades: list[Trade] = []
    for coin, s in series_by_coin.items():
        n = len(s.close)
        i = warmup
        while i < n:
            btc_reg = btc_reg_map.get(int(s.ts[i]), "CHOP")
            feats = features_at(s, i, lookback, btc_reg)
            if feats is None:
                i += 1
                continue
            if strat.should_enter(feats) is not None:
                pnl, exit_idx = simulate_exit(s, i, pol, fee_pct)
                trades.append(Trade(coin, s.ts[i], s.ts[exit_idx], pnl))
                i = max(exit_idx + 1, i + 1)  # no overlap (one position per coin)
            else:
                i += 1
    return trades


# ── rigor ────────────────────────────────────────────────────────────
def bootstrap_ci(xs: list[float], n_boot: int = 5000, seed: int = 7) -> tuple[float, float]:
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = []
    n = len(xs)
    for _ in range(n_boot):
        means.append(sum(xs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return (means[int(0.025 * n_boot)], means[int(0.975 * n_boot)])


def time_group(ts: float, t0: float, t1: float, n_groups: int) -> int:
    if t1 <= t0:
        return 0
    g = int((ts - t0) / (t1 - t0) * n_groups)
    return min(max(g, 0), n_groups - 1)


def variant_grid(strategy_id: str) -> list[dict]:
    """Small honest sweep around the v0 centre (the n_trials for DSR)."""
    if strategy_id == "trend_breakout":
        grid = []
        for adx_min in (20.0, 22.0, 26.0):
            for rsi_max in (72.0, 75.0, 78.0):
                for brk in (0.4, 0.5, 0.6):
                    grid.append(
                        {"adx_min": adx_min, "rsi_max": rsi_max, "breakout_magnitude_min_pct": brk}
                    )
        return grid
    if strategy_id == "mean_reversion":
        grid = []
        for rsi_max in (28.0, 30.0, 32.0):
            for adx_max in (22.0, 25.0, 28.0):
                for mfi_max in (20.0, 25.0, 30.0):
                    grid.append({"rsi_max": rsi_max, "adx_max": adx_max, "mfi_max": mfi_max})
        return grid
    return [{}]


def spec_with(strategy_id: str, overrides: dict, base: StrategySpec | None = None):
    """Clone the base spec (default if None) and apply entry-gate overrides.
    Deep-clones via JSON so sweep iterations never mutate a shared base."""
    src = base if base is not None else load_strategy(strategy_id).spec
    spec = StrategySpec.from_json(src.to_json())
    spec.entry_gates.update(overrides)
    return spec


def analyze(strategy_id, data, series_by_coin, btc_reg_map, fee_pct, n_groups=8, n_periods=10, base_spec=None):
    base = load_strategy(strategy_id, base_spec)
    # ── v0 centre run (per-symbol CI + CPCV) ─────────────────────────
    v0_trades = run_strategy(strategy_id, data, series_by_coin, btc_reg_map, base.spec, fee_pct)
    all_ts = [t.entry_ts for t in v0_trades]
    if not all_ts:
        return {"strategy": strategy_id, "n_trades": 0, "verdict": None, "note": "0 trades"}
    t0, t1 = min(all_ts), max(all_ts)

    # per-symbol fee-adj mean-return CI
    by_sym: dict[str, list[float]] = {}
    for t in v0_trades:
        by_sym.setdefault(t.symbol, []).append(t.pnl_pct)
    sym_ci = {}
    sym_ci_excludes_0 = 0
    for sym, xs in by_sym.items():
        lo, hi = bootstrap_ci(xs)
        excl = (lo == lo) and (lo > 0 or hi < 0)
        sym_ci[sym] = {"n": len(xs), "mean": st.mean(xs), "ci": (lo, hi), "excl_0": excl}
        if excl and st.mean(xs) > 0:
            sym_ci_excludes_0 += 1

    # CPCV samples: (entry_group, ret, exit_group)
    samples = [
        (
            time_group(t.entry_ts, t0, t1, n_groups),
            t.pnl_pct,
            time_group(t.exit_ts, t0, t1, n_groups),
        )
        for t in v0_trades
    ]
    cpcv = ofr.cpcv_paths(samples, n_groups=n_groups, n_test=2, embargo_groups=1)

    # ── sweep for PBO + DSR (perf_matrix periods × variants) ─────────
    grid = variant_grid(strategy_id)
    variant_rets: list[list[float]] = []  # per-variant pooled returns (for DSR sharpes)
    perf = [[0.0 for _ in grid] for _ in range(n_periods)]
    for vi, ov in enumerate(grid):
        sweep_spec = spec_with(strategy_id, ov, base=base.spec)
        tr = run_strategy(strategy_id, data, series_by_coin, btc_reg_map, sweep_spec, fee_pct)
        variant_rets.append([t.pnl_pct for t in tr])
        # mean return per period
        bucket: dict[int, list[float]] = {}
        for t in tr:
            bucket.setdefault(time_group(t.entry_ts, t0, t1, n_periods), []).append(t.pnl_pct)
        for p in range(n_periods):
            perf[p][vi] = st.mean(bucket[p]) if bucket.get(p) else 0.0

    pbo_res = ofr.pbo(perf, n_partitions=min(n_periods, 10))
    avoid_pbo = ofr.worst_in_worst_out_pbo(perf, n_partitions=min(n_periods, 10))

    variant_sharpes = [ofr.sharpe_ratio(r) if len(r) >= 2 else 0.0 for r in variant_rets]
    v0_rets = [t.pnl_pct for t in v0_trades]
    dsr_res = ofr.deflated_sharpe_ratio(v0_rets, variant_sharpes)

    mdd = ofr.max_drawdown(v0_rets)
    total = sum(v0_rets)
    calmar = (total / abs(mdd)) if mdd < 0 else float("inf") if total > 0 else 0.0

    verdict = ofr.make_verdict(strategy_id, cpcv, dsr_res, pbo_res, mdd, calmar)

    # §5 PAPER-CONTINUE gate (spec): DSR>0 AND PBO<0.5 AND >=3 symbols CI excl 0
    s5_pass = (dsr_res.dsr > 0) and (pbo_res.pbo < 0.5) and (sym_ci_excludes_0 >= 3)

    return {
        "strategy": strategy_id,
        "n_trades": len(v0_trades),
        "n_variants": len(grid),
        "fee_pct": fee_pct,
        "mean_net_pct": st.mean(v0_rets),
        "total_net_pct": total,
        "win_rate": sum(1 for r in v0_rets if r > 0) / len(v0_rets),
        "sym_ci": sym_ci,
        "sym_ci_excludes_0": sym_ci_excludes_0,
        "cpcv": cpcv,
        "pbo": pbo_res,
        "avoid_pbo": avoid_pbo,
        "dsr": dsr_res,
        "verdict": verdict,
        "s5_paper_continue": s5_pass,
        "trades": v0_trades,
    }


def print_report(r: dict) -> None:
    sid = r["strategy"]
    print(f"\n{'=' * 64}\nSTRATEGY: {sid}")
    if not r.get("verdict"):
        print(f"  {r.get('note', 'no result')}")
        return
    print(
        f"  trades={r['n_trades']}  win_rate={r['win_rate']:.1%}  "
        f"mean_net={r['mean_net_pct']:+.3f}%  total_net={r['total_net_pct']:+.2f}%  "
        f"(fee {r['fee_pct']:.2f}% RT, {r['n_variants']} variants)"
    )
    print("  per-symbol fee-adj mean (95% CI):")
    for sym, d in r["sym_ci"].items():
        lo, hi = d["ci"]
        flag = "  ← excl 0" if d["excl_0"] else ""
        print(f"    {sym:>5}: n={d['n']:>4} mean={d['mean']:+.3f}% CI=[{lo:+.3f},{hi:+.3f}]{flag}")
    print(f"  symbols with CI excluding 0 (and >0): {r['sym_ci_excludes_0']}")
    print(f"  avoidance-PBO (regime-gate exclusion): {r['avoid_pbo'].pbo:.3f}")
    print()
    print(r["verdict"].render())
    print(
        f"\n  §5 PAPER-CONTINUE gate: "
        f"{'PASS' if r['s5_paper_continue'] else 'FAIL'} "
        f"(DSR>{0}:{r['dsr'].dsr > 0}, PBO<0.5:{r['pbo'].pbo < 0.5}, "
        f">=3 sym CI>0:{r['sym_ci_excludes_0'] >= 3})"
        "  [NOTE: PAPER-CONTINUE only — NOT a real-money green light]"
    )


def orthogonality_rho(ra: dict, rb: dict, n_bins: int = 60) -> float | None:
    """Realised correlation of A's and B's per-bin net PnL (spec §2 target |rho|<0.3)."""
    ta, tb = ra.get("trades"), rb.get("trades")
    if not ta or not tb:
        return None
    all_ts = [t.entry_ts for t in ta] + [t.entry_ts for t in tb]
    t0, t1 = min(all_ts), max(all_ts)

    def binned(trs):
        b = [0.0] * n_bins
        for t in trs:
            b[time_group(t.entry_ts, t0, t1, n_bins)] += t.pnl_pct
        return b

    a, b = binned(ta), binned(tb)
    if len(a) < 2 or st.pstdev(a) == 0 or st.pstdev(b) == 0:
        return None
    ma, mb = st.mean(a), st.mean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=False)) / len(a)
    return cov / (st.pstdev(a) * st.pstdev(b))


# ── API surface (Phase 1: POST /backtest) ────────────────────────────
def verdict_envelope(r: dict) -> dict:
    """Convert an analyze() result into a JSON-serializable verdict envelope —
    the contract the app's Strategy Forge renders as a verdict card."""
    if not r.get("verdict"):
        return {"strategy_id": r.get("strategy"), "n_trades": r.get("n_trades", 0),
                "verdict": None, "note": r.get("note", "no trades")}
    v, cpcv, pbo, dsr = r["verdict"], r["cpcv"], r["pbo"], r["dsr"]
    return {
        "strategy_id": r["strategy"],
        "verdict": v.verdict,  # DEPLOY | PAPER ONLY | REJECT
        "s5_paper_continue": r["s5_paper_continue"],
        "rationale": list(v.rationale),
        "n_trades": r["n_trades"],
        "n_variants": r["n_variants"],
        "fee_pct": r["fee_pct"],
        "win_rate": round(r["win_rate"], 4),
        "mean_net_pct": round(r["mean_net_pct"], 4),
        "total_net_pct": round(r["total_net_pct"], 3),
        "rigor": {
            "cpcv_median_sharpe": round(cpcv.median, 4),
            "cpcv_ci": [round(cpcv.p05, 4), round(cpcv.p95, 4)],
            "cpcv_pct_paths_negative": round(cpcv.pct_paths_negative, 4),
            "pbo": round(pbo.pbo, 4),
            "avoidance_pbo": round(r["avoid_pbo"].pbo, 4),
            "dsr": round(dsr.dsr, 4),
        },
        "per_symbol": {
            sym: {"n": d["n"], "mean_net_pct": round(d["mean"], 4),
                  "ci": [round(d["ci"][0], 4), round(d["ci"][1], 4)], "ci_excludes_0": d["excl_0"]}
            for sym, d in r["sym_ci"].items()
        },
        "symbols_ci_excludes_0": r["sym_ci_excludes_0"],
    }


def run_backtest(
    strategy_id: str = "trend_breakout",
    entry_gates: dict | None = None,
    exit_overrides: dict | None = None,
    coins: list[str] | None = None,
    fee_pct: float = DEFAULT_FEE_PCT,
    both: bool = False,
) -> dict:
    """Run the rigor backtest for a StrategySpec and return a JSON envelope.

    This is the Phase-1 API core: the app POSTs a strategy_id + gate/exit
    overrides; we run the SAME harness the live bot's rules bind to, and return
    the verdict card. `both=True` adds the orthogonality ρ of trend vs meanrev.
    Raises ValueError if the majors data isn't ingested yet.
    """
    cov_path = os.path.join(DATA_DIR, "coverage.json")
    if coins:
        want = [c.strip().upper() for c in coins]
    elif os.path.exists(cov_path):
        with open(cov_path) as f:
            want = list(json.load(f).get("coins", {}))
    else:
        want = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    data = {c: load_candles(c) for c in want}
    data = {c: v for c, v in data.items() if len(v) > 250}
    if not data:
        raise ValueError(f"no majors data in {DATA_DIR} — run ingest_okx_majors_5m.py first")
    series = {c: build_series(v) for c, v in data.items()}
    btc_reg = btc_1h_regime_by_ts(data.get("BTC", []))

    targets = ["trend_breakout", "mean_reversion"] if both else [strategy_id]
    results = {}
    envelopes = []
    for sid in targets:
        # only the requested strategy receives the caller's overrides (cloned base)
        base_spec = None
        if sid == strategy_id and (entry_gates or exit_overrides):
            base_spec = StrategySpec.from_json(load_strategy(sid).spec.to_json())
            if entry_gates:
                base_spec.entry_gates.update(entry_gates)
            if exit_overrides:
                base_spec.exit.update(exit_overrides)
        r = analyze(sid, data, series, btc_reg, fee_pct, base_spec=base_spec)
        results[sid] = r
        envelopes.append(verdict_envelope(r))

    out: dict = {"coins": list(data), "fee_pct": fee_pct, "strategies": envelopes}
    if both:
        rho = orthogonality_rho(results["trend_breakout"], results["mean_reversion"])
        out["orthogonality_rho"] = round(rho, 4) if rho is not None else None
    return out


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--strategy", choices=["trend_breakout", "mean_reversion"], default="trend_breakout"
    )
    ap.add_argument("--both", action="store_true", help="run both + orthogonality rho")
    ap.add_argument(
        "--fee", type=float, default=DEFAULT_FEE_PCT, help="round-trip fee %% (default 0.20)"
    )
    ap.add_argument(
        "--coins", type=str, default="", help="override coins (default: coverage manifest)"
    )
    args = ap.parse_args()

    cov_path = os.path.join(DATA_DIR, "coverage.json")
    if args.coins:
        coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    elif os.path.exists(cov_path):
        with open(cov_path) as f:
            coins = list(json.load(f).get("coins", {}))
    else:
        coins = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

    data = {c: load_candles(c) for c in coins}
    data = {c: v for c, v in data.items() if len(v) > 250}
    if not data:
        print(f"No usable data in {DATA_DIR}. Run ingest_okx_majors_5m.py first.")
        return
    print(f"Loaded {len(data)} coins: {', '.join(f'{c}({len(v)})' for c, v in data.items())}")
    series = {c: build_series(v) for c, v in data.items()}
    btc_reg = btc_1h_regime_by_ts(data.get("BTC", []))

    targets = ["trend_breakout", "mean_reversion"] if args.both else [args.strategy]
    results = {}
    for sid in targets:
        results[sid] = analyze(sid, data, series, btc_reg, args.fee)
        print_report(results[sid])

    if args.both:
        rho = orthogonality_rho(results["trend_breakout"], results["mean_reversion"])
        print(
            f"\n{'=' * 64}\nORTHOGONALITY: rho(A_pnl, B_pnl) = {rho:+.3f} (target |rho|<0.3)"
            if rho is not None
            else "\nORTHOGONALITY: n/a"
        )


if __name__ == "__main__":
    _cli()
