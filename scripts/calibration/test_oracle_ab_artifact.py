"""Tests for oracle_ab_artifact — the Oracle ON-vs-OFF A/B proof.

Load-bearing: arm metrics must compute win-rate/EV correctly, and the
block-bootstrap delta CI must flag a clearly-separated pair as CI-clean and an
overlapping pair as not-clean (or the "Oracle adds value" claim is unfounded).

Run: uv run pytest scripts/calibration/test_oracle_ab_artifact.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oracle_ab_artifact as ab


def _entries(verdict: str, pnls: list[float]) -> list[dict]:
    return [
        {"verdict": verdict, "pnl_real": p, "entry_ts_iso": f"2026-05-01 0{i}:00", "idx": i}
        for i, p in enumerate(pnls)
    ]


def test_arm_metrics_winrate_and_ev():
    m = ab.arm_metrics(_entries("act", [1.0, -1.0, 2.0, 0.0]), fee_rt=0.0)
    assert m["n"] == 4
    assert abs(m["win_rate"] - 0.5) < 1e-9  # 2 of 4 strictly > 0
    assert abs(m["ev_gross"] - 0.5) < 1e-9  # mean(1,-1,2,0)
    assert m["max_dd_net"] <= 0.0


def test_block_diff_ci_separates_clear_pair():
    # a clearly above b -> CI excludes zero
    a = [1.0, 1.2, 0.9, 1.1, 1.0, 1.3, 0.8, 1.1, 1.0, 1.2]
    b = [-1.0, -0.8, -1.2, -0.9, -1.1, -1.0, -0.7, -1.1, -1.0, -0.9]
    delta, lo, _hi, clean = ab.block_diff_ci(a, b)
    assert delta > 0 and clean and lo > 0


def test_block_diff_ci_overlapping_not_clean():
    # near-identical noisy arms -> CI straddles zero
    a = [0.1, -0.1, 0.2, -0.2, 0.0, 0.1, -0.1, 0.0]
    b = [0.0, 0.1, -0.1, 0.1, -0.2, 0.2, 0.0, -0.1]
    _delta, lo, hi, clean = ab.block_diff_ci(a, b)
    assert not clean and lo < 0 < hi
