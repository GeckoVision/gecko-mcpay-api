#!/usr/bin/env python3
"""Phase S52 — Experiment 1: longer-hold gross-EV-vs-horizon (quant-analyst, 2026-05-24).

THE QUESTION
  Per-token directional patterns (breakout, ICT) tested with SHORT holds were
  3 nulls — the fee (0.04-0.75%) dwarfed the captured move. Hypothesis: extend
  the HOLD so a bigger move accrues and gross EV clears 2x fees.

      "A 6%-class move over days dwarfs a 0.04-0.75% fee."

  This sweeps hold HORIZONS on the SAME entry candidates and asks, per horizon:
    1. gross EV per regime,
    2. fee sensitivity (does net EV clear the 2x-fee bar CI-clean?),
    3. does gross EV scale with hold length?
  Then runs the full López de Prado rigor (CPCV / PBO / DSR) on every horizon —
  because sweeping 5 horizons IS 5 variants tried, and the best of them is
  exactly the kind of thing DSR/PBO exist to deflate.

DESIGN (kept clean on purpose)
  * Tape: 1H bars (6599 bars/symbol ~ 9 months) — long enough for multi-day holds
    without 5m's 288-bar/day censoring. 6 symbols: PYTH WIF JTO BOME SOL BTC.
  * Entry: the SAME breakout / volume-spike detection as the live bot
    (BREAKOUT_LOOKBACK=24, CONFIRM=1.5%, VOL_SPIKE 1.5x/24) — pure OHLCV, tape-
    faithful. One entry set; every horizon exits the IDENTICAL entries.
  * Exit: FIXED HORIZON close-to-close. NO path-dependent stops. This is the
    clean isolation of "does the move scale with hold" — a TP/SL/trail stack would
    confound horizon with the stop logic. (The bot's real stack is a SEPARATE
    question, already measured in exit_reconciliation.)
  * Horizons (in 1H bars): 1h, 4h, 1d(24), 3d(72), 1w(168).
  * Regime: ADX(14) at entry → trend / transitional / chop (the same classifier).
  * Direction: LONG-ONLY (the live bot is long-only; no perps in tape).

RIGOR (the point — quant-backtest-rigor SKILL)
  * Block-bootstrap CI on gross & net EV (stats_validation — autocorrelation-aware).
  * CPCV: 8 time groups, k=2 → C(8,2)=28 OOS Sharpe paths PER horizon, with the
    label horizon = the hold length in groups (purge/embargo remove overlap).
  * PBO over all 5 horizons × the fee grid (honest variant count).
  * DSR on the best horizon, deflated for the honest count of horizons tried.
  * VERDICT block per promising horizon. Default REJECT unless the rigor clears.

DATA LIMITATION (flagged, fed to the richer-data decision)
  OHLCV TIME bars only. We cannot see intrabar path (a 1d close-to-close +2% may
  have round-tripped -5%/+8% — invisible here), nor dollar/volume-bar clocks that
  de-noise the variance, nor L2/trade-flow that would let a longer hold be EXITED
  on microstructure rather than a fixed clock. Close-to-close fixed-horizon is the
  honest thing the data permits; it understates path risk and overstates the
  cleanliness of a fixed-clock exit.

READ-ONLY w.r.t. the live bot (port 8265). Free: cached tape replay, no LLM, no net.

Run:  python3 scripts/calibration/longhold_validation.py
      python3 scripts/calibration/longhold_validation.py --self-test
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "contest_bot"))

import indicators as ind  # noqa: E402  the live bot's indicators (ADX for regime)
import overfitting_rigor as ofr  # noqa: E402  CPCV / PBO / DSR
import stats_validation as sv  # noqa: E402  block-bootstrap CI

# ── Config (tape-faithful) ──────────────────────────────────────────
TAPE_DIR = os.path.join(_HERE, "data", "tape")
SYMBOLS = ["PYTH", "WIF", "JTO", "BOME", "SOL", "BTC"]
TF = "1H"  # 1-hour bars: long enough for multi-day holds, 6599 bars/symbol

# Entry detection (mirrors live bot — pure OHLCV)
BREAKOUT_LOOKBACK = 24
BREAKOUT_CONFIRM_PCT = 1.5
VOL_SPIKE_MULT = 1.5
VOL_SPIKE_BARS = 24
WARMUP = 50  # ADX(14)/EMA warm-up
ENTRY_STRIDE = 6  # no-overlap stride after an entry (mirrors backtest run_symbol)

# Hold horizons in 1H BARS. Honest variant count = len(HORIZONS).
HORIZONS_BARS = {"1h": 1, "4h": 4, "1d": 24, "3d": 72, "1w": 168}

# Fee grid (round-trip %, taker; the venue/fee doc band). 2x-fee bar = 2*fee.
FEE_GRID = [0.04, 0.10, 0.20, 0.40, 0.75]

# Regime thresholds (same as the rest of the harness)
ADX_TREND = 25.0
ADX_CHOP = 18.0

# CPCV config
CPCV_N_GROUPS = 8
CPCV_N_TEST = 2
CPCV_EMBARGO = 1


# ── Data ────────────────────────────────────────────────────────────
def load_tape(symbol: str, tf: str = TF) -> list[dict]:
    path = os.path.join(TAPE_DIR, f"{symbol}_{tf}.json")
    with open(path) as f:
        return json.load(f)


def as_columns(candles: list[dict]) -> dict:
    return {
        "ts": [x["ts"] for x in candles],
        "open": [x["open"] for x in candles],
        "high": [x["high"] for x in candles],
        "low": [x["low"] for x in candles],
        "close": [x["close"] for x in candles],
        "volume": [x["volume"] for x in candles],
    }


# ── Entry detection (pure OHLCV, tape-faithful) ─────────────────────
def breakout_fires(c: dict, i: int) -> bool:
    if i < BREAKOUT_LOOKBACK:
        return False
    prior = c["high"][i - BREAKOUT_LOOKBACK : i]
    prior_high = max(prior) if prior else 0.0
    if prior_high <= 0:
        return False
    return (c["close"][i] - prior_high) / prior_high * 100.0 >= BREAKOUT_CONFIRM_PCT


def volume_spike_fires(c: dict, i: int) -> bool:
    if i < 1:
        return False
    lo = max(0, i - VOL_SPIKE_BARS + 1)
    window = c["volume"][lo : i + 1]
    if not window:
        return False
    med = st.median(window)
    if med <= 0:
        return False
    return c["volume"][i] >= VOL_SPIKE_MULT * med


def regime_at(adx_series: list, i: int) -> str:
    a = adx_series[i] if i < len(adx_series) else None
    if a is None:
        return "transitional"
    if a >= ADX_TREND:
        return "trend"
    if a <= ADX_CHOP:
        return "chop"
    return "transitional"


# ── A longer-hold entry (one entry, exits computed per horizon) ─────
@dataclass
class Entry:
    sym: str
    idx: int  # entry bar (time order key within symbol)
    regime: str
    # gross close-to-close return % at each horizon (NaN if censored — not enough
    # forward bars). Keyed by horizon label.
    gross_by_horizon: dict[str, float]


def collect_entries(symbols: list[str]) -> tuple[list[Entry], dict[str, dict]]:
    """One entry set; every horizon's gross return computed on the SAME entries.

    An entry at bar i has gross_h = (close[i+h] - close[i]) / close[i] * 100 for
    each horizon h, or NaN if i+h exceeds the tape (censoring guard — never mark
    to last close, which would bias a long horizon toward 0)."""
    max_h = max(HORIZONS_BARS.values())
    entries: list[Entry] = []
    enriched: dict[str, dict] = {}
    for sym in symbols:
        candles = load_tape(sym)
        c = as_columns(candles)
        adx_series = ind.adx(c["high"], c["low"], c["close"], 14)
        enriched[sym] = c
        n = len(c["close"])
        i = WARMUP
        while i < n:
            if breakout_fires(c, i) or volume_spike_fires(c, i):
                ep = c["close"][i]
                gross: dict[str, float] = {}
                for label, h in HORIZONS_BARS.items():
                    j = i + h
                    if ep > 0 and j < n:
                        gross[label] = (c["close"][j] - ep) / ep * 100.0
                    else:
                        gross[label] = float("nan")
                # require the LONGEST horizon to be uncensored so every horizon
                # is evaluated on the SAME entry set (apples to apples).
                if i + max_h < n:
                    entries.append(
                        Entry(
                            sym=sym,
                            idx=i,
                            regime=regime_at(adx_series, i),
                            gross_by_horizon=gross,
                        )
                    )
                i += ENTRY_STRIDE
            else:
                i += 1
    return entries, enriched


# ── Per-horizon gross / net EV with block-bootstrap CI ──────────────
def horizon_series(
    entries: list[Entry], horizon: str, regime: str | None = None
) -> list[list[float]]:
    """Per-symbol ordered gross-return series for one horizon (and optional
    regime), for the block bootstrap (within-symbol order preserved)."""
    by_sym: dict[str, list[float]] = {}
    for e in entries:
        if regime is not None and e.regime != regime:
            continue
        v = e.gross_by_horizon.get(horizon, float("nan"))
        if v == v:  # not NaN
            by_sym.setdefault(e.sym, []).append(v)
    return [s for s in by_sym.values() if s]


def gross_ev(entries: list[Entry], horizon: str, regime: str | None = None) -> dict:
    series = horizon_series(entries, horizon, regime)
    flat = [v for s in series for v in s]
    if len(flat) < 2:
        return {
            "n": len(flat),
            "n_eff": float(len(flat)),
            "ev": float("nan"),
            "ci": (float("nan"), float("nan")),
            "excl0": False,
        }
    mean, lo, hi, n_eff, block = sv.block_bootstrap_ci(series)
    return {
        "n": len(flat),
        "n_eff": n_eff,
        "ev": mean,
        "ci": (lo, hi),
        "block": block,
        "excl0": (lo > 0 or hi < 0),
        "excl0_pos": (lo > 0),
    }


def net_ev_clears_2x_fee(entries: list[Entry], horizon: str, fee: float) -> dict:
    """Net EV = gross - fee. The 2x-fee BAR is: does the net-EV CI exclude 2*fee
    on the + side? (i.e. the edge is worth at least twice the round-trip cost — a
    margin-of-safety bar, not just break-even.)"""
    series = horizon_series(entries, horizon)
    flat = [v for s in series for v in s]
    if len(flat) < 2:
        return {
            "n": len(flat),
            "net_ev": float("nan"),
            "ci": (float("nan"),) * 2,
            "clears_2x": False,
            "bar": 2 * fee,
        }
    net_series = [[v - fee for v in s] for s in series]
    mean, lo, hi, _neff, _b = sv.block_bootstrap_ci(net_series)
    bar = 2 * fee  # the 2x-fee margin-of-safety threshold (above net 0)
    # "clears the 2x-fee bar CI-clean" = net-EV CI lower bound > +fee
    #   (net = gross - fee; clearing 2x fee means gross-fee CI low > fee, i.e.
    #    gross CI low > 2*fee). Equivalent: net-EV CI low > fee.
    clears = lo > fee
    return {
        "n": len(flat),
        "net_ev": mean,
        "ci": (lo, hi),
        "bar": bar,
        "clears_2x": clears,
        "gross_ci_low_minus_2fee": (lo + fee) - 2 * fee,  # gross_lo - 2*fee
    }


# ── CPCV per horizon ────────────────────────────────────────────────
def cpcv_for_horizon(entries: list[Entry], horizon: str, fee: float = 0.0) -> ofr.CPCVResult:
    """Build the CPCV sample stream for one horizon.

    Time order: sort all entries by (idx, sym) — the bar clock across symbols.
    Assign each entry to one of CPCV_N_GROUPS contiguous time groups. The label
    horizon (in GROUPS) = ceil(hold_bars / group_span_bars) — a long hold spills
    its label into later groups, which the purge then removes from any test path
    that doesn't contain the whole horizon. ret = gross - fee."""
    rows = [(e, e.gross_by_horizon.get(horizon, float("nan"))) for e in entries]
    rows = [(e, g) for (e, g) in rows if g == g]  # drop censored
    if len(rows) < CPCV_N_GROUPS * 2:
        return ofr.CPCVResult(
            CPCV_N_GROUPS,
            CPCV_N_TEST,
            0,
            [],
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            0.0,
            note="too few entries for CPCV",
        )
    ordered = sorted(rows, key=lambda r: (r[0].idx, r[0].sym))
    n = len(ordered)
    # group boundaries by COUNT (equal-population groups over the ordered stream)
    bounds = [round(n * gi / CPCV_N_GROUPS) for gi in range(CPCV_N_GROUPS + 1)]
    # map each row's position to its group
    pos_group = [0] * n
    for gi in range(CPCV_N_GROUPS):
        for p in range(bounds[gi], bounds[gi + 1]):
            pos_group[p] = gi
    # label horizon in groups: how many WHOLE groups does the hold spill past the
    # entry's own group. group span in BARS ~ (idx range)/N_GROUPS. A hold shorter
    # than one group span spills 0 groups (its label closes inside the entry group
    # almost always); only a hold comparable to / longer than a group span spills.
    # Use true ceil of (hold / bars_per_group) MINUS 1 so a hold that fits inside a
    # group is span 0 (no purge needed), and a hold equal to one group is span 1.
    import math as _m

    idx_min = ordered[0][0].idx
    idx_max = ordered[-1][0].idx
    bars_per_group = max(1.0, (idx_max - idx_min) / CPCV_N_GROUPS)
    hold_bars = HORIZONS_BARS[horizon]
    label_span_groups = max(0, _m.ceil(hold_bars / bars_per_group) - 1)
    samples: list[tuple[int, float, int]] = []
    for p, (_e, g) in enumerate(ordered):
        grp = pos_group[p]
        lab_end = min(CPCV_N_GROUPS - 1, grp + label_span_groups)
        samples.append((grp, g - fee, lab_end))
    return ofr.cpcv_paths(
        samples, n_groups=CPCV_N_GROUPS, n_test=CPCV_N_TEST, embargo_groups=CPCV_EMBARGO
    )


