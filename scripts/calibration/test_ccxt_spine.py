"""Unit tests for the pure helpers in ``ccxt_spine``.

Network helpers (``fetch_funding_history`` / ``fetch_ohlcv`` /
``pick_binance_universe``) are deliberately NOT tested here — they hit a live
venue and belong in opt-in contract tests. The pure helpers (``_dedup_by_ts``,
``paginate_windows``, ``detect_gaps``) carry the only branchy logic that needs
green-on-CI coverage.

Pattern matches ``feedback_lighter_tests`` — direct tests against the
pure functions, no fixtures, no mocks, no ccxt import overhead (the module
imports ccxt at top-level but the tests only call its pure helpers).
"""

from __future__ import annotations

import pytest

from scripts.calibration import ccxt_spine as cs


class TestDedupByTs:
    def test_passthrough_unique_ascending(self):
        rows = [{"ts": 1, "v": "a"}, {"ts": 2, "v": "b"}, {"ts": 3, "v": "c"}]
        assert cs._dedup_by_ts(rows) == rows

    def test_dedup_keeps_last(self):
        rows = [
            {"ts": 1, "v": "first"},
            {"ts": 1, "v": "later"},
            {"ts": 2, "v": "x"},
        ]
        assert cs._dedup_by_ts(rows) == [{"ts": 1, "v": "later"}, {"ts": 2, "v": "x"}]

    def test_sorts_unsorted_input(self):
        rows = [{"ts": 3, "v": "c"}, {"ts": 1, "v": "a"}, {"ts": 2, "v": "b"}]
        out = cs._dedup_by_ts(rows)
        assert [r["ts"] for r in out] == [1, 2, 3]

    def test_skips_rows_with_no_ts(self):
        rows = [{"ts": 1, "v": "a"}, {"v": "no-ts"}, {"ts": 2, "v": "b"}]
        out = cs._dedup_by_ts(rows)
        assert [r["ts"] for r in out] == [1, 2]

    def test_skips_rows_with_non_numeric_ts(self):
        rows = [{"ts": 1}, {"ts": "string"}, {"ts": None}, {"ts": 2}]
        out = cs._dedup_by_ts(rows)
        assert [r["ts"] for r in out] == [1, 2]

    def test_custom_ts_key(self):
        rows = [{"time": 2}, {"time": 1}]
        out = cs._dedup_by_ts(rows, ts_key="time")
        assert [r["time"] for r in out] == [1, 2]

    def test_empty_input(self):
        assert cs._dedup_by_ts([]) == []


class TestPaginateWindows:
    def test_basic_clean_division(self):
        assert cs.paginate_windows(0, 100, 30) == [(0, 30), (30, 60), (60, 90), (90, 100)]

    def test_single_window_fits_exactly(self):
        assert cs.paginate_windows(0, 30, 30) == [(0, 30)]

    def test_single_window_partial(self):
        assert cs.paginate_windows(0, 20, 30) == [(0, 20)]

    def test_no_windows_when_since_ge_end(self):
        assert cs.paginate_windows(100, 100, 30) == []
        assert cs.paginate_windows(150, 100, 30) == []

    def test_no_windows_when_window_zero_or_negative(self):
        assert cs.paginate_windows(0, 100, 0) == []
        assert cs.paginate_windows(0, 100, -10) == []

    def test_non_zero_start(self):
        assert cs.paginate_windows(1_000, 1_100, 30) == [
            (1000, 1030),
            (1030, 1060),
            (1060, 1090),
            (1090, 1100),
        ]


class TestDetectGaps:
    def test_no_gaps_uniform_spacing(self):
        rows = [{"ts": 0}, {"ts": 100}, {"ts": 200}, {"ts": 300}]
        assert cs.detect_gaps(rows, expected_step_ms=100) == []

    def test_detects_single_gap_with_explicit_step(self):
        rows = [{"ts": 0}, {"ts": 100}, {"ts": 400}, {"ts": 500}]
        out = cs.detect_gaps(rows, expected_step_ms=100)
        assert len(out) == 1
        assert out[0]["after"] == 100
        assert out[0]["before"] == 400
        assert out[0]["missing_steps"] == 2
        assert out[0]["duration_ms"] == 300

    def test_infers_modal_step(self):
        # Most steps are 100; one gap of 400 should be detected.
        rows = [{"ts": 0}, {"ts": 100}, {"ts": 200}, {"ts": 600}, {"ts": 700}]
        out = cs.detect_gaps(rows)  # no expected_step_ms; infer 100
        assert len(out) == 1
        assert out[0]["after"] == 200
        assert out[0]["before"] == 600

    def test_empty_and_single_row_return_empty(self):
        assert cs.detect_gaps([]) == []
        assert cs.detect_gaps([{"ts": 0}]) == []

    def test_tolerates_50pct_overrun_without_flagging(self):
        # Step 100 modal; a single 140-step is within the 1.5x threshold => no gap.
        rows = [{"ts": 0}, {"ts": 100}, {"ts": 240}, {"ts": 340}]
        out = cs.detect_gaps(rows, expected_step_ms=100)
        assert out == []  # 140 < 100 * 1.5

    def test_custom_ts_key(self):
        rows = [{"time": 0}, {"time": 100}, {"time": 400}]
        out = cs.detect_gaps(rows, ts_key="time", expected_step_ms=100)
        assert len(out) == 1


class TestVenueRegistry:
    def test_known_venues_resolve_to_ccxt_ids(self):
        # No network call — just confirm the IDs map to attributes on the
        # ccxt module so misnamed venue ids fail loudly at unit-test time.
        import ccxt

        for name, spec in cs.VENUE_IDS.items():
            assert hasattr(ccxt, spec["id"]), f"{name} -> ccxt.{spec['id']} missing"

    def test_unknown_venue_raises(self):
        with pytest.raises(ValueError, match="unknown venue"):
            cs._venue("not_a_real_venue")
