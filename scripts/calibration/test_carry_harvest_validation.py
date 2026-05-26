"""Tests for carry_harvest_validation.carry_series — the leakage-clean harvest logic.

Load-bearing: side must use a STRICTLY-PRIOR window (no look-ahead), harvest =
side*funding, and the flip cost must be charged exactly on side changes (the churn
that drove the verdict).

Run: uv run pytest scripts/calibration/test_carry_harvest_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import carry_harvest_validation as ch


def _recs(rates):
    return [{"ts": i * 3_600_000, "fundingRate": r, "premium": 0.0} for i, r in enumerate(rates)]


def test_persistent_positive_no_flips_harvests_funding():
    # constant positive funding -> side stays +1 after warmup -> harvest each hour, no flips
    rates = [0.001] * (ch.W + 5)
    out = ch.carry_series(_recs(rates), flip_cost=0.002)
    assert len(out) == 5
    # first hour: side flips 0->+1 -> charged once; net = 0.001 - 0.002
    assert abs(out[0][1] - (0.001 - 0.002)) < 1e-9
    # subsequent: side holds -> just harvest +0.001, no cost
    assert all(abs(v - 0.001) < 1e-9 for _, v in out[1:])


def test_sign_persistence_no_lookahead():
    # trailing window is strictly prior: a sign change at t doesn't use funding[t]
    rates = [0.001] * ch.W + [-0.001]  # trailing mean over [0..W-1] is +, so side[W]=+1
    out = ch.carry_series(_recs(rates), flip_cost=0.0)
    # at t=W: side=+1 (from prior +), funding=-0.001 -> harvest = +1 * -0.001 = -0.001 (a loss, no lookahead)
    assert abs(out[0][1] - (-0.001)) < 1e-9
