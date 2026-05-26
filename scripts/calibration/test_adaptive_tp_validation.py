"""Tests for adaptive_tp_validation — the pure helpers (ATR% + clamp).

Load-bearing: ATR% must be causal + correct (a wrong ATR mis-sizes every adaptive
TP), and the clamp must bound the TP to the pre-registered [0.5, 3.0].

Run: uv run pytest scripts/calibration/test_adaptive_tp_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import adaptive_tp_validation as atp


def test_clamp_bounds():
    assert atp._clamp(0.1, 0.5, 3.0) == 0.5
    assert atp._clamp(9.0, 0.5, 3.0) == 3.0
    assert atp._clamp(1.5, 0.5, 3.0) == 1.5


def test_atr_pct_constant_range():
    # every bar: high=100.5, low=99.5, close=100 -> TR=1, ATR=1, ATR%=1.0
    n = 40
    c = {
        "high": [100.5] * n,
        "low": [99.5] * n,
        "close": [100.0] * n,
    }
    v = atp.atr_pct_at(c, 20)
    assert v is not None and abs(v - 1.0) < 1e-6


def test_atr_pct_needs_warmup():
    c = {"high": [1.0] * 5, "low": [1.0] * 5, "close": [1.0] * 5}
    assert atp.atr_pct_at(c, 3) is None  # i < ATR_PERIOD
