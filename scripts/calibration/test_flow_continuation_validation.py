"""Tests for flow_continuation_validation — the rigor helpers.

Load-bearing: the two-sample delta CI must flag a clearly-separated pair as clean and
an overlapping pair as not-clean (the "beats rejected" gate depends on it).

Run: uv run pytest scripts/calibration/test_flow_continuation_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import flow_continuation_validation as fc


def test_arm_metrics():
    m = fc.arm([1.0, -1.0, 2.0, 0.0])
    assert m["n"] == 4 and abs(m["ev"] - 0.5) < 1e-9 and abs(m["win"] - 0.5) < 1e-9


def test_block_diff_ci_separates_clear_pair():
    a = [1.0, 1.1, 0.9, 1.2, 1.0, 1.1, 0.8, 1.0, 1.1, 1.0]
    b = [-1.0, -0.9, -1.1, -1.0, -0.8, -1.2, -1.0, -0.9, -1.1, -1.0]
    d, lo, _hi, clean = fc.block_diff_ci(a, b)
    assert d > 0 and clean and lo > 0


def test_block_diff_ci_overlap_not_clean():
    a = [0.1, -0.1, 0.2, -0.2, 0.0, 0.1, -0.1, 0.0]
    b = [0.0, 0.1, -0.1, 0.1, -0.2, 0.2, 0.0, -0.1]
    _d, lo, hi, clean = fc.block_diff_ci(a, b)
    assert not clean and lo < 0 < hi
