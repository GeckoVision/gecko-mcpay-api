"""Tests for the exit/hold gross-edge validation harness (light fakes, no I/O).

Asserts the exit-model machinery is correct without replaying the full 24-tape:
  * each exit simulator fires on the right condition (TP / SL / trail / structure
    / ATR / time) and returns the realized close-based pnl%;
  * censoring is reported honestly (no-exit-fired -> mark-to-last-close flag);
  * gross_ev_ci recovers a known mean + excludes zero on a clean positive set;
  * the fee-sensitivity break-even fee + clears-at-fee flags are arithmetic-correct.

Run: uv run pytest scripts/calibration/test_exit_hold_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import exit_hold_validation as h


# ── tiny candle builder (parallel oldest-first lists) ───────────────
def _candles(closes, highs=None, lows=None):
    return {
        "close": list(closes),
        "high": list(highs) if highs is not None else list(closes),
        "low": list(lows) if lows is not None else list(closes),
    }


# ── fixed-TP exit ───────────────────────────────────────────────────
def test_wider_tp_fires_at_target():
    # entry at 100; close rises to 104 -> 4% TP fires (2x the 2% baseline).
    c = _candles([100, 101, 102, 104, 110])
    res = h.simulate_exit_fixed_tp(c, 0, tp_pct=4.0, sl_pct=3.0)
    assert abs(res.pnl - 4.0) < 1e-9
    assert res.exited is True
    assert res.reason == "tp"


def test_fixed_tp_stop_loss_fires_close_based():
    # close drops to 96 -> -4% <= -SL(3) fires on the close (not intrabar wick).
    c = _candles([100, 99, 96, 95], lows=[100, 90, 90, 90])
    res = h.simulate_exit_fixed_tp(c, 0, tp_pct=4.0, sl_pct=3.0)
    assert res.pnl <= -3.0
    assert res.reason == "sl"


def test_fixed_tp_marks_to_last_close_when_no_exit():
    # never reaches TP or SL -> marks to last close, censored flag True.
    c = _candles([100, 100.5, 101, 101.5])
    res = h.simulate_exit_fixed_tp(c, 0, tp_pct=4.0, sl_pct=3.0)
    assert res.exited is False
    assert res.censored is True
    assert abs(res.pnl - 1.5) < 1e-9


# ── let-it-ride (trailing-only) ─────────────────────────────────────
def test_let_it_ride_holds_then_trails_out():
    # rises to +5% (peak), then gives back > trail_stop -> exits near the peak,
    # NOT at a fixed TP (it would have TP'd out at +2 under the baseline).
    c = _candles([100, 102, 105, 103.5])  # peak 105 (=+5%), close 103.5 trail give 1.43%
    res = h.simulate_exit_let_it_ride(c, 0, trail_activate=1.0, trail_stop=1.0, sl_pct=3.0)
    assert res.reason == "trail"
    # realized = (103.5-100)/100 = +3.5, which is > the +2 a fixed TP would cap.
    assert abs(res.pnl - 3.5) < 1e-9


def test_let_it_ride_sl_floor_still_protects():
    c = _candles([100, 99, 96])
    res = h.simulate_exit_let_it_ride(c, 0, trail_activate=1.0, trail_stop=1.0, sl_pct=3.0)
    assert res.reason == "sl"
    assert res.pnl <= -3.0


# ── ATR-multiple targets ────────────────────────────────────────────
def test_atr_target_fires_on_atr_multiple():
    # ATR provided externally = 2.0 (price units) on a 100 entry -> tp at +2*ATR =
    # +4 -> 104; sl at -1.5*ATR = -3 -> 97.
    c = _candles([100, 101, 104, 110])
    res = h.simulate_exit_atr(c, 0, atr_abs=2.0, tp_mult=2.0, sl_mult=1.5)
    assert res.reason == "tp"
    assert abs(res.pnl - 4.0) < 1e-9


def test_atr_target_none_atr_marks_to_close():
    # no ATR available -> cannot set targets -> hold to last close, censored.
    c = _candles([100, 101, 102])
    res = h.simulate_exit_atr(c, 0, atr_abs=None, tp_mult=2.0, sl_mult=1.5)
    assert res.censored is True


# ── time-based hold ─────────────────────────────────────────────────
def test_time_hold_exits_at_max_bars():
    c = _candles([100, 101, 102, 103, 104, 105])
    res = h.simulate_exit_time_hold(c, 0, max_bars=3, sl_pct=3.0)
    # exits at bar 3 (age 3): close 103 -> +3%
    assert res.reason == "time"
    assert abs(res.pnl - 3.0) < 1e-9


def test_time_hold_sl_floor_fires_first():
    c = _candles([100, 96, 102, 103])
    res = h.simulate_exit_time_hold(c, 0, max_bars=3, sl_pct=3.0)
    assert res.reason == "sl"


# ── structure-trailing + cache causality ────────────────────────────
def test_structure_trailing_sl_floor():
    c = _candles([100, 99, 96, 95])
    res = h.simulate_exit_structure_trailing(c, 0, sl_pct=3.0)
    assert res.reason == "sl"
    assert res.pnl <= -3.0


def test_cached_ms_series_matches_per_bar(monkeypatch):
    # The whole-series market_structure pass (the cache) must equal the per-bar
    # truncated computation at every bar — the lookahead-clean property the cache
    # relies on. Build a wiggly series long enough to confirm pivots.
    import random as _r

    rng = _r.Random(3)
    closes = [100.0]
    for _ in range(80):
        closes.append(closes[-1] * (1 + rng.uniform(-0.03, 0.035)))
    c = _candles(closes)
    cache = h.build_tape_cache(c)
    for j in range(len(closes)):
        trunc = h.struct.market_structure(c["high"][: j + 1], c["low"][: j + 1], j)
        assert cache.ms_series[j] == trunc


def test_simulate_all_returns_all_models():
    closes = [100 + i * 0.3 for i in range(60)]
    c = _candles(closes)
    cache = h.build_tape_cache(c)
    pnl, cens = h.simulate_all(c, 5, cache)
    assert set(pnl.keys()) == set(h.MODEL_NAMES)
    assert set(cens.keys()) == set(h.MODEL_NAMES)


# ── gross-EV CI ─────────────────────────────────────────────────────
def test_gross_ev_ci_recovers_positive_mean():
    rows = [h.Row("T1", i, "trend_up", {"m": 2.0}, {"m": False}) for i in range(40)]
    rows += [h.Row("T2", i, "trend_up", {"m": 3.0}, {"m": False}) for i in range(40)]
    res = h.gross_ev_ci(rows, "m")
    assert 2.0 < res["gross_ev"] < 3.0
    assert res["excl_zero_pos"] is True
    assert res["n"] == 80


def test_gross_ev_ci_empty():
    assert h.gross_ev_ci([], "m")["n"] == 0


def test_fast_block_bootstrap_matches_canonical():
    # The fast prefix-sum block bootstrap must be BIT-IDENTICAL to the canonical
    # sv.block_bootstrap_ci on the same data + seed (it mirrors the exact RNG draw
    # sequence; only the summation is accelerated). Use multi-series autocorrelated
    # data so block>1 and truncation actually exercise.
    import stats_validation as sv

    s1 = sv.ar1_series(120, phi=0.6, seed=1)
    s2 = sv.ar1_series(90, phi=0.4, seed=2)
    s3 = sv.ar1_series(150, phi=0.7, mean=0.3, seed=3)
    series = [s1, s2, s3]
    canon = sv.block_bootstrap_ci(series)
    fast = h.fast_block_bootstrap_ci(series)
    # mean, lo, hi, n_eff, block all identical
    for a, b in zip(canon, fast, strict=True):
        assert abs(a - b) < 1e-9, f"canon={canon} fast={fast}"


# ── fee sensitivity / break-even ────────────────────────────────────
def test_break_even_fee_is_gross_ev():
    # net EV = gross - fee_rt; break-even fee = gross EV (the fee that zeroes net).
    assert abs(h.break_even_fee(0.8) - 0.8) < 1e-9
    assert h.break_even_fee(-0.2) == 0.0  # negative gross never clears any fee


def test_clears_at_fee_flags():
    # gross 0.5: clears 2x-fee bar only where 0.5 >= 2*fee, i.e. fee <= 0.25.
    sweep = h.fee_sensitivity(0.5, fees=[0.75, 0.10, 0.04, 0.0])
    flags = {row["fee_rt"]: row["clears_2x_bar"] for row in sweep["per_fee"]}
    assert flags[0.75] is False  # bar 1.5 > 0.5
    assert flags[0.10] is True  # bar 0.20 <= 0.5
    assert flags[0.04] is True  # bar 0.08 <= 0.5
    assert flags[0.0] is True  # bar 0 <= 0.5
