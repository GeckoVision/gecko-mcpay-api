#!/usr/bin/env python3
"""Exit/Hold gross-edge validation — does HOLDING FOR SIZE clear fees? (quant-analyst).

THE BINDING CONSTRAINT (proven three ways across Phase 1)
  ENTRY selection — momentum, the oracle, AND structure — does NOT lift the
  primitive's per-trade GROSS edge past the 2x-fee bar (~1.5% at the 0.75% central
  fee; the best clean read was ~+0.08% in trend_up). Selection is solved; the
  GROSS edge is the bottleneck. The remaining lever is the EXIT/HOLD model: do you
  clear fees by HOLDING FOR SIZE (let winners run) rather than scalping with the
  tight trailing stack?

WHAT THIS DOES (free, deterministic, NO LLM, NO network)
  1. Replays all 24 tapes through the EXACT live candidate gate (breakout OR
     volume-spike, full-horizon) — the SAME candidate entries Phase 1 used — and
     for each candidate simulates SEVERAL exit models, each producing a realized
     GROSS pnl%. The resampling unit is the tape (a (sym, tf) ordered series);
     within-tape order is preserved for the block bootstrap.
  2. Exit models tested vs the baseline live trailing stack:
       - baseline           : the live close-based trailing stack (TP2/SL3/trail/
                              stall) — exit_reconciliation.simulate_exit_real_close.
       - tp_2x / tp_3x / tp_4x : wider fixed take-profit (4 / 6 / 8%), SL3 kept.
       - let_it_ride        : NO fixed TP — exit only on the trailing stop (SL3 as
                              the catastrophic floor). The "hold for size" thesis.
       - structure_trailing : hold while market structure stays HH/HL (UP); exit at
                              the next overhead S/R level, or when structure breaks
                              DOWN, or SL3. Uses the s52 structure primitives.
       - atr_target_*       : TP at +N*ATR, SL at -M*ATR (volatility-scaled).
       - time_hold_*        : max-hold N bars then exit at close, SL3 floor.
  3. Partitions by the 4-WAY regime (trend_up / trend_down / transitional / chop),
     reusing the cross-regime study's regime4_at. Per model x regime reports:
       - GROSS EV (pre-fee), the canonical block-bootstrap CI, N_eff,
       - whether the gross edge CLEARS the 2x-fee bar CI-clean (the real bar),
       - a CENSORING diagnostic (fraction of trades that hit the tape end without
         an exit firing -> marked-to-last-close; hold models censor more, and a
         high censor fraction makes the read OPTIMISTICALLY biased for winners and
         must be flagged, not hidden).
  4. FEE-SENSITIVITY sweep per model x regime: the break-even fee (the fee that
     zeroes net EV) and whether gross clears the 2x-fee bar at 0.75 / 0.10 / 0.04 /
     0.0 % RT (feeds the Jupiter ~0.04% / Phoenix ~0% venue decision).
  5. Runs the full Phase V acceptance gate (default REJECT) per exit model in the
     declared regime (trend_up — where selection works, so holding winners there is
     the best shot).

THE QUESTION ANSWERED
  Does ANY exit/hold model lift gross EV past the 2x-fee bar, in any regime,
  CI-clean — especially trend_up? If yes: which model / regime / fee. If no: does
  it clear at a REACHABLE fee (~0.04%)? If not even at 0% fee, the PRIMITIVE — not
  the exit — is the problem (flagged loudly). Default NOT PROVEN: no lift is
  claimed unless the CI excludes zero AND it clears the bar.

HONESTY
  * Same candidate set across all exit models -> a fair within-trade comparison.
  * Block bootstrap (canonical, stats_validation) — IID understates width on
    autocorrelated returns.
  * Censoring is REPORTED, not hidden: hold-for-size models that never exit before
    the tape ends are marked-to-last-close, which biases the gross read; the censor
    fraction is in every row.
  * READ-ONLY w.r.t. the live bot. No network. NO result numbers baked into these
    docstrings (findings go to the gitignored private/ doc).

Run:
  python3 scripts/calibration/exit_hold_validation.py --json-out /tmp/exit_hold.json
  uv run pytest scripts/calibration/test_exit_hold_validation.py -q   # unit tests
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as stx
import sys
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "contest_bot"))
sys.path.insert(0, os.path.join(_REPO, "contest_bot", "features"))

import acceptance_gate as ag  # noqa: E402
import chart_floor_calibration as base  # noqa: E402  candidate gate + enrich + regime
import exit_reconciliation as recon  # noqa: E402  baseline live exit stack
import feature_validation as fv  # noqa: E402
import indicators as ind  # noqa: E402  ATR (the live bot's module)
import stats_validation as sv  # noqa: E402
import structure as struct  # noqa: E402  s52 structure primitives
import walkforward_validation as wfv  # noqa: E402

TAPE_DIR = os.path.join(_HERE, "data", "tape")
RESERVED = {"tape_index.json", "regime_windows.json"}
REGIMES_4 = ("trend_up", "trend_down", "transitional", "chop")
TREND_DIR_LOOKBACK = 14
FEE_RT = recon.FEE_RT_CENTRAL  # 0.75 RT central; 2x = 1.5% is the economic bar
FEE_SWEEP = [0.75, 0.10, 0.04, 0.0]  # central DEX / Jupiter RFQ-ish / Phoenix-ish / zero
FWD_HORIZON = 18  # bars for the leakage-trap forward label (matches has_full_horizon)

# Exit-model params (the live baseline values are the reference point).
SL_PCT = recon.LIVE_SL_PCT  # 3.0 — kept as the catastrophic floor across models
TRAIL_ACTIVATE = recon.LIVE_TRAIL_ACTIVATE_PCT  # 1.0
TRAIL_STOP = recon.LIVE_TRAIL_STOP_PCT  # 1.0
BASE_TP = recon.LIVE_TP_PCT  # 2.0


# ── A single realized exit result ───────────────────────────────────
@dataclass
class ExitResult:
    pnl: float  # realized GROSS pnl% (close-based)
    reason: str  # tp | sl | trail | structure | time | end
    exited: bool  # True if an exit rule fired before the tape ended
    censored: bool  # True if the trade marked-to-last-close (no exit fired)


def _mark_to_close(c: dict, ep: float, entry_idx: int) -> ExitResult:
    n = len(c["close"])
    if entry_idx + 1 >= n:
        return ExitResult(0.0, "end", False, True)
    return ExitResult((c["close"][-1] - ep) / ep * 100, "end", False, True)


# ── Exit model: wider FIXED take-profit (close-based) ───────────────
def simulate_exit_fixed_tp(c: dict, entry_idx: int, tp_pct: float, sl_pct: float) -> ExitResult:
    """Close-based fixed TP/SL. Mirrors the live poll loop's close-only reads (no
    intrabar wick), so a deep wick that recovers does NOT stop out. Order: SL, TP."""
    ep = c["close"][entry_idx]
    if ep <= 0:
        return ExitResult(0.0, "end", False, True)
    n = len(c["close"])
    for j in range(entry_idx + 1, n):
        pnl = (c["close"][j] - ep) / ep * 100
        if pnl <= -sl_pct:
            return ExitResult(pnl, "sl", True, False)
        if pnl >= tp_pct:
            return ExitResult(pnl, "tp", True, False)
    return _mark_to_close(c, ep, entry_idx)


# ── Exit model: let-it-ride (trailing-only, no fixed TP) ────────────
def simulate_exit_let_it_ride(
    c: dict, entry_idx: int, trail_activate: float, trail_stop: float, sl_pct: float
) -> ExitResult:
    """No fixed TP. Once unrealized peak >= trail_activate%, a give-back of
    trail_stop% from the running peak-of-closes exits. SL is the catastrophic
    floor. This is the pure 'hold winners for size' model."""
    ep = c["close"][entry_idx]
    if ep <= 0:
        return ExitResult(0.0, "end", False, True)
    peak = ep
    n = len(c["close"])
    for j in range(entry_idx + 1, n):
        cl = c["close"][j]
        if cl > peak:
            peak = cl
        pnl = (cl - ep) / ep * 100
        peak_pct = (peak - ep) / ep * 100
        # trail checked first (mirrors the live loop order)
        if peak_pct >= trail_activate and peak > 0 and (peak - cl) / peak * 100 >= trail_stop:
            return ExitResult(pnl, "trail", True, False)
        if pnl <= -sl_pct:
            return ExitResult(pnl, "sl", True, False)
    return _mark_to_close(c, ep, entry_idx)


# ── Exit model: structure-trailing (hold while HH/HL; exit at next S/R) ──
def simulate_exit_structure_trailing(
    c: dict,
    entry_idx: int,
    sl_pct: float,
    lookback: int = struct.DEFAULT_LOOKBACK,
    ms_series: list[str] | None = None,
    target_px: float | None = None,
    _target_set: bool = False,
) -> ExitResult:
    """Hold while market structure remains UP (HH/HL) AND price stays below the next
    overhead S/R level. Exit when:
      - price reaches/exceeds the nearest confirmed resistance above entry (target
        hit — 'sell into the next level'), OR
      - market structure flips to DOWN (LH/LL — the up-leg is over), OR
      - the SL floor is breached.
    Structure + S/R are strictly causal. For the 24-tape replay the caller passes a
    precomputed `ms_series` (market_structure per bar, one causal pass per tape) and
    the fixed `target_px` (nearest overhead resistance at entry); standalone callers
    (tests) leave both None and the function computes them on the fly. If there is
    OPEN SKY (no overhead resistance) the target is None -> hold on the structure
    condition alone (let it run until structure breaks)."""
    ep = c["close"][entry_idx]
    if ep <= 0:
        return ExitResult(0.0, "end", False, True)
    highs, lows, closes = c["high"], c["low"], c["close"]
    if not _target_set:
        # Fix the overhead target ONCE at entry (the level the trade aims for).
        res, _sup = struct.sr_levels(highs, lows, entry_idx, lookback=lookback)
        above = [lvl.price for lvl in res if lvl.price > ep]
        target_px = min(above) if above else None
    n = len(closes)
    for j in range(entry_idx + 1, n):
        cl = closes[j]
        pnl = (cl - ep) / ep * 100
        if pnl <= -sl_pct:
            return ExitResult(pnl, "sl", True, False)
        if target_px is not None and cl >= target_px:
            return ExitResult(pnl, "structure", True, False)
        ms = (
            ms_series[j]
            if ms_series is not None
            else struct.market_structure(highs, lows, j, lookback=lookback)
        )
        if ms == "DOWN":
            return ExitResult(pnl, "structure", True, False)
    return _mark_to_close(c, ep, entry_idx)


# ── Exit model: ATR-multiple targets ────────────────────────────────
def simulate_exit_atr(
    c: dict, entry_idx: int, atr_abs: float | None, tp_mult: float, sl_mult: float
) -> ExitResult:
    """TP at +tp_mult*ATR, SL at -sl_mult*ATR (volatility-scaled, in price units).
    Close-based. `atr_abs` is the ATR value (price units) AT ENTRY, computed
    causally by the caller. None ATR -> targets undefined -> mark-to-close."""
    ep = c["close"][entry_idx]
    if ep <= 0:
        return ExitResult(0.0, "end", False, True)
    if atr_abs is None or atr_abs <= 0:
        return _mark_to_close(c, ep, entry_idx)
    tp_px = ep + tp_mult * atr_abs
    sl_px = ep - sl_mult * atr_abs
    n = len(c["close"])
    for j in range(entry_idx + 1, n):
        cl = c["close"][j]
        pnl = (cl - ep) / ep * 100
        if cl <= sl_px:
            return ExitResult(pnl, "sl", True, False)
        if cl >= tp_px:
            return ExitResult(pnl, "tp", True, False)
    return _mark_to_close(c, ep, entry_idx)


# ── Exit model: time-based max-hold ─────────────────────────────────
def simulate_exit_time_hold(c: dict, entry_idx: int, max_bars: int, sl_pct: float) -> ExitResult:
    """Hold for up to max_bars, then exit at the close; SL is the floor. A pure
    'give the trade room for N bars' model."""
    ep = c["close"][entry_idx]
    if ep <= 0:
        return ExitResult(0.0, "end", False, True)
    n = len(c["close"])
    for j in range(entry_idx + 1, n):
        cl = c["close"][j]
        age = j - entry_idx
        pnl = (cl - ep) / ep * 100
        if pnl <= -sl_pct:
            return ExitResult(pnl, "sl", True, False)
        if age >= max_bars:
            return ExitResult(pnl, "time", True, False)
    return _mark_to_close(c, ep, entry_idx)


# ── The exit-model roster ───────────────────────────────────────────
# Names only; the per-candidate simulation is dispatched in `simulate_all` so the
# expensive structure/ATR computations can be served from a per-tape cache.
MODEL_NAMES = (
    "baseline",
    "tp_2x",
    "tp_3x",
    "tp_4x",
    "let_it_ride",
    "structure_trailing",
    "atr_2_1.5",
    "atr_3_1.5",
    "atr_4_2",
    "time_hold_24",
    "time_hold_48",
)


def exit_models() -> dict:
    """name -> callable(c, idx) -> ExitResult. Standalone (test) path — recomputes
    structure/ATR on the fly (no cache). The 24-tape replay uses `simulate_all`
    with a per-tape cache instead, for speed."""
    return {
        "baseline": lambda c, i: _wrap_baseline(c, i),
        "tp_2x": lambda c, i: simulate_exit_fixed_tp(c, i, BASE_TP * 2, SL_PCT),
        "tp_3x": lambda c, i: simulate_exit_fixed_tp(c, i, BASE_TP * 3, SL_PCT),
        "tp_4x": lambda c, i: simulate_exit_fixed_tp(c, i, BASE_TP * 4, SL_PCT),
        "let_it_ride": lambda c, i: simulate_exit_let_it_ride(
            c, i, TRAIL_ACTIVATE, TRAIL_STOP, SL_PCT
        ),
        "structure_trailing": lambda c, i: simulate_exit_structure_trailing(c, i, SL_PCT),
        "atr_2_1.5": lambda c, i: simulate_exit_atr(c, i, _atr_at(c, i), 2.0, 1.5),
        "atr_3_1.5": lambda c, i: simulate_exit_atr(c, i, _atr_at(c, i), 3.0, 1.5),
        "atr_4_2": lambda c, i: simulate_exit_atr(c, i, _atr_at(c, i), 4.0, 2.0),
        "time_hold_24": lambda c, i: simulate_exit_time_hold(c, i, 24, SL_PCT),
        "time_hold_48": lambda c, i: simulate_exit_time_hold(c, i, 48, SL_PCT),
    }


def _atr_at(c: dict, idx: int) -> float | None:
    """Causal ATR(14) value (price units) at bar idx, from candles[:idx+1]."""
    series = ind.atr(c["high"][: idx + 1], c["low"][: idx + 1], c["close"][: idx + 1], 14)
    return series[idx] if idx < len(series) else None


@dataclass
class TapeCache:
    """Per-tape precomputed series so each exit model is O(forward-window) per trade
    instead of recomputing pivots/ATR per forward bar (the difference between the
    replay finishing in seconds vs. timing out).

    ms_series  — market_structure(...) at every bar, ONE causal pass (the whole-
                 series pass is identical to the per-bar truncated pass because
                 confirmed_pivots only reads bars <= j; verified by the structure
                 lookahead trap).
    atr_series — causal ATR(14) over the full tape (Wilder smoothing is causal)."""

    ms_series: list[str]
    atr_series: list[float | None]


def build_tape_cache(c: dict, lookback: int = struct.DEFAULT_LOOKBACK) -> TapeCache:
    highs, lows, closes = c["high"], c["low"], c["close"]
    n = len(closes)
    ms = [struct.market_structure(highs, lows, j, lookback=lookback) for j in range(n)]
    atr = ind.atr(highs, lows, closes, 14)
    return TapeCache(ms_series=ms, atr_series=atr)


def simulate_all(c: dict, i: int, cache: TapeCache) -> tuple[dict, dict]:
    """Run every exit model for candidate bar `i`, using the per-tape cache. Returns
    (pnl_by_model, censored_by_model)."""
    atr_abs = cache.atr_series[i] if i < len(cache.atr_series) else None
    # structure target fixed once at entry (nearest overhead resistance)
    res, _sup = struct.sr_levels(c["high"], c["low"], i)
    ep = c["close"][i]
    above = [lvl.price for lvl in res if lvl.price > ep]
    target_px = min(above) if above else None

    results = {
        "baseline": _wrap_baseline(c, i),
        "tp_2x": simulate_exit_fixed_tp(c, i, BASE_TP * 2, SL_PCT),
        "tp_3x": simulate_exit_fixed_tp(c, i, BASE_TP * 3, SL_PCT),
        "tp_4x": simulate_exit_fixed_tp(c, i, BASE_TP * 4, SL_PCT),
        "let_it_ride": simulate_exit_let_it_ride(c, i, TRAIL_ACTIVATE, TRAIL_STOP, SL_PCT),
        "structure_trailing": simulate_exit_structure_trailing(
            c, i, SL_PCT, ms_series=cache.ms_series, target_px=target_px, _target_set=True
        ),
        "atr_2_1.5": simulate_exit_atr(c, i, atr_abs, 2.0, 1.5),
        "atr_3_1.5": simulate_exit_atr(c, i, atr_abs, 3.0, 1.5),
        "atr_4_2": simulate_exit_atr(c, i, atr_abs, 4.0, 2.0),
        "time_hold_24": simulate_exit_time_hold(c, i, 24, SL_PCT),
        "time_hold_48": simulate_exit_time_hold(c, i, 48, SL_PCT),
    }
    pnl = {k: v.pnl for k, v in results.items()}
    cens = {k: v.censored for k, v in results.items()}
    return pnl, cens


def _wrap_baseline(c: dict, i: int) -> ExitResult:
    """The live trailing stack returns a bare pnl%; wrap it so it shares the
    ExitResult shape. It always 'exits' (its stall rules + mark-to-close are part
    of the stack), so we don't separately flag censoring for it (it is the
    reference)."""
    pnl = recon.simulate_exit_real_close(c, i)
    return ExitResult(pnl, "baseline", True, False)


# ── A graded candidate: one Row per fired bar, all models' pnl ──────
@dataclass
class Row:
    tape: str  # "BTC_1H" — the resampling unit (within-tape order preserved)
    idx: int
    regime: str  # 4-way
    pnl: dict  # model_name -> realized GROSS pnl%
    censored: dict  # model_name -> bool (marked-to-last-close)


def regime4_at(c: dict, i: int) -> str:
    r = base.regime_at(c, i)
    if r != "trend":
        return r
    lo = max(0, i - TREND_DIR_LOOKBACK)
    net = c["close"][i] - c["close"][lo]
    return "trend_up" if net >= 0 else "trend_down"


def collect_all_tapes(tape_dir: str = TAPE_DIR) -> tuple[dict, list[Row], dict]:
    """Replay every tape through the EXACT live gate; for each candidate run ALL
    exit models (served from a per-tape cache). Returns (enriched_by_tape, rows,
    meta)."""
    enriched: dict[str, dict] = {}
    rows: list[Row] = []
    meta: dict = {"tapes": {}, "skipped": []}
    files = sorted(
        f for f in os.listdir(tape_dir) if f.endswith(".json") and "_" in f and f not in RESERVED
    )
    for fname in files:
        with open(os.path.join(tape_dir, fname)) as fh:
            raw = json.load(fh)
        if not isinstance(raw, list) or len(raw) < 60:
            meta["skipped"].append(fname)
            continue
        tape = fname[:-5]
        c = base.enrich(raw)
        enriched[tape] = c
        cache = build_tape_cache(c)
        n = len(c["close"])
        per_tape = 0
        i = base.WARMUP
        while i < n:
            if (
                base.breakout_fires(c, i) or base.volume_spike_fires(c, i)
            ) and base.has_full_horizon(c, i):
                pnl, cens = simulate_all(c, i, cache)
                rows.append(Row(tape=tape, idx=i, regime=regime4_at(c, i), pnl=pnl, censored=cens))
                per_tape += 1
                i += 6  # no-overlap, mirrors the backtest run
            else:
                i += 1
        meta["tapes"][tape] = {"bars": n, "candidates": per_tape}
        print(f"    {tape}: {per_tape} candidates", file=sys.stderr)
    return enriched, rows, meta


# ── Fast block bootstrap (bit-identical to sv, prefix-sum accelerated) ──
def fast_block_bootstrap_ci(
    series_list: list[list[float]],
    block: int | None = None,
    n_boot: int = sv.N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = sv.RNG_SEED,
) -> tuple[float, float, float, float, int]:
    """Drop-in for sv.block_bootstrap_ci that produces BIT-IDENTICAL results but
    runs in O(n_boot * total/block) instead of O(n_boot * total).

    It mirrors sv's EXACT RNG draw sequence — same rng.choices(usable, weights),
    same rng.randrange(start) per block, same truncate-to-total — so the resampled
    means (and therefore the percentiles) are numerically identical. The only change
    is that each block's contribution to the running sum is an O(1) prefix-sum
    lookup rather than a list.extend + statistics.mean over `total` elements at the
    end. Equivalence is asserted in the unit test against the canonical function on
    the same data + seed. This is the difference between the 11-model replay finishing
    in a couple of minutes vs. timing out at ~25."""
    flat = [v for s in series_list for v in s]
    if not flat:
        return (float("nan"), float("nan"), float("nan"), 0.0, 0)
    point = stx.mean(flat)
    n_eff = sv.effective_n(series_list)
    if len(flat) == 1:
        return (point, point, point, n_eff, 1)
    b = block if block is not None else sv.choose_block_length(series_list)
    usable = [s for s in series_list if len(s) >= 1]
    weights = [len(s) for s in usable]
    total = len(flat)
    # prefix sums + length per usable series; index by identity (id()) so the
    # rng.choices result maps back to its prefix array in O(1).
    cum = []
    lens = []
    id_to_si = {}
    for k, s in enumerate(usable):
        c = [0.0]
        for v in s:
            c.append(c[-1] + v)
        cum.append(c)
        lens.append(len(s))
        id_to_si[id(s)] = k
    import random

    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(n_boot):
        ssum = 0.0
        got = 0
        while got < total:
            s = rng.choices(usable, weights=weights, k=1)[0]
            si = id_to_si[id(s)]
            slen = lens[si]
            bb = min(b, slen)
            start = rng.randrange(0, slen - bb + 1)
            # mirror sv: it extends the WHOLE block then truncates at `total` at the
            # end. Equivalent: add the block, but if it would overshoot `total` only
            # the first (total-got) of THIS block survive the truncation.
            take = min(bb, total - got)
            ssum += cum[si][start + take] - cum[si][start]
            got += bb  # sv advances by the full block length before truncating
        boots.append(ssum / total)
    boots.sort()
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[int((1 - alpha / 2) * n_boot)]
    return (point, lo, hi, n_eff, b)


# ── Gross-EV block-CI on a row subset for one model ─────────────────
def _by_tape_gross(rows: list[Row], model: str) -> list[list[float]]:
    by: dict[str, list[float]] = {}
    for r in sorted(rows, key=lambda x: (x.tape, x.idx)):
        by.setdefault(r.tape, []).append(r.pnl[model])
    return [v for v in by.values() if v]


def gross_ev_ci(rows: list[Row], model: str) -> dict:
    series = _by_tape_gross(rows, model)
    if not series:
        return {"gross_ev": float("nan"), "ci": (float("nan"), float("nan")), "n": 0, "n_eff": 0.0}
    mean, lo, hi, n_eff, _b = fast_block_bootstrap_ci(series)
    return {
        "gross_ev": mean,
        "ci": (lo, hi),
        "n": sum(len(s) for s in series),
        "n_eff": n_eff,
        "excl_zero_pos": lo == lo and lo > 0,
    }


def censor_fraction(rows: list[Row], model: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.censored.get(model)) / len(rows)


# ── Fee sensitivity ─────────────────────────────────────────────────
def break_even_fee(gross_ev: float) -> float:
    """The round-trip fee that zeroes net EV. = gross EV when positive; 0 if gross
    is non-positive (no fee clears a non-positive gross edge)."""
    if gross_ev != gross_ev:  # NaN
        return float("nan")
    return max(0.0, gross_ev)


def fee_sensitivity(gross_ev: float, fees: list[float] = FEE_SWEEP) -> dict:
    """For each fee: net EV = gross - fee; does gross clear the 2x-fee bar
    (gross >= 2*fee)? Plus the break-even fee."""
    per_fee = []
    for f in fees:
        bar = ag.ECON_FEE_MULTIPLE * f
        per_fee.append(
            {
                "fee_rt": f,
                "two_x_bar": bar,
                "net_ev": (gross_ev - f) if gross_ev == gross_ev else float("nan"),
                "clears_2x_bar": bool(gross_ev == gross_ev and gross_ev >= bar),
            }
        )
    return {"break_even_fee": break_even_fee(gross_ev), "per_fee": per_fee}


# ── Per-model, per-regime analysis ──────────────────────────────────
def analyze_model(rows: list[Row], model: str) -> dict:
    bar = ag.ECON_FEE_MULTIPLE * FEE_RT  # 2x central fee
    out: dict = {"model": model, "regimes": {}}
    for rg in ("ALL", *REGIMES_4):
        pool = rows if rg == "ALL" else [r for r in rows if r.regime == rg]
        if not pool:
            out["regimes"][rg] = {"n": 0}
            continue
        ev = gross_ev_ci(pool, model)
        clears = bool(
            ev["gross_ev"] == ev["gross_ev"]
            and ev["ci"][0] == ev["ci"][0]
            and ev["ci"][0] >= bar  # CI LOWER bound clears 2x central fee
        )
        out["regimes"][rg] = {
            "n": ev["n"],
            "gross_ev": ev["gross_ev"],
            "ci": list(ev["ci"]),
            "n_eff": ev["n_eff"],
            "excl_zero_pos": ev["excl_zero_pos"],
            "censor_frac": censor_fraction(pool, model),
            "two_x_fee_bar": bar,
            "clears_2x_fee_ci_clean": clears,
            "fee_sensitivity": fee_sensitivity(ev["gross_ev"]),
        }
    return out


# ── Phase V acceptance gate per exit model (declared regime) ────────
class _ModelFeature:
    """Adapter so an exit model can be scored by the Phase V acceptance gate. The
    'feature value' is the realized gross pnl% of the trade under this model — a
    strictly-causal realized outcome (no lookahead: it is the trade's own forward
    result, the same quantity the gate's forward-return uses). compute(candles, i)
    looks up the precomputed pnl for (tape implied by candles, i)."""

    def __init__(self, model: str, pnl_by_idx: dict[int, float]):
        self.name = f"exit::{model}"
        self._pnl = pnl_by_idx

    def compute(self, candles: dict, i: int) -> float:
        return self._pnl.get(i, 0.0)


def acceptance_for_model(
    rows: list[Row],
    enriched: dict,
    model: str,
    declared_regime: str,
    pvalue: float,
    fdr_batch_pvalues: list[float],
) -> ag.AcceptanceVerdict:
    """Default-REJECT acceptance gate for one exit model in its declared regime.
    The exit model is applied to the SAME candidate entries; the 'selected' set is
    every candidate in the regime (the exit model does not gate entries — it is the
    exit). EV/econ gates run on the full regime pool; leakage traps run on the
    largest tape's pool (structural property)."""
    pool = [r for r in rows if r.regime == declared_regime]
    by_tape: dict[str, list[Row]] = {}
    for r in pool:
        by_tape.setdefault(r.tape, []).append(r)
    if not by_tape:
        return ag.AcceptanceVerdict(
            feature=f"exit::{model}",
            regime=declared_regime,
            gates=[],
            fee_rt=FEE_RT,
            accepted=False,
        )
    big_tape = max(by_tape, key=lambda t: len(by_tape[t]))
    big_c = enriched[big_tape]
    big_rows = by_tape[big_tape]
    big_indices = [r.idx for r in big_rows]
    big_syms = [big_tape] * len(big_indices)
    big_fwd = [fv.forward_return(big_c, i, FWD_HORIZON) * 100 for i in big_indices]

    feat = _ModelFeature(model, {r.idx: r.pnl[model] for r in big_rows})

    sel_idx = [r.idx for r in pool]
    sel_syms = [r.tape for r in pool]
    gross = [r.pnl[model] for r in pool]
    net = [r.pnl[model] - FEE_RT for r in pool]

    wf_samples = [
        wfv.Sample(
            sym=r.tape,
            idx=r.idx,
            score=r.pnl[model],
            fwd_return=r.pnl[model],
            regime=declared_regime,
        )
        for r in pool
    ]

    return ag.evaluate_feature(
        feature=feat,
        regime=declared_regime,
        candles=big_c,
        indices=sel_idx,
        symbols=sel_syms,
        net_returns=net,
        gross_returns=gross,
        trap_indices=big_indices,
        trap_symbols=big_syms,
        trap_fwd_returns=big_fwd,
        samples_for_walkforward=wf_samples,
        pvalue=pvalue,
        fdr_batch_pvalues=fdr_batch_pvalues,
        fee_rt=FEE_RT,
        panel_columns=None,  # honest NOT_APPLICABLE (incrementality not the question here)
    )


# ── Reporting ───────────────────────────────────────────────────────
def _fmt(x: float) -> str:
    return "  n/a" if x != x else f"{x:+.3f}"


def print_gross_table(analyses: list[dict]) -> None:
    bar = ag.ECON_FEE_MULTIPLE * FEE_RT
    print(f"\n{'=' * 110}")
    print(f"EXIT-MODEL x REGIME — GROSS EV (block-CI), 2x-fee bar = {bar:.2f}% @ {FEE_RT}% RT")
    print(f"{'=' * 110}")
    hdr = (
        f"{'model':>20} {'regime':>13} {'N':>5} {'Neff':>5} | {'grossEV%':>9} "
        f"{'95% CI (block)':>20} {'CI>0':>5} {'cens%':>6} | {'clears 2x?':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for a in analyses:
        for rg in ("ALL", *REGIMES_4):
            r = a["regimes"].get(rg, {})
            if not r or r.get("n", 0) == 0:
                continue
            lo, hi = r["ci"]
            ci_pos = "YES" if r["excl_zero_pos"] else "no"
            clears = "YES(+)" if r["clears_2x_fee_ci_clean"] else "no"
            print(
                f"{a['model']:>20} {rg:>13} {r['n']:>5} {r['n_eff']:>5.0f} | "
                f"{_fmt(r['gross_ev']):>9} [{_fmt(lo)},{_fmt(hi)}] {ci_pos:>5} "
                f"{r['censor_frac'] * 100:>5.0f}% | {clears:>10}"
            )
        print("-" * len(hdr))


def print_fee_sensitivity(analyses: list[dict], regime: str = "trend_up") -> None:
    print(f"\n{'=' * 110}")
    print(f"FEE SENSITIVITY — regime={regime}: break-even fee + clears 2x-bar at each fee")
    print(f"{'=' * 110}")
    hdr = f"{'model':>20} {'grossEV%':>9} {'breakEvenFee%':>14} | " + " ".join(
        f"{'@' + str(f) + '%':>9}" for f in FEE_SWEEP
    )
    print(hdr)
    print("-" * len(hdr))
    for a in analyses:
        r = a["regimes"].get(regime, {})
        if not r or r.get("n", 0) == 0:
            continue
        fs = r["fee_sensitivity"]
        cells = []
        for pf in fs["per_fee"]:
            cells.append("clears" if pf["clears_2x_bar"] else "  no  ")
        print(
            f"{a['model']:>20} {_fmt(r['gross_ev']):>9} {_fmt(fs['break_even_fee']):>14} | "
            + " ".join(f"{c:>9}" for c in cells)
        )


def print_acceptance(verdicts: list[ag.AcceptanceVerdict]) -> None:
    print(f"\n{'=' * 110}")
    print("PHASE V ACCEPTANCE GATE (default REJECT) — per exit model (declared regime=trend_up)")
    print(f"{'=' * 110}")
    for v in verdicts:
        print(
            f"\n  {v.feature}  (regime={v.regime})  ->  {'ACCEPTED' if v.accepted else 'REJECTED'}"
        )
        for g in v.gates:
            print(f"      {g.name:>24}: {g.result.value:>14}  {g.detail}")


def run(json_out: str | None) -> dict:
    print("Loading 24-tape dataset + replaying live gate (all exit models)...", file=sys.stderr)
    enriched, rows, meta = collect_all_tapes()
    dist = {rg: sum(1 for r in rows if r.regime == rg) for rg in REGIMES_4}
    print(
        f"  tapes: {len(meta['tapes'])}  candidates: {len(rows)}  regime dist: {dist}",
        file=sys.stderr,
    )

    models = list(exit_models().keys())
    analyses = [analyze_model(rows, m) for m in models]
    print_gross_table(analyses)
    print_fee_sensitivity(analyses, regime="trend_up")
    print_fee_sensitivity(analyses, regime="ALL")

    declared = "trend_up"
    ledger = ag.PreRegistrationLedger()
    for m in models:
        ledger.register(f"exit::{m}", declared, f"exit model {m} lifts gross edge in {declared}")
    fdr_p = []
    for a in analyses:
        r = a["regimes"].get(declared, {})
        fdr_p.append(0.04 if r.get("excl_zero_pos") else 0.5)
    verdicts = [
        acceptance_for_model(rows, enriched, m, declared, pvalue=p, fdr_batch_pvalues=fdr_p)
        for m, p in zip(models, fdr_p, strict=True)
    ]
    print_acceptance(verdicts)

    result = {
        "generated": "2026-05-24",
        "phase": "Exit/Hold — gross-edge-for-size validation",
        "fee_rt": FEE_RT,
        "fee_sweep": FEE_SWEEP,
        "two_x_fee_bar": ag.ECON_FEE_MULTIPLE * FEE_RT,
        "tape_meta": meta,
        "regime_distribution": dist,
        "n_candidates": len(rows),
        "declared_regime": declared,
        "model_analyses": analyses,
        "acceptance": [v.to_dict() for v in verdicts],
        "ledger_batch_size": ledger.batch_size(),
    }
    if json_out:
        with open(json_out, "w") as fh:
            json.dump(result, fh, indent=2, default=str)
        print(f"\nWrote {json_out}", file=sys.stderr)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    run(args.json_out)


if __name__ == "__main__":
    main()
