"""Tests for h1_reversion_validation — the pre-registered on-chain net-flow
reversion null.

Load-bearing: the causal trailing-decile percentile must be correct (a leaked
full-sample decile would invalidate the whole test), and the embedded self-test
(percentile + CPCV + block-bootstrap sanity) must pass.

Run: uv run pytest scripts/calibration/test_h1_reversion_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import h1_reversion_validation as h1


def test_self_test_passes():
    assert h1.self_test() is True


def test_percentile_endpoints_and_interpolation():
    vals = list(range(101))  # 0..100 sorted
    assert abs(h1.percentile(vals, 0.10) - 10.0) < 1e-9
    assert abs(h1.percentile(vals, 0.90) - 90.0) < 1e-9
    assert abs(h1.percentile(vals, 0.0) - 0.0) < 1e-9
    assert abs(h1.percentile(vals, 1.0) - 100.0) < 1e-9
    assert h1.percentile([42.0], 0.9) == 42.0  # single-value window


def test_fwd_return_is_forward_and_bounded():
    close = [100.0, 101.0, 102.0, 103.0, 104.0]
    assert abs(h1.fwd_return(close, 0, 4) - 4.0) < 1e-9  # (104-100)/100*100
    assert h1.fwd_return(close, 2, 4) is None  # 2+4 >= len -> no forward bar
