"""Tests for overfitting_rigor — CPCV / PBO / DSR per López de Prado.

The load-bearing tests are the DISCRIMINATING ones: each primitive must separate
a genuine edge from noise. A CPCV that says "positive" on noise, a PBO that stays
low on noise, or a DSR that doesn't deflate for trial count would all be cosmetic
— and would let an overfit variant through the gate the skill exists to hold.

Run: uv run pytest scripts/calibration/test_overfitting_rigor.py -q
"""

from __future__ import annotations

import math
import os
import random
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import overfitting_rigor as ofr


# ── Gaussian helpers (DSR/PSR depend on these; no scipy) ─────────────
def test_normal_cdf_known_points():
    assert abs(ofr.normal_cdf(0.0) - 0.5) < 1e-12
    assert abs(ofr.normal_cdf(1.959964) - 0.975) < 1e-4
    assert abs(ofr.normal_cdf(-1.959964) - 0.025) < 1e-4


def test_normal_ppf_roundtrips_cdf():
    for p in (0.01, 0.25, 0.5, 0.7, 0.99):
        assert abs(ofr.normal_cdf(ofr.normal_ppf(p)) - p) < 1e-6


# ── Sharpe ───────────────────────────────────────────────────────────
def test_sharpe_zero_on_constant():
    assert ofr.sharpe_ratio([1.0] * 10) == 0.0


def test_sharpe_sign_tracks_drift():
    assert ofr.sharpe_ratio([0.1 + 0.001 * i for i in range(50)]) > 0
    assert ofr.sharpe_ratio([-0.1 - 0.001 * i for i in range(50)]) < 0


# ── CPCV: distribution, not a point; purge drops overlap ─────────────
def _stream(n_groups, per, mean, sd, seed, label_offset=0):
    rng = random.Random(seed)
    out = []
    for g in range(n_groups):
        for _ in range(per):
            out.append((g, mean + rng.gauss(0, sd), min(g + label_offset, n_groups - 1)))
    return out


def test_cpcv_yields_combinatorial_path_count():
    res = ofr.cpcv_paths(_stream(8, 40, 0.5, 0.3, 7), n_groups=8, n_test=2)
    # C(8,2) = 28 selections; all have admissible samples here
    assert res.n_paths == 28


def test_cpcv_separates_edge_from_noise():
    edge = ofr.cpcv_paths(_stream(8, 40, 0.5, 0.3, 7), n_groups=8, n_test=2)
    noise = ofr.cpcv_paths(_stream(8, 40, 0.0, 1.0, 9), n_groups=8, n_test=2)
    assert edge.median > 0 and edge.pct_paths_negative < 0.10
    assert abs(noise.median) < 0.30 and noise.pct_paths_negative > 0.25


def test_cpcv_purge_drops_label_spill():
    # group-1 sample with label ending in group 2 must never enter the {0,1} path
    spill = [(0, 1.0, 0), (1, 1.0, 1), (1, 99.0, 2)]
    r = ofr.cpcv_paths(spill, n_groups=3, n_test=2, embargo_groups=0)
    assert all(s < 50 for s in r.path_sharpes) or r.n_paths == 0


def test_cpcv_embargo_excludes_following_block_labels():
    # embargo=1: a sample whose label ends one group after a test group is dropped
    s = [(0, 1.0, 1)]  # group 0 in test, label ends group 1 (embargoed)
    r = ofr.cpcv_paths(s, n_groups=2, n_test=1, embargo_groups=1)
    # single sample anyway can't make a >=2 path, but it must not be admitted
    assert r.n_paths == 0


# ── PBO: low for a real edge, elevated for noise ─────────────────────
def test_pbo_low_when_one_variant_genuinely_best():
    rng = random.Random(3)
    V = 6
    mat = []
    for _ in range(40):
        mat.append([0.4 + rng.gauss(0, 0.5)] + [rng.gauss(0, 0.5) for _ in range(V - 1)])
    assert ofr.pbo(mat, n_partitions=8).pbo < 0.30