# ── PBO + DSR over the horizon grid ─────────────────────────────────
def pbo_over_horizons(entries: list[Entry], fee: float = 0.0) -> ofr.PBOResult:
    """PBO with variants = the 5 horizons. perf_matrix rows = time blocks,
    columns = horizons; value = mean net return of that horizon's entries in that
    block. Honest: every horizon we swept is a column."""
    horizons = list(HORIZONS_BARS.keys())
    ordered = sorted(entries, key=lambda e: (e.idx, e.sym))
    n = len(ordered)
    n_blocks = 10
    if n < n_blocks * 2:
        return ofr.PBOResult(
            float("nan"), 0, len(horizons), float("nan"), note="too few entries for PBO"
        )
    bounds = [round(n * b / n_blocks) for b in range(n_blocks + 1)]
    matrix: list[list[float]] = []
    for b in range(n_blocks):
        block_entries = ordered[bounds[b] : bounds[b + 1]]
        row: list[float] = []
        for h in horizons:
            vals = [
                e.gross_by_horizon[h] - fee
                for e in block_entries
                if e.gross_by_horizon[h] == e.gross_by_horizon[h]
            ]
            row.append(st.mean(vals) if vals else 0.0)
        matrix.append(row)
    return ofr.pbo(matrix, n_partitions=n_blocks)


