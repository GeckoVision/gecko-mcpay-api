"""Tests for stats_validation — the Phase V.1 block-bootstrap + BH-FDR primitives.

The load-bearing test is T_block_wider_than_iid: it proves the new block
bootstrap is NOT a cosmetic rename of the IID bootstrap — on autocorrelated data
its CI is materially wider and its N_eff is far below N. That widening is the
entire reason V.1 replaces the IID method.

Run: uv run pytest scripts/calibration/test_stats_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stats_validation as sv


# ── BH-FDR against a hand-computed vector ────────────────────────────
def test_bh_fdr_known_vector():
    pv = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    res = sv.bh_fdr(pv, alpha=0.05)
    assert res["k"] == 2
    assert res["rejected"] == {0, 1}
    assert abs(res["threshold"] - 0.008) < 1e-9
    # adjusted q for smallest p = m/1 * p_(1) = 10*0.001 = 0.01
    assert abs(res["adjusted"][0] - 0.01) < 1e-9


def test_bh_fdr_preserves_original_order():
    # shuffle the same vector; rejected set must track ORIGINAL indices
    pv = [0.039, 0.001, 0.216, 0.008, 0.06]
    res = sv.bh_fdr(pv, alpha=0.05)
    # only 0.001 (idx 1) is small enough: thresholds m=5 -> .01,.02,.03,.04,.05
    # sorted: .001<=.01 ✓; .008<=.02 ✓; .039<=.03 ✗ -> k=2
    assert res["rejected"] == {1, 3}


def test_bh_fdr_empty():
    res = sv.bh_fdr([], 0.05)
    assert res["k"] == 0
    assert res["rejected"] == set()


def test_bh_fdr_all_null():
    # all large p-values -> nothing rejected, threshold 0
    res = sv.bh_fdr([0.9, 0.8, 0.95], 0.05)
    assert res["k"] == 0
    assert res["threshold"] == 0.0


def test_bh_fdr_adjusted_monotone():
    pv = [0.001, 0.008, 0.039, 0.041, 0.042]
    adj = sv.bh_fdr(pv, 0.05)["adjusted"]
    # q-values, taken in p-value-sorted order, must be non-decreasing
    order = sorted(range(len(pv)), key=lambda i: pv[i])
    sorted_q = [adj[i] for i in order]
    assert sorted_q == sorted(sorted_q)
    assert all(0.0 <= q <= 1.0 for q in adj)


# ── Block bootstrap: IID case (should match IID bootstrap) ───────────
def test_block_matches_iid_on_iid_series():
    iid = sv.iid_series(400, sigma=1.0, mean=0.0, seed=11)
    _pi, ilo, ihi = sv.iid_bootstrap_ci(iid)
    _pb, blo, bhi, neff, _bk = sv.block_bootstrap_ci([iid])
    ratio = (bhi - blo) / (ihi - ilo)
    # on IID data the block bootstrap must NOT meaningfully widen the CI
    assert 0.80 <= ratio <= 1.25, f"block/IID width ratio {ratio:.2f} should be ~1 on IID data"
    # and N_eff should be ~ N (no autocorrelation to discount)
    assert neff >= 0.80 * len(iid)


# ── THE DISCRIMINATING PROPERTY (load-bearing) ───────────────────────
def test_block_materially_wider_than_iid_on_ar1():
    """On AR(1) phi=0.7, the block CI must be MATERIALLY wider than the IID CI
    and N_eff must be far below N. This is the proof the harness is real."""
    ar = sv.ar1_series(400, phi=0.7, sigma=1.0, mean=0.0, seed=7)
    _ai, alo, ahi = sv.iid_bootstrap_ci(ar)
    _ab, ablo, abhi, neff, _bk = sv.block_bootstrap_ci([ar])
    iid_w = ahi - alo
    blk_w = abhi - ablo
    ratio = blk_w / iid_w
    assert ratio > 1.3, f"block CI must be materially wider on AR(1); ratio={ratio:.2f}"
    assert neff < 0.6 * len(ar), f"N_eff must be << N on AR(1); got {neff:.0f}/{len(ar)}"


def test_block_widening_bigger_on_ar1_than_iid():
    """The widening on autocorrelated data must EXCEED the widening on IID data —
    the block bootstrap reacts to dependence, not to noise."""
    iid = sv.iid_series(400, sigma=1.0, mean=0.0, seed=11)
    ar = sv.ar1_series(400, phi=0.7, sigma=1.0, mean=0.0, seed=7)
    _i, ilo, ihi = sv.iid_bootstrap_ci(iid)
    _ib, iblo, ibhi, _n1, _k1 = sv.block_bootstrap_ci([iid])
    _a, alo, ahi = sv.iid_bootstrap_ci(ar)
    _ab, ablo, abhi, _n2, _k2 = sv.block_bootstrap_ci([ar])
    ratio_iid = (ibhi - iblo) / (ihi - ilo)
    ratio_ar = (abhi - ablo) / (ahi - alo)
    assert ratio_ar > ratio_iid + 0.2


def test_choose_block_length_data_driven():
    iid = sv.iid_series(400, sigma=1.0, seed=11)
    ar = sv.ar1_series(400, phi=0.7, sigma=1.0, seed=7)
    bl_iid = sv.choose_block_length([iid])
    bl_ar = sv.choose_block_length([ar])
    assert bl_iid >= 2 and bl_ar >= 2
    # autocorrelated data should pick a block at least as long
    assert bl_ar >= bl_iid


def test_variance_inflation_iid_near_one():
    iid = sv.iid_series(400, sigma=1.0, seed=11)
    vif = sv.variance_inflation([iid])
    assert 0.99 <= vif <= 1.5  # ~1 on IID (floored at 1.0)


def test_variance_inflation_ar1_above_one():
    ar = sv.ar1_series(400, phi=0.7, sigma=1.0, seed=7)
    vif = sv.variance_inflation([ar])
    assert vif > 1.5  # strong positive autocorrelation inflates variance
