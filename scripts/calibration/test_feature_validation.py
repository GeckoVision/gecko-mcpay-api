"""Tests for feature_validation — the Phase V leakage traps.

The load-bearing assertions: the deliberately-LEAKED feature is REJECTED by the
traps and the clean feature is ACCEPTED. That is the harness catching cheating —
the whole reason it exists.

Run: uv run pytest scripts/calibration/test_feature_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feature_validation as fv


def _setup():
    c = fv.build_predictive_window(n=300, phi=0.6, seed=5)
    n = len(c["close"])
    indices = list(range(5, n - 2))
    syms = ["SYN"] * len(indices)
    fwd = [fv.forward_return(c, i, horizon=1) for i in indices]
    return c, indices, syms, fwd


# ── Trap 1: lookahead (structural) ──────────────────────────────────
def test_clean_feature_is_lookahead_invariant():
    c, indices, _syms, _fwd = _setup()
    assert fv.lookahead_clean(fv.MomentumFeature(k=3), c, indices)


def test_leaked_feature_fails_lookahead_trap():
    c, indices, _syms, _fwd = _setup()
    # the leaked feature reads candles[i+1] -> changes when the future is hidden
    assert not fv.lookahead_clean(fv.LeakedFeature(), c, indices)


# ── Trap 2: shuffle (statistical) ───────────────────────────────────
def test_clean_feature_real_edge_present():
    c, indices, syms, fwd = _setup()
    rep = fv.run_leakage_traps(fv.MomentumFeature(k=3), c, indices, fwd, syms)
    assert rep.detail["shuffle"]["real"]["excl_zero"], "clean feature should have a real edge"


def test_clean_feature_edge_vanishes_on_shuffle():
    c, indices, syms, fwd = _setup()
    rep = fv.run_leakage_traps(fv.MomentumFeature(k=3), c, indices, fwd, syms)
    assert not rep.detail["shuffle"]["shuffled"]["excl_zero"], "edge must vanish on shuffled labels"
    assert rep.shuffle_passes


# ── Trap 3: placebo (statistical) ───────────────────────────────────
def test_clean_feature_no_edge_vs_placebo():
    c, indices, syms, fwd = _setup()
    rep = fv.run_leakage_traps(fv.MomentumFeature(k=3), c, indices, fwd, syms)
    assert rep.placebo_passes, "clean feature must show no edge vs an independent noise label"


# ── THE HEADLINE: leaked rejected, clean accepted ───────────────────
def test_leaked_feature_is_rejected():
    c, indices, syms, fwd = _setup()
    rep = fv.run_leakage_traps(fv.LeakedFeature(), c, indices, fwd, syms)
    assert not rep.clean, "the leaked feature must NOT pass the leakage suite"
    assert not rep.lookahead_clean


def test_clean_feature_is_accepted():
    c, indices, syms, fwd = _setup()
    rep = fv.run_leakage_traps(fv.MomentumFeature(k=3), c, indices, fwd, syms)
    assert rep.clean, "the clean feature must pass all three traps"


# ── Protocol conformance ────────────────────────────────────────────
def test_features_conform_to_protocol():
    assert isinstance(fv.MomentumFeature(), fv.Feature)
    assert isinstance(fv.LeakedFeature(), fv.Feature)
