"""Tests for walkforward_validation — per-regime partitioning + walk-forward folds.

Asserts: (1) regime partitioning recovers opposite per-regime signs; (2) a
time-stable edge is OOS-positive and same-sign across folds with clean splits;
(3) an edge that flips sign mid-tape FAILS the same-sign-across-folds check.

Run: uv run pytest scripts/calibration/test_walkforward_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import walkforward_validation as wfv


# ── Per-regime partition ────────────────────────────────────────────
def test_partition_recovers_opposite_signs():
    rs = wfv.make_regime_split_samples()
    pr = wfv.per_regime_edge(rs)
    assert pr["trend"]["edge"] > 0
    assert pr["chop"]["edge"] < 0


def test_partition_counts():
    rs = wfv.make_regime_split_samples()
    part = wfv.partition_by_regime(rs)
    assert len(part["trend"]) == 150
    assert len(part["chop"]) == 150
    assert sum(len(v) for v in part.values()) == 300


# ── Walk-forward on a stable edge ───────────────────────────────────
def test_walk_forward_stable_edge_oos_positive():
    cs = wfv.make_consistent_samples(n=240, edge=0.5)
    wf = wfv.walk_forward(cs, n_folds=4)
    assert wf["oos_positive"]
    assert wf["same_sign_across_folds"]


def test_walk_forward_splits_have_no_lookahead():
    cs = wfv.make_consistent_samples(n=240, edge=0.5)
    wf = wfv.walk_forward(cs, n_folds=4)
    assert wf["all_splits_clean"]
    # every non-warmup fold trains on a strictly-earlier slice
    for fd in wf["folds"]:
        assert fd["split_clean"]


def test_walk_forward_fold0_is_warmup():
    cs = wfv.make_consistent_samples(n=240, edge=0.5)
    wf = wfv.walk_forward(cs, n_folds=4)
    assert wf["folds"][0]["is_warmup_fold"]
    assert wf["folds"][0]["n_train"] == 0
    assert wf["folds"][1]["n_train"] > 0


# ── Walk-forward catches a sign-flipping edge ───────────────────────
def test_walk_forward_sign_flip_fails_same_sign():
    fl = wfv.make_regime_flips_sign_samples()
    wf = wfv.walk_forward(fl, n_folds=4)
    assert not wf["same_sign_across_folds"]


def test_walk_forward_insufficient_samples():
    few = wfv.make_consistent_samples(n=6, edge=0.5)
    wf = wfv.walk_forward(few, n_folds=4)
    assert wf["folds"] == []
    assert not wf["oos_positive"]
