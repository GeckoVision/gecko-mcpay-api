#!/usr/bin/env python3
"""Exit reconciliation — binary TP/SL vs the bot's REAL close-based exit stack.

Phase 0.5 of the market-analysis roadmap (2026-05-22, quant-analyst).

THE QUESTION
  The TP2/SL3 calibration (`tp_regime_validation.py`, `chart_floor_calibration.py`)
  concludes the strategy is net -EV (needs ~75% win-rate, gross edge ~1/7 of a fee).
  BUT the live realized exits (N=7) show a 3.6:1 payoff (avg win +2.9% vs avg loss
  -0.81%, break-even ~22%, win-rate 57%). These DISAGREE ON SIGN.

  Hypothesis: the calibration's exit model does not match the bot's ACTUAL exit
  stack, and the real (trailing / stall / close-based) exits already carry a small
  edge the -EV read hides.

WHAT THIS SETTLES
  1. Transcribe + implement the bot's REAL exit stack faithfully:
       - poll-driven on the CLOSE price each bar (the live bot reads the 30s spot,
         NOT intrabar high/low). This is the single biggest fidelity gap: the base
         harness fires SL/TP on intrabar wick touch; the live bot only ever sees a
         close, so a -3% wick that recovers does NOT stop the live bot out.
       - LIVE params: TP +2 / SL -3 / trail(activate +1, give-back 1) /
         stall_green(>=60min & >=+1% -> close) / flat_stall(>=90min, -0.5..+2,
         no-new-high 30min -> close). NO 12h time-stop fires in the live poll loop
         (it only computes a dashboard ETA), so we DO NOT apply one here.
       - exit-check ORDER mirrors the live loop: trail -> SL -> TP -> stall_green
         -> flat_stall.
  2. Keep the BINARY TP2/SL3 model (intrabar, the base study's implicit read) for
     a side-by-side.
  3. Re-run regime-partitioned net-EV for BOTH exit models, with a MOVING-BLOCK
     bootstrap CI (autocorrelation -> effective-N << raw-N), block length 3.
  4. Reconcile against the live N=7.

READ-ONLY w.r.t. the live bot. Reuses chart_floor_calibration's faithful
candidate detection, regime, enrichment, and the bot's own indicators module.

Usage:
    python3 scripts/calibration/exit_reconciliation.py --cached /tmp/cal_candles_d1.json
    python3 scripts/calibration/exit_reconciliation.py            # fetches live (read-only HTTP)
    python3 scripts/calibration/exit_reconciliation.py --cached ... --json-out out.json
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
sys.path.insert(0, _HERE)

import chart_floor_calibration as base  # noqa: E402  faithful base study

# ── Fee model (same band as tp_regime_validation) ───────────────────
FEE_RT_BAND = [0.5, 0.75, 1.0]
FEE_RT_CENTRAL = 0.75

# ── LIVE exit params (transcribed from the bot, 2026-05-22) ──────────
# Source: contest_bot/jto_breakout_gecko_gated_contest_bot.py lines 96-114 +
# the monitor_positions() poll loop lines 1575-1631.
LIVE_TP_PCT = 2.0
LIVE_SL_PCT = 3.0
LIVE_TRAIL_STOP_PCT = 1.0
LIVE_TRAIL_ACTIVATE_PCT = 1.0
LIVE_STALL_GREEN_AGE_BARS = 12  # 60 min / 5m
LIVE_STALL_GREEN_MIN_PCT = 1.0
LIVE_FLAT_STALL_AGE_BARS = 18  # 90 min / 5m
LIVE_FLAT_STALL_LO, LIVE_FLAT_STALL_HI = -0.5, 2.0
LIVE_FLAT_STALL_NO_NEW_HIGH_BARS = 6  # 30 min / 5m
# NB: NO live time-stop fires in the poll loop (only a dashboard ETA is computed).

# Binary baseline params (the base study's implicit read).
BIN_TP_PCT = 2.0
BIN_SL_PCT = 3.0

# ── Block-bootstrap config ──────────────────────────────────────────
N_BOOTSTRAP = 5000
RNG_SEED = 1729
BLOCK_LEN = 3  # lag-1 autocorr ~0.36, ~0 by lag-3; N^(1/3)~5.6 but short block
#                preserves resampling diversity at small per-regime N.


# ── Exit model A: REAL close-based live stack ───────────────────────
def simulate_exit_real_close(c: dict, entry_idx: int) -> float:
    """Faithful replica of the live bot's monitor_positions() poll loop.

    Evaluates exits on the CLOSE price of each forward bar (the live bot polls
    the 30s spot, never intrabar high/low). Trail uses the running peak of CLOSES
    (the live bot tracks peak from polled spot prices, not candle highs). Order
    of checks mirrors the live loop: trail -> SL -> TP -> stall_green ->
    flat_stall. Returns realized pnl_pct at exit; marks to last close if no exit
    fires within the window.
    """
    ep = c["close"][entry_idx]
    if ep <= 0:
        return 0.0
    peak = ep  # peak of CLOSES (live bot's peak_price is updated from polled spot)
    last_new_high_bar = entry_idx
    n = len(c["close"])
    for j in range(entry_idx + 1, n):
        cl = c["close"][j]
        age = j - entry_idx
        if cl >= peak:
            peak = cl
            last_new_high_bar = j
        pnl = (cl - ep) / ep * 100
        peak_pct = (peak - ep) / ep * 100
        no_new_high = j - last_new_high_bar
        # 1. Trail (checked FIRST in the live loop)
        if peak_pct >= LIVE_TRAIL_ACTIVATE_PCT:
            trail = (peak - cl) / peak * 100 if peak else 0.0
            if trail >= LIVE_TRAIL_STOP_PCT:
                return pnl
        # 2. Stop loss (close-based, NOT intrabar)
        if pnl <= -LIVE_SL_PCT:
            return pnl
        # 3. Take profit (close-based)
        if pnl >= LIVE_TP_PCT:
            return pnl
        # 4. Stall green
        if age >= LIVE_STALL_GREEN_AGE_BARS and pnl >= LIVE_STALL_GREEN_MIN_PCT:
            return pnl
        # 5. Flat stall
        if (
            age >= LIVE_FLAT_STALL_AGE_BARS
            and LIVE_FLAT_STALL_LO <= pnl <= LIVE_FLAT_STALL_HI
            and no_new_high >= LIVE_FLAT_STALL_NO_NEW_HIGH_BARS
        ):
            return pnl
        # (no live time-stop)
    return (c["close"][-1] - ep) / ep * 100


# ── Exit model B: BINARY TP2/SL3 (intrabar, the base study's read) ──
def simulate_exit_binary(c: dict, entry_idx: int) -> float:
    """Pure binary TP/SL: first intrabar touch of +TP or -SL wins/loses. No trail,
    no stall. This is the model whose `won_at`/`breakeven_winrate` framing produced
    the '-EV, needs 75% win-rate' headline. Conservative SL-before-TP on straddle."""
    ep = c["close"][entry_idx]
    if ep <= 0:
        return 0.0
    n = len(c["close"])
    for j in range(entry_idx + 1, n):
        hi, lo = c["high"][j], c["low"][j]
        if (lo - ep) / ep * 100 <= -BIN_SL_PCT:
            return -BIN_SL_PCT
        if (hi - ep) / ep * 100 >= BIN_TP_PCT:
            return BIN_TP_PCT
    return (c["close"][-1] - ep) / ep * 100


# ── Candidate collection (faithful gate; both exits + ordered series) ─
@dataclass
class Cand:
    sym: str
    idx: int
    regime: str
    proxy_conf: float
    chart_bullish: bool
    pnl_real: float  # realized gross pnl%, REAL close-based exit
    pnl_bin: float  # realized gross pnl%, BINARY TP2/SL3 exit


def collect(data: dict[str, dict]) -> list[Cand]:
    """Collect candidates in time order WITHIN each symbol (block bootstrap needs
    the within-symbol ordering preserved)."""
    out: list[Cand] = []
    for sym, c in data.items():
        n = len(c["close"])
        i = base.WARMUP
        while i < n:
            if (
                base.breakout_fires(c, i) or base.volume_spike_fires(c, i)
            ) and base.has_full_horizon(c, i):
                out.append(
                    Cand(
                        sym=sym,
                        idx=i,
                        regime=base.regime_at(c, i),
                        proxy_conf=base.chart_confidence_proxy(c, i),
                        chart_bullish=base.chart_verdict_bullish(c, i),
                        pnl_real=simulate_exit_real_close(c, i),
                        pnl_bin=simulate_exit_binary(c, i),
                    )
                )
                i += 6
            else:
                i += 1
    return out


# ── Moving-block bootstrap CI ───────────────────────────────────────
def _autocorr(x: list[float], lag: int) -> float:
    n = len(x)
    if n <= lag + 2:
        return 0.0
    m = st.mean(x)
    var = sum((v - m) ** 2 for v in x)
    if var == 0:
        return 0.0
    return sum((x[t] - m) * (x[t - lag] - m) for t in range(lag, n)) / var


def variance_inflation(series_list: list[list[float]], k_max: int = 4) -> float:
    """Bartlett-weighted variance-inflation factor from within-symbol autocorr.
    VIF = 1 + 2 * sum_{k=1}^{K} (1 - k/(K+1)) * rho_k  (rho averaged over symbols,
    n-weighted). N_eff = N / VIF."""
    vif = 1.0
    for k in range(1, k_max + 1):
        num = den = 0.0
        for s in series_list:
            if len(s) > k + 2:
                num += _autocorr(s, k) * len(s)
                den += len(s)
        rho = num / den if den else 0.0
        vif += 2 * (1 - k / (k_max + 1)) * rho
    return max(vif, 1.0)


def block_bootstrap_ci(
    series_list: list[list[float]],
    block: int = BLOCK_LEN,
    n_boot: int = N_BOOTSTRAP,
    alpha: float = 0.05,
):
    """Moving-block bootstrap of the MEAN over a set of per-symbol ordered series.

    Each resample draws overlapping blocks of length `block` (sampled with random
    start within each symbol's series) until it has >= the original total count,
    then truncates. Blocks are drawn proportionally to symbol length so the
    resample's symbol mix matches the data. Preserves within-symbol serial
    dependence; returns (point, lo, hi).
    """
    flat = [v for s in series_list for v in s]
    if not flat:
        return (float("nan"),) * 3
    point = st.mean(flat)
    if len(flat) == 1:
        return (point, point, point)
    rng = random.Random(RNG_SEED)
    total = len(flat)
    # weighted symbol pick proportional to length, only symbols long enough
    usable = [s for s in series_list if len(s) >= 1]
    weights = [len(s) for s in usable]
    boots: list[float] = []
    for _ in range(n_boot):
        sample: list[float] = []
        while len(sample) < total:
            s = rng.choices(usable, weights=weights, k=1)[0]
            b = min(block, len(s))
            start = rng.randrange(0, len(s) - b + 1)
            sample.extend(s[start : start + b])
        boots.append(st.mean(sample[:total]))
    boots.sort()
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[int((1 - alpha / 2) * n_boot)]
    return (point, lo, hi)


def iid_bootstrap_ci(vals: list[float], n_boot: int = N_BOOTSTRAP, alpha: float = 0.05):
    """IID bootstrap of the mean (the base study's method) — for the side-by-side
    'how much wider does block make it' check."""
    if not vals:
        return (float("nan"),) * 3
    point = st.mean(vals)
    if len(vals) == 1:
        return (point, point, point)
    rng = random.Random(RNG_SEED)
    m = len(vals)
    boots = [st.mean([vals[rng.randrange(m)] for _ in range(m)]) for _ in range(n_boot)]
    boots.sort()
    return (point, boots[int((alpha / 2) * n_boot)], boots[int((1 - alpha / 2) * n_boot)])


# ── Per-regime reconciliation table ─────────────────────────────────
def regime_series(cands: list[Cand], regime: str | None, key: str) -> list[list[float]]:
    """Per-symbol ordered net-of-central-fee series for one regime (or all)."""
    by_sym: dict[str, list[float]] = {}
    for cand in cands:
        if regime and cand.regime != regime:
            continue
        by_sym.setdefault(cand.sym, []).append(getattr(cand, key) - FEE_RT_CENTRAL)
    return list(by_sym.values())


def regime_series_gross(cands: list[Cand], regime: str | None, key: str) -> list[list[float]]:
    by_sym: dict[str, list[float]] = {}
    for cand in cands:
        if regime and cand.regime != regime:
            continue
        by_sym.setdefault(cand.sym, []).append(getattr(cand, key))
    return list(by_sym.values())


def describe(series_list: list[list[float]]) -> dict:
    flat = [v for s in series_list for v in s]
    if not flat:
        return {"n": 0}
    wins = [x for x in flat if x > 0]
    losses = [x for x in flat if x < 0]
    return {
        "n": len(flat),
        "mean": st.mean(flat),
        "n_win": len(wins),
        "n_loss": len(losses),
        "avg_win": st.mean(wins) if wins else 0.0,
        "avg_loss": st.mean(losses) if losses else 0.0,
        "win_rate": len(wins) / len(flat),
        "payoff": (st.mean(wins) / abs(st.mean(losses))) if (wins and losses) else float("nan"),
    }


def print_reconciliation(cands: list[Cand]) -> dict:
    out: dict = {}
    regimes = [
        (None, "ALL"),
        ("trend", "TREND"),
        ("transitional", "TRANSITIONAL"),
        ("chop", "CHOP"),
    ]
    print(f"\n{'=' * 100}")
    print("EXIT RECONCILIATION — BINARY TP2/SL3  vs  REAL close-based stack  (net of 0.75% RT fee)")
    print(f"{'=' * 100}")
    print(
        f"  block-bootstrap: block={BLOCK_LEN}, n_boot={N_BOOTSTRAP}, 95% CI.  N_eff = N / VIF (Bartlett K=4).\n"
    )
    hdr = (
        f"{'regime':>13} {'N':>4} {'Neff':>5} | "
        f"{'BIN netEV%':>10} {'BIN 95%CI(block)':>20} {'excl0':>5} | "
        f"{'REAL netEV%':>11} {'REAL 95%CI(block)':>20} {'excl0':>5}"
    )
    print(hdr)
    print("-" * len(hdr))
    for rg, label in regimes:
        gross_real = regime_series_gross(cands, rg, "pnl_real")
        vif = variance_inflation(gross_real)
        net_bin = regime_series(cands, rg, "pnl_bin")
        net_real = regime_series(cands, rg, "pnl_real")
        n = sum(len(s) for s in net_real)
        neff = n / vif if vif else n
        bpt, blo, bhi = block_bootstrap_ci(net_bin)
        rpt, rlo, rhi = block_bootstrap_ci(net_real)
        bexcl = "YES" if (blo > 0 or bhi < 0) else "no"
        rexcl = "YES" if (rlo > 0 or rhi < 0) else "no"
        print(
            f"{label:>13} {n:>4} {neff:>5.0f} | "
            f"{bpt:>+10.3f} [{blo:>+6.3f},{bhi:>+6.3f}] {bexcl:>5} | "
            f"{rpt:>+11.3f} [{rlo:>+6.3f},{rhi:>+6.3f}] {rexcl:>5}"
        )
        out[label] = {
            "n": n,
            "vif": vif,
            "n_eff": neff,
            "binary": {"net_ev": bpt, "ci": [blo, bhi], "excl_zero": bexcl == "YES"},
            "real": {"net_ev": rpt, "ci": [rlo, rhi], "excl_zero": rexcl == "YES"},
        }
    return out


def print_gross_and_shape(cands: list[Cand]) -> dict:
    """Per-regime GROSS mean + win-rate + payoff for both exit models (the 'shape'
    that the binary read collapses)."""
    out: dict = {}
    print(f"\n{'=' * 100}")
    print("EXIT SHAPE — GROSS (pre-fee) realized distribution, per regime")
    print(f"{'=' * 100}")
    hdr = (
        f"{'regime':>13} {'model':>6} {'N':>4} | {'grossEV%':>9} | "
        f"{'win%':>5} {'avgWin%':>8} {'avgLoss%':>9} {'payoff':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for rg, label in [
        (None, "ALL"),
        ("trend", "TREND"),
        ("transitional", "TRANS"),
        ("chop", "CHOP"),
    ]:
        d_bin = describe(regime_series_gross(cands, rg, "pnl_bin"))
        d_real = describe(regime_series_gross(cands, rg, "pnl_real"))
        for model, d in (("BIN", d_bin), ("REAL", d_real)):
            if d["n"] == 0:
                continue
            print(
                f"{label:>13} {model:>6} {d['n']:>4} | {d['mean']:>+8.3f}% | "
                f"{d['win_rate'] * 100:>4.0f}% {d['avg_win']:>+7.3f}% {d['avg_loss']:>+8.3f}% "
                f"{d['payoff']:>7.2f}"
            )
        out[label] = {"binary": d_bin, "real": d_real}
    return out


def print_iid_vs_block(cands: list[Cand]) -> None:
    """Show how much the block bootstrap widens the CI vs IID, for the ALL pool,
    REAL exit — the methodological honesty check."""
    net_real_flat = [v for s in regime_series(cands, None, "pnl_real") for v in s]
    net_real_series = regime_series(cands, None, "pnl_real")
    _ipt, ilo, ihi = iid_bootstrap_ci(net_real_flat)
    _bpt, blo, bhi = block_bootstrap_ci(net_real_series)
    print(f"\n{'=' * 100}")
    print("METHOD CHECK — IID vs MOVING-BLOCK bootstrap (ALL regimes, REAL exit, net of fee)")
    print(f"{'=' * 100}")
    print(f"  IID    95% CI: [{ilo:+.3f}, {ihi:+.3f}]  width={ihi - ilo:.3f}")
    print(f"  BLOCK  95% CI: [{blo:+.3f}, {bhi:+.3f}]  width={bhi - blo:.3f}")
    print(
        f"  block/IID width ratio = {(bhi - blo) / (ihi - ilo):.2f}x  (>1 confirms autocorr inflates variance)"
    )


# ── Live N=7 reconciliation ─────────────────────────────────────────
LIVE_EXITS = [
    # (ts, symbol, reason, pnl_pct) — from contest_bot/artifact_2026052*.jsonl
    ("2026-05-20T11:37", "MEW", "trailing_stop", -0.97),
    ("2026-05-20T11:57", "RAY", "trailing_stop", 1.39),
    ("2026-05-20T15:42", "PYTH", "trailing_stop", 1.93),
    ("2026-05-20T23:37", "PYTH", "stall_green_exit", 2.08),
    ("2026-05-21T00:54", "WIF", "take_profit", 6.21),
    ("2026-05-21T08:48", "DRIFT", "flat_stall_exit", -0.40),
    ("2026-05-22T03:41", "BOME", "flat_stall_exit", -1.06),
]


def reconcile_live(cands: list[Cand]) -> dict:
    pnl = [x[3] for x in LIVE_EXITS]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]
    live = {
        "n": len(pnl),
        "win_rate": len(wins) / len(pnl),
        "avg_win": st.mean(wins),
        "avg_loss": st.mean(losses),
        "payoff": st.mean(wins) / abs(st.mean(losses)),
        "mean_gross": st.mean(pnl),
    }
    # backtest REAL exit, ALL regimes, GROSS (live pnl is pre-fee oracle/paper read)
    real_flat = [v for s in regime_series_gross(cands, None, "pnl_real") for v in s]
    rw = [x for x in real_flat if x > 0]
    rl = [x for x in real_flat if x < 0]
    bt = {
        "n": len(real_flat),
        "win_rate": len(rw) / len(real_flat),
        "avg_win": st.mean(rw) if rw else 0.0,
        "avg_loss": st.mean(rl) if rl else 0.0,
        "payoff": (st.mean(rw) / abs(st.mean(rl))) if (rw and rl) else float("nan"),
        "mean_gross": st.mean(real_flat),
    }
    print(f"\n{'=' * 100}")
    print("LIVE N=7 RECONCILIATION — do the REAL-exit backtest stats reproduce the live shape?")
    print(f"{'=' * 100}")
    print(f"  {'metric':>16} | {'LIVE (N=7)':>12} | {'BACKTEST real-exit':>20}")
    print(f"  {'-' * 16} | {'-' * 12} | {'-' * 20}")
    print(f"  {'win-rate':>16} | {live['win_rate'] * 100:>11.1f}% | {bt['win_rate'] * 100:>19.1f}%")
    print(f"  {'avg win %':>16} | {live['avg_win']:>+11.2f}% | {bt['avg_win']:>+19.2f}%")
    print(f"  {'avg loss %':>16} | {live['avg_loss']:>+11.2f}% | {bt['avg_loss']:>+19.2f}%")
    print(f"  {'payoff ratio':>16} | {live['payoff']:>11.2f} | {bt['payoff']:>19.2f}")
    print(f"  {'mean gross %':>16} | {live['mean_gross']:>+11.3f}% | {bt['mean_gross']:>+19.3f}%")
    return {"live": live, "backtest_real": bt}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", help="load raw candles from JSON")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    if args.cached:
        with open(args.cached) as f:
            raw = json.load(f)
        print(f"Loaded cached candles from {args.cached}", file=sys.stderr)
    else:
        raw = base.fetch_candles()

    data = {sym: base.enrich(cs) for sym, cs in raw.items() if len(cs) >= 60}
    base.print_window_summary(data)
    cands = collect(data)
    print(f"\nTotal candidates (deterministic gate, full-horizon): {len(cands)}")

    shape = print_gross_and_shape(cands)
    recon = print_reconciliation(cands)
    print_iid_vs_block(cands)
    live = reconcile_live(cands)

    if args.json_out:
        out = {
            "generated": "2026-05-22",
            "fee_central": FEE_RT_CENTRAL,
            "fee_band": FEE_RT_BAND,
            "block_len": BLOCK_LEN,
            "n_bootstrap": N_BOOTSTRAP,
            "live_params": {
                "tp": LIVE_TP_PCT,
                "sl": LIVE_SL_PCT,
                "trail_activate": LIVE_TRAIL_ACTIVATE_PCT,
                "trail_give": LIVE_TRAIL_STOP_PCT,
                "stall_green_min": LIVE_STALL_GREEN_MIN_PCT,
                "flat_stall_band": [LIVE_FLAT_STALL_LO, LIVE_FLAT_STALL_HI],
            },
            "n_candidates": len(cands),
            "shape": shape,
            "reconciliation": recon,
            "live": live,
        }
        with open(args.json_out, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\nWrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
