"""Unit tests for ``voice_drift_report`` — Sprint 3 S3-4.

Per ``feedback_lighter_tests`` — synthetic VoiceObservation streams; no
JSONL files, no network. Tests cover the window splitter, KS analysis
adequacy branches, and the alarm-fire logic.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scripts.calibration import voice_drift_report as vdr


def _obs(voice: str, ts: dt.datetime, conf: float, verdict: str = "bullish") -> vdr.VoiceObservation:
    return vdr.VoiceObservation(voice_name=voice, ts=ts, confidence=conf, verdict=verdict)


REF = dt.datetime(2026, 5, 26, 12, 0, tzinfo=dt.UTC)


class TestSplitWindows:
    def test_partitions_by_timestamp(self):
        # 7d recent, 7d baseline, ref May 26 → recent = [May 19, May 26],
        # baseline = [May 12, May 19)
        obs = [
            _obs("v", REF - dt.timedelta(days=1), 0.5),  # recent
            _obs("v", REF - dt.timedelta(days=10), 0.5),  # baseline
            _obs("v", REF - dt.timedelta(days=20), 0.5),  # excluded (too old)
        ]
        recent, baseline = vdr.split_windows(obs, 7, 7, reference=REF)
        assert len(recent) == 1
        assert len(baseline) == 1
        # The 20-day-old observation is in neither window
        assert sum(len(w) for w in (recent, baseline)) == 2

    def test_boundary_inclusive_recent_exclusive_baseline(self):
        # Boundary at recent_start (REF - 7d) goes into RECENT (inclusive lower)
        # not baseline (exclusive upper).
        boundary = REF - dt.timedelta(days=7)
        obs = [_obs("v", boundary, 0.5)]
        recent, baseline = vdr.split_windows(obs, 7, 7, reference=REF)
        assert len(recent) == 1
        assert len(baseline) == 0


class TestAnalyzeVoice:
    def test_empty_window_reports_insufficient(self):
        result = vdr.analyze_voice("v", [], [], ks_threshold=0.2, alpha=0.05)
        assert result.n_recent == 0
        assert result.n_baseline == 0
        assert not result.drift_detected
        assert "insufficient_window" in result.adequacy["reason"]

    def test_below_min_samples_no_drift_alarm(self):
        # Distributions are obviously different but n is way below the floor
        recent = [_obs("v", REF, 0.9) for _ in range(5)]
        baseline = [_obs("v", REF - dt.timedelta(days=10), 0.1) for _ in range(5)]
        result = vdr.analyze_voice("v", recent, baseline, ks_threshold=0.2, alpha=0.05)
        # Drift should NOT be flagged even though KS will be high — n is too small
        assert not result.drift_detected
        # KS computes but alarm gated by adequacy check
        assert result.ks_statistic is not None
        assert "recent_window_too_small" in result.adequacy["reason"]

    def test_drift_detected_when_distributions_shift_significantly(self):
        # Make 50 recent observations centred at 0.9, 50 baseline at 0.1 —
        # KS will be ~1.0, p < 1e-20.
        recent = [_obs("v", REF, 0.9) for _ in range(50)]
        baseline = [_obs("v", REF - dt.timedelta(days=10), 0.1) for _ in range(50)]
        result = vdr.analyze_voice("v", recent, baseline, ks_threshold=0.2, alpha=0.05)
        assert result.drift_detected
        assert result.ks_statistic == pytest.approx(1.0)
        assert result.p_value < 0.05
        assert "drift_detected" in result.adequacy["reason"]

    def test_identical_distributions_no_drift(self):
        recent = [
            _obs("v", REF, 0.5 + (i % 5) * 0.1) for i in range(50)
        ]
        baseline = [
            _obs("v", REF - dt.timedelta(days=10), 0.5 + (i % 5) * 0.1) for i in range(50)
        ]
        result = vdr.analyze_voice("v", recent, baseline, ks_threshold=0.2, alpha=0.05)
        assert not result.drift_detected
        assert result.ks_statistic == 0.0
        assert "no_drift" in result.adequacy["reason"]

    def test_voice_filter_separates_streams(self):
        # Two voices in the same observation list — analyzing 'a' should NOT
        # include 'b's confidences.
        recent = [_obs("a", REF, 0.9)] * 50 + [_obs("b", REF, 0.1)] * 50
        baseline = [_obs("a", REF - dt.timedelta(days=10), 0.9)] * 50 + [
            _obs("b", REF - dt.timedelta(days=10), 0.1)
        ] * 50
        result_a = vdr.analyze_voice("a", recent, baseline, ks_threshold=0.2, alpha=0.05)
        assert result_a.n_recent == 50
        assert result_a.n_baseline == 50
        assert not result_a.drift_detected  # 'a' identical across windows
