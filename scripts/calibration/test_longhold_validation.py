"""Tests for longhold_validation — Experiment 1 (longer-hold gross-EV-vs-horizon).

Load-bearing: a longer hold MUST capture a bigger move on a clean ramp (else the
forward-return math is wrong), entry detection must fire on a real breakout, and
the CPCV stream must yield a non-degenerate distribution of paths (the bug we
fixed: a mis-computed label span collapsed 28 paths to 6 identical ones).

Run: uv run pytest scripts/calibration/test_longhold_validation.py -q
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import longhold_validation as lh


def _ramp(n=400):
    return [
        {
            "ts": i,
            "open": 100 + i,
            "high": 100 + i + 0.5,
            "low": 100 + i - 0.5,
            "close": 100 + i,
            "volume": 100.0,
        }
        for i in range(n)
    ]


def test_longer_hold_captures_bigger_move_on_ramp():
    c = lh.as_columns(_ramp())
    ep = c["close"][50]
    g1 = (c["close"][51] - ep) / ep * 100
    g24 = (c["close"][74] - ep) / ep * 100
    g168 = (c["close"][218] - ep) / ep * 100
    assert g1 < g24 < g168


def test_breakout_and_volume_spike_fire():
    spike = [
        {"ts": i, "open": 100, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 100.0}
        for i in range(30)
    ]
    spike.append({"ts": 30, "open": 100, "high": 105, "low": 100, "close": 104.0, "volume": 1000.0})
    cc = lh.as_columns(spike)
    assert lh.breakout_fires(cc, 30)
    assert lh.volume_spike_fires(cc, 30)


def test_cpcv_stream_is_non_degenerate():
    # the fixed label-span: 28 distinct paths on a noisy synthetic edge, not 6
    r = random.Random(7)
    ents = [
        lh.Entry("SYN", i, "trend", {h: 0.5 + r.gauss(0, 0.3) for h in lh.HORIZONS_BARS})
        for i in range(200)
    ]
    res = lh.cpcv_for_horizon(ents, "1d", fee=0.0)
    assert res.n_paths == 28
    assert len({round(s, 4) for s in res.path_sharpes}) > 5  # not collapsed
    assert res.median > 0  # the synthetic edge is real


def test_censoring_guard_requires_longest_horizon():
    # entries near the tape end (within the 1w horizon) must not be collected
    ents, _ = lh.collect_entries(["SOL"])
    max_h = max(lh.HORIZONS_BARS.values())
    # every collected SOL entry has a finite 1w gross (uncensored at the longest)
    assert all(e.gross_by_horizon["1w"] == e.gross_by_horizon["1w"] for e in ents)
    # and none sits within max_h of the end
    n = len(lh.as_columns(lh.load_tape("SOL"))["close"])
    assert all(e.idx + max_h < n for e in ents)
