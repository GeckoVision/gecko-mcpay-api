"""Tests for xsectional_validation — Experiment 2 (cross-sectional relative-value).

Load-bearing: momentum must long the riser / short the faller on a clean
cross-section (else the ranking is inverted); reversion must do the opposite and
LOSE on a persistent trend; the panel must be timestamp-aligned; and the L/S
spread must equal long-basket minus short-basket exactly (the dollar-neutral
definition the report leans on).

Run: uv run pytest scripts/calibration/test_xsectional_validation.py -q
"""

from __future__ import annotations

import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import xsectional_validation as xs


def _cross_section(n=400):
    return {
        "A": [100 * (1.001**i) for i in range(n)],  # steady up
        "B": [100 * (0.999**i) for i in range(n)],  # steady down
        "C": [100.0 for _ in range(n)],  # flat
    }, list(range(n))


def test_momentum_longs_riser_shorts_faller():
    closes, ts = _cross_section()
    saved = xs.SYMBOLS
    xs.SYMBOLS = ["A", "B", "C"]
    try:
        ranked = xs.rank_symbols(closes, 200, 12, "momentum")
        assert ranked is not None and ranked[0][0] == "A" and ranked[-1][0] == "B"
        vr = xs.run_variant(closes, ts, "momentum", lookback=12, hold=12, k=1)
        assert st.mean(vr.spread) > 0  # long A, short B -> positive spread
    finally:
        xs.SYMBOLS = saved


def test_reversion_loses_on_persistent_trend():
    closes, ts = _cross_section()
    saved = xs.SYMBOLS
    xs.SYMBOLS = ["A", "B", "C"]
    try:
        vr = xs.run_variant(closes, ts, "reversion", lookback=12, hold=12, k=1)
        # reversion longs the loser (B, falling) on a trend that persists -> loses
        assert st.mean(vr.spread) < 0
    finally:
        xs.SYMBOLS = saved


def test_spread_is_long_minus_short_exactly():
    closes, ts = _cross_section()
    saved = xs.SYMBOLS
    xs.SYMBOLS = ["A", "B", "C"]
    try:
        vr = xs.run_variant(closes, ts, "momentum", lookback=12, hold=12, k=1)
        for lo, sh, sp in zip(vr.long_only, vr.short_basket, vr.spread, strict=True):
            assert abs(sp - (lo - sh)) < 1e-9
    finally:
        xs.SYMBOLS = saved


def test_panel_is_timestamp_aligned():
    ts, closes = xs.load_aligned()
    assert all(len(cl) == len(ts) for cl in closes.values())
    assert len(set(ts)) == len(ts)  # strictly unique, sorted clock
    assert ts == sorted(ts)


def test_no_overlap_rebalance_stride_equals_hold():
    # consecutive rebalance bars differ by at least `hold` (non-overlapping blocks)
    closes, ts = _cross_section()
    saved = xs.SYMBOLS
    xs.SYMBOLS = ["A", "B", "C"]
    try:
        vr = xs.run_variant(closes, ts, "momentum", lookback=12, hold=12, k=1)
        diffs = [b2 - b1 for b1, b2 in zip(vr.bar_index, vr.bar_index[1:], strict=False)]
        assert all(d >= 12 for d in diffs)
    finally:
        xs.SYMBOLS = saved


def test_cpcv_series_yields_distribution():
    closes, ts = _cross_section()
    saved = xs.SYMBOLS
    xs.SYMBOLS = ["A", "B", "C"]
    try:
        vr = xs.run_variant(closes, ts, "momentum", lookback=12, hold=12, k=1)
        cp = xs.cpcv_series(vr.spread, vr.bar_index, hold=12)
        assert cp.n_paths == 28
    finally:
        xs.SYMBOLS = saved