def dsr_for_horizon(
    entries: list[Entry],
    horizon: str,
    all_horizon_sharpes: list[float],
    n_trials: int,
    fee: float = 0.0,
) -> ofr.DSRResult:
    """DSR on one horizon's per-entry net returns, deflated for n_trials honestly
    counted variants (horizons × fee levels)."""
    series = horizon_series(entries, horizon)
    flat = [v - fee for s in series for v in s]
    return ofr.deflated_sharpe_ratio(flat, all_horizon_sharpes, n_trials=n_trials)


def horizon_sharpe(entries: list[Entry], horizon: str, fee: float = 0.0) -> float:
    series = horizon_series(entries, horizon)
    flat = [v - fee for s in series for v in s]
    return ofr.sharpe_ratio(flat)


# ── Self-test ───────────────────────────────────────────────────────
def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # synthetic tape: a clean uptrend → longer hold MUST capture a bigger move.
    up = [
        {
            "ts": i,
            "open": 100 + i,
            "high": 100 + i + 0.5,
            "low": 100 + i - 0.5,
            "close": 100 + i,
            "volume": 100.0,
        }
        for i in range(400)
    ]
    c = as_columns(up)
    # entry at bar 50; gross 1h vs 1d vs 1w must be increasing on a linear ramp
    ep = c["close"][50]
    g1 = (c["close"][51] - ep) / ep * 100
    g24 = (c["close"][74] - ep) / ep * 100
    g168 = (c["close"][218] - ep) / ep * 100
    check(
        f"T1 longer hold captures bigger move on a ramp ({g1:.2f}<{g24:.2f}<{g168:.2f})",
        g1 < g24 < g168,
    )

    # entry detection fires on a breakout
    spike = [
        {"ts": i, "open": 100, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 100.0}
        for i in range(30)
    ]
    spike.append({"ts": 30, "open": 100, "high": 105, "low": 100, "close": 104.0, "volume": 1000.0})
    cc = as_columns(spike)
    check("T2 breakout_fires on a >1.5% close above 24-bar high", breakout_fires(cc, 30))
    check("T3 volume_spike_fires on a 10x volume bar", volume_spike_fires(cc, 30))

    # CPCV stream construction on a positive-drift synthetic entry set (with
    # noise — a zero-variance series has Sharpe 0 by definition, so the edge needs
    # dispersion for the Sharpe distribution to be meaningful).
    import random as _rnd

    _r = _rnd.Random(7)
    ents = [
        Entry("SYN", i, "trend", {h: 0.5 + _r.gauss(0, 0.3) for h in HORIZONS_BARS})
        for i in range(200)
    ]
    res = cpcv_for_horizon(ents, "1d", fee=0.0)
    check(
        f"T4 CPCV yields a positive Sharpe distribution on a synthetic edge "
        f"({res.n_paths} paths, median {res.median:+.2f})",
        res.n_paths > 0 and res.median > 0,
    )

    print(f"\n  {'ALL TESTS PASS' if ok else 'SOME TESTS FAILED'}")
    return ok


