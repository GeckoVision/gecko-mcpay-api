"""Tests for the Phase 1 structure validation harness (light fakes, no I/O).

Asserts the harness machinery is correct without replaying the full 24-tape:
  * regime4_at splits trend into trend_up / trend_down by net close direction;
  * gross_ev_ci recovers a known mean and excludes zero on a clean positive set;
  * gross_delta_paired recovers a positive delta when the filter keeps the winners;
  * feature_passes uses the predicate when present.

Run: uv run pytest scripts/calibration/test_structure_phase1_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import structure_phase1_validation as h


def _cand(tape: str, idx: int, regime: str, pnl: float) -> h.Cand:
    return h.Cand(tape=tape, idx=idx, regime=regime, pnl_real=pnl)


def test_regime4_splits_trend_by_direction(monkeypatch):
    # force base.regime_at to say "trend"; direction decided by close net change.
    monkeypatch.setattr(h.base, "regime_at", lambda c, i: "trend")
    up = {"close": [1.0] * 20 + [2.0]}
    dn = {"close": [2.0] * 20 + [1.0]}
    assert h.regime4_at(up, 20) == "trend_up"
    assert h.regime4_at(dn, 20) == "trend_down"


def test_regime4_passes_through_non_trend(monkeypatch):
    monkeypatch.setattr(h.base, "regime_at", lambda c, i: "chop")
    assert h.regime4_at({"close": [1.0] * 5}, 4) == "chop"


def test_gross_ev_ci_recovers_positive_mean():
    cands = [_cand("T1", i, "trend_up", 2.0) for i in range(40)]
    cands += [_cand("T2", i, "trend_up", 3.0) for i in range(40)]
    res = h.gross_ev_ci(cands)
    assert 2.0 < res["gross_ev"] < 3.0
    assert res["excl_zero_pos"] is True
    assert res["n"] == 80


def test_gross_ev_ci_empty():
    res = h.gross_ev_ci([])
    assert res["n"] == 0


def test_gross_delta_positive_when_filter_keeps_winners():
    # winners +3, losers -1; filter keeps the winners -> positive delta.
    cands: list[h.Cand] = []
    passes: list[bool] = []
    for t in ("T1", "T2", "T3"):
        for i in range(30):
            win = i % 2 == 0
            cands.append(_cand(t, i, "trend_up", 3.0 if win else -1.0))
            passes.append(win)
    res = h.gross_delta_paired(cands, passes)
    # selected mean ~ +3, ungated mean ~ +1 -> delta ~ +2, CI clean positive
    assert res["delta"] > 0
    assert res["excl_zero_pos"] is True
    assert res["n_on"] == 45 and res["n_off"] == 90


def test_gross_delta_nan_when_no_selection():
    cands = [_cand("T1", i, "chop", 1.0) for i in range(10)]
    res = h.gross_delta_paired(cands, [False] * 10)
    assert res["delta"] != res["delta"]  # NaN


def test_feature_passes_uses_predicate():
    class FakeGate:
        name = "fake"

        def passes(self, candles, i):
            return i % 2 == 0

        def compute(self, candles, i):
            return float(i)

    cands = [_cand("T1", i, "trend_up", 0.0) for i in range(6)]
    enriched = {"T1": {"high": [], "low": [], "close": []}}
    passes = h.feature_passes(FakeGate(), enriched, cands)
    assert passes == [True, False, True, False, True, False]


def test_sorted_with_orders_by_tape_idx():
    cands = [_cand("T2", 5, "x", 0.0), _cand("T1", 9, "x", 0.0), _cand("T1", 2, "x", 0.0)]
    passes = [True, False, True]
    ordered = h.sorted_with(cands, passes)
    keys = [(c.tape, c.idx) for c, _p in ordered]
    assert keys == [("T1", 2), ("T1", 9), ("T2", 5)]
