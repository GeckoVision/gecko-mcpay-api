"""Tests for ingest_universe_candles.merge_forward — the forward-append logic.

Load-bearing: the collector must NEVER overwrite or reorder historical bars (a bug
here corrupts the deep tapes), and must append ONLY strictly-newer bars (no dupes).

Run: uv run pytest scripts/calibration/test_ingest_universe_candles.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_universe_candles as ing


def _bar(ts, close=1.0):
    return {"ts": ts, "open": close, "high": close, "low": close, "close": close, "volume": 1.0}


def test_merge_appends_only_newer():
    existing = [_bar(100), _bar(200), _bar(300)]
    fresh = [_bar(200, 9), _bar(300, 9), _bar(400), _bar(500)]  # 200/300 are dupes
    merged, added = ing.merge_forward(existing, fresh)
    ts = [c["ts"] for c in merged]
    assert added == 2  # only 400, 500
    assert ts == [100, 200, 300, 400, 500]  # ascending, no dupes
    # historical bars untouched (200's close stays 1.0, not the fresh 9)
    assert merged[1]["close"] == 1.0


def test_merge_into_empty_creates_full_series():
    merged, added = ing.merge_forward([], [_bar(10), _bar(20)])
    assert added == 2 and [c["ts"] for c in merged] == [10, 20]


def test_merge_nothing_newer_is_noop():
    existing = [_bar(100), _bar(200)]
    merged, added = ing.merge_forward(existing, [_bar(50), _bar(200)])
    assert added == 0 and len(merged) == 2