# ── Main report ─────────────────────────────────────────────────────
def run() -> dict:
    print("=" * 100)
    print(
        "EXPERIMENT 1 — LONGER-HOLD gross-EV-vs-horizon  (1H tape, long-only, fixed-horizon exit)"
    )
    print("=" * 100)
    entries, _enr = collect_entries(SYMBOLS)
    n_per_sym: dict[str, int] = {}
    regime_mix: dict[str, int] = {}
    for e in entries:
        n_per_sym[e.sym] = n_per_sym.get(e.sym, 0) + 1
        regime_mix[e.regime] = regime_mix.get(e.regime, 0) + 1
    print(f"\nEntries (breakout/volume-spike, longest-horizon-uncensored): {len(entries)} total")
    print(f"  per symbol: {dict(sorted(n_per_sym.items()))}")
    print(f"  regime mix: {dict(sorted(regime_mix.items()))}")

    horizons = list(HORIZONS_BARS.keys())
    n_trials = len(horizons) * len(FEE_GRID)  # honest variant count

    # ── gross EV vs horizon (the curve) ──
    print("\n=== GROSS EV vs HORIZON (block-bootstrap 95% CI; ALL regimes) ===")
    print(
        f"  {'horizon':>7} {'bars':>5} {'N':>5} {'Neff':>5} | {'grossEV%':>9} "
        f"{'block 95% CI':>22} {'excl0':>7} {'Sharpe':>7}"
    )
    print("  " + "-" * 78)
    gross_curve: dict = {}
    for h in horizons:
        g = gross_ev(entries, h)
        lo, hi = g["ci"]
        excl = "YES(+)" if g.get("excl0_pos") else ("YES(-)" if g["excl0"] else "no")
        shp = horizon_sharpe(entries, h, fee=0.0)
        print(
            f"  {h:>7} {HORIZONS_BARS[h]:>5} {g['n']:>5} {g['n_eff']:>5.0f} | "
            f"{g['ev']:>+9.3f} [{lo:>+7.3f},{hi:>+7.3f}] {excl:>7} {shp:>+7.3f}"
        )
        gross_curve[h] = {
            "bars": HORIZONS_BARS[h],
            "n": g["n"],
            "n_eff": g["n_eff"],
            "gross_ev": g["ev"],
            "ci": [lo, hi],
            "excl_zero_positive": bool(g.get("excl0_pos")),
            "sharpe": shp,
        }

    # ── per-regime gross EV ──
    print("\n=== GROSS EV by REGIME (block-bootstrap 95% CI) ===")
    per_regime: dict = {}
    for h in horizons:
        per_regime[h] = {}
        for rg in ("trend", "transitional", "chop"):
            g = gross_ev(entries, h, regime=rg)
            per_regime[h][rg] = {
                "n": g["n"],
                "gross_ev": g["ev"],
                "ci": list(g["ci"]),
                "excl_zero_positive": bool(g.get("excl0_pos")),
            }
        line = f"  {h:>4}: "
        for rg in ("trend", "transitional", "chop"):
            cell = per_regime[h][rg]
            ev = cell["gross_ev"]
            flag = "+" if cell["excl_zero_positive"] else " "
            line += f"{rg[:5]}={ev:+6.2f}%(n{cell['n']}){flag}  "
        print(line)

    # ── fee sensitivity: does net EV clear the 2x-fee bar CI-clean? ──
    print("\n=== FEE SENSITIVITY — does net-EV clear the 2x-fee bar CI-clean? ===")
    print(f"  {'horizon':>7} | " + " ".join(f"{f'fee{f}%':>11}" for f in FEE_GRID))
    fee_table: dict = {}
    for h in horizons:
        fee_table[h] = {}
        cells = []
        for fee in FEE_GRID:
            r = net_ev_clears_2x_fee(entries, h, fee)
            fee_table[h][str(fee)] = {
                "net_ev": r["net_ev"],
                "ci": list(r["ci"]),
                "clears_2x_fee": r["clears_2x"],
                "bar": r["bar"],
            }
            mark = "CLEAR" if r["clears_2x"] else "no"
            cells.append(f"{r['net_ev']:+6.2f}/{mark:>4}")
        print(f"  {h:>7} | " + " ".join(f"{c:>11}" for c in cells))

    # ── the rigor stack ──
    all_h_sharpes = [horizon_sharpe(entries, h, fee=0.0) for h in horizons]
    pbo_res = pbo_over_horizons(entries, fee=0.0)
    print("\n=== OVERFITTING RIGOR ===")
    print(
        f"  PBO over {len(horizons)} horizons (CSCV, gross): {pbo_res.pbo:.3f} "
        f"({pbo_res.note or f'{pbo_res.n_combinations} combos'})"
    )

    verdicts: dict = {}
    print("\n=== CPCV / DSR / VERDICT per horizon ===")
    for h in horizons:
        cpcv = cpcv_for_horizon(entries, h, fee=0.0)
        # DSR deflated for honest n_trials (horizons x fee levels)
        dsr = dsr_for_horizon(entries, h, all_h_sharpes, n_trials=n_trials, fee=0.0)
        # max DD + Calmar from the worst CPCV path's cumulative equity
        net_series = horizon_series(entries, h)
        flat = [v for s in net_series for v in s]
        mdd = ofr.max_drawdown(flat)
        total = sum(flat)
        calmar = (total / abs(mdd)) if mdd < 0 else float("inf") if total > 0 else 0.0
        v = ofr.make_verdict(f"longhold-{h}", cpcv, dsr, pbo_res, mdd, calmar)
        print("\n" + v.render())
        verdicts[h] = {
            "cpcv_median_sharpe": cpcv.median,
            "cpcv_ci": [cpcv.p05, cpcv.p95],
            "cpcv_pct_paths_neg": cpcv.pct_paths_negative,
            "cpcv_n_paths": cpcv.n_paths,
            "dsr": dsr.dsr,
            "dsr_sr_obs": dsr.observed_sr,
            "dsr_sr_star": dsr.sr_star,
            "pbo": pbo_res.pbo,
            "max_dd": mdd,
            "calmar": calmar,
            "verdict": v.verdict,
            "rationale": v.rationale,
        }

    return {
        "experiment": "1 — longer-hold gross-EV-vs-horizon",
        "tape": {"tf": TF, "symbols": SYMBOLS, "n_entries": len(entries)},
        "n_per_symbol": n_per_sym,
        "regime_mix": regime_mix,
        "horizons_bars": HORIZONS_BARS,
        "fee_grid": FEE_GRID,
        "honest_n_trials": n_trials,
        "gross_curve": gross_curve,
        "per_regime": per_regime,
        "fee_table": fee_table,
        "pbo": pbo_res.pbo,
        "verdicts": verdicts,
        "data_limitation": (
            "OHLCV time bars only: no intrabar path (close-to-close hides round-trips), "
            "no dollar/volume bars (variance not de-noised), no L2/trade-flow (no "
            "microstructure exit). Fixed-horizon close-to-close understates path risk."
        ),
    }


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    out = run()
    ji = sys.argv.index("--json-out") if "--json-out" in sys.argv else -1
    if ji >= 0 and ji + 1 < len(sys.argv):
        with open(sys.argv[ji + 1], "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\nWrote {sys.argv[ji + 1]}", file=sys.stderr)