def test_pbo_elevated_for_noise_on_average():
    pbos = []
    for s in range(12):
        rng = random.Random(500 + s)
        mat = [[rng.gauss(0, 1.0) for _ in range(6)] for _ in range(40)]
        pbos.append(ofr.pbo(mat, n_partitions=8).pbo)
    assert st.mean(pbos) >= 0.30


def test_pbo_needs_two_variants():
    assert math.isnan(ofr.pbo([[1.0], [2.0]], n_partitions=2).pbo)


# ── DSR: deflates for honest trial count ─────────────────────────────
def test_dsr_in_unit_interval():
    rng = random.Random(11)
    ret = [0.3 + rng.gauss(0, 1.0) for _ in range(200)]
    d = ofr.deflated_sharpe_ratio(ret, [ofr.sharpe_ratio(ret), 0.0])
    assert 0.0 <= d.dsr <= 1.0


def test_dsr_falls_as_trials_rise():
    rng = random.Random(11)
    ret = [0.3 + rng.gauss(0, 1.0) for _ in range(200)]
    sr = ofr.sharpe_ratio(ret)
    few = ofr.deflated_sharpe_ratio(ret, [sr, 0.0])
    many = ofr.deflated_sharpe_ratio(ret, [sr] + [rng.gauss(0, 0.3) for _ in range(50)])
    # the whole point of DSR: more variants tried -> higher benchmark -> lower DSR
    assert many.sr_star >= few.sr_star
    assert many.dsr <= few.dsr + 1e-9


def test_dsr_strong_real_edge_passes_when_few_trials():
    # a strong, long, clean edge with only 2 trials should clear 0.95
    rng = random.Random(5)
    ret = [0.15 + rng.gauss(0, 0.5) for _ in range(500)]
    d = ofr.deflated_sharpe_ratio(ret, [ofr.sharpe_ratio(ret), 0.05])
    assert d.dsr >= 0.95


# ── Verdict gating: never DEPLOY on a failed gate ────────────────────
def _cpcv(median, pct_neg):
    return ofr.CPCVResult(8, 2, 28, [], median, median - 0.3, median + 0.3, pct_neg, 30.0)


def test_verdict_deploy_only_when_all_gates_clear():
    v = ofr.make_verdict(
        "ok",
        _cpcv(1.2, 0.0),
        ofr.DSRResult(0.99, 1.2, 0.1, 5, 200, 0, 3),
        ofr.PBOResult(0.05, 28, 6, 1.0),
        -0.1,
        12.0,
    )
    assert v.verdict == "DEPLOY"


def test_verdict_rejects_high_pbo():
    v = ofr.make_verdict(
        "bad",
        _cpcv(1.2, 0.0),
        ofr.DSRResult(0.99, 1.2, 0.1, 5, 200, 0, 3),
        ofr.PBOResult(0.60, 28, 6, -0.5),
        -0.1,
        12.0,
    )
    assert v.verdict != "DEPLOY"


def test_verdict_rejects_low_dsr_and_many_neg_paths():
    v = ofr.make_verdict(
        "bad",
        _cpcv(0.1, 0.40),
        ofr.DSRResult(0.20, 0.1, 0.5, 50, 200, 0, 3),
        ofr.PBOResult(0.55, 28, 6, -0.3),
        -2.0,
        0.1,
    )
    assert v.verdict == "REJECT"


def test_verdict_rejects_nan_metric():
    v = ofr.make_verdict(
        "nan",
        _cpcv(float("nan"), float("nan")),
        ofr.DSRResult(0.99, 1.2, 0.1, 5, 200, 0, 3),
        ofr.PBOResult(0.05, 28, 6, 1.0),
        0.0,
        0.0,
    )
    assert v.verdict == "REJECT"


# ── Max drawdown sign convention ─────────────────────────────────────
def test_max_drawdown_sign():
    assert ofr.max_drawdown([0.1, 0.2, 0.1]) == 0.0
    assert ofr.max_drawdown([1.0, -0.5, -0.5]) <= -1.0 + 1e-9
