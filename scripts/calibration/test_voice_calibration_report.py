"""Unit tests for ``voice_calibration_report`` — Sprint 3 S3-1.

Per ``feedback_lighter_tests``: targeted, no big fixtures, no network. Tests
the pure-math helpers (Brier, Platt fit, isotonic fit, reliability bins) and
the voice-prediction transform; integration test (``calibrate_voice``) uses
synthetic ``VoiceObservation`` data so we don't depend on the live JSONL on
disk being a specific shape.
"""

from __future__ import annotations

import math

import pytest

from scripts.calibration import voice_calibration_report as vcr


class TestVoiceToPrediction:
    def test_bullish_uses_confidence_directly(self):
        assert vcr.voice_to_prediction("bullish", 0.85) == 0.85
        assert vcr.voice_to_prediction("BULLISH", 0.5) == 0.5

    def test_bearish_inverts(self):
        assert vcr.voice_to_prediction("bearish", 0.8) == pytest.approx(0.2)

    def test_neutral_returns_half(self):
        assert vcr.voice_to_prediction("neutral", 0.7) == 0.5

    def test_abstain_returns_none(self):
        assert vcr.voice_to_prediction("abstain", 0.0) is None

    def test_unknown_verdict_returns_none(self):
        assert vcr.voice_to_prediction("???", 0.5) is None
        assert vcr.voice_to_prediction("", 0.5) is None

    def test_clamps_confidence_to_unit_interval(self):
        assert vcr.voice_to_prediction("bullish", 1.5) == 1.0
        assert vcr.voice_to_prediction("bullish", -0.2) == 0.0

    def test_invalid_confidence_returns_none(self):
        assert vcr.voice_to_prediction("bullish", "not_a_number") is None
        assert vcr.voice_to_prediction("bullish", None) is None


class TestBrierScore:
    def test_perfect_classifier_is_zero(self):
        assert vcr.brier_score([1.0, 0.0, 1.0, 0.0], [1, 0, 1, 0]) == 0.0

    def test_inverted_classifier_is_one(self):
        assert vcr.brier_score([0.0, 1.0, 0.0, 1.0], [1, 0, 1, 0]) == 1.0

    def test_random_50_50_is_quarter(self):
        # All predictions 0.5, mix of outcomes → (0.5-0)² = (0.5-1)² = 0.25
        assert vcr.brier_score([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == 0.25

    def test_empty_returns_nan(self):
        assert math.isnan(vcr.brier_score([], []))


class TestFitPlatt:
    def test_degenerate_constant_prediction_returns_none(self):
        # all predictions 0.85; can't fit a slope
        assert vcr.fit_platt([0.85] * 10, [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]) is None

    def test_degenerate_all_same_outcome_returns_none(self):
        # mix of predictions, all wins → logistic regression fails to fit
        assert vcr.fit_platt([0.3, 0.5, 0.7, 0.9], [1, 1, 1, 1]) is None

    def test_well_separated_inputs_fit_positively(self):
        # high predictions → wins, low predictions → losses; slope should be +
        preds = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9] * 3
        outs = [0, 0, 0, 1, 1, 1] * 3
        fit = vcr.fit_platt(preds, outs)
        assert fit is not None
        assert fit["slope"] > 0


class TestFitIsotonic:
    def test_degenerate_returns_none(self):
        assert vcr.fit_isotonic([0.85] * 10, [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]) is None
        assert vcr.fit_isotonic([0.3, 0.5, 0.7], [1, 1, 1]) is None

    def test_monotonic_fit_returns_curve(self):
        preds = [0.1, 0.3, 0.5, 0.7, 0.9] * 4
        outs = [0, 0, 1, 1, 1] * 4
        curve = vcr.fit_isotonic(preds, outs)
        assert curve is not None
        cal = [pt["calibrated"] for pt in curve]
        # monotonic non-decreasing
        for i in range(len(cal) - 1):
            assert cal[i] <= cal[i + 1] + 1e-9


class TestReliabilityBins:
    def test_empty_returns_empty(self):
        assert vcr.reliability_bins([], []) == []

    def test_single_bin_collapse_for_constant_prediction(self):
        bins = vcr.reliability_bins([0.85] * 10, [1, 0, 1, 0, 1, 0, 1, 1, 1, 0])
        # all go in the one bin containing 0.85
        non_empty = [b for b in bins if b["n"] > 0]
        assert len(non_empty) == 1
        assert non_empty[0]["n"] == 10
        assert non_empty[0]["predicted_avg"] == pytest.approx(0.85)
        assert non_empty[0]["observed_avg"] == pytest.approx(0.6)

    def test_spread_predictions_fill_multiple_bins(self):
        preds = [0.1, 0.3, 0.5, 0.7, 0.9]
        outs = [0, 0, 1, 1, 1]
        bins = vcr.reliability_bins(preds, outs, n_bins=5)
        assert len(bins) == 5
        assert sum(b["n"] for b in bins) == 5


class TestBuildObservations:
    def test_excludes_decision_without_outcome(self):
        decisions = {
            "did1": {
                "decision_id": "did1",
                "voices": [{"name": "v1", "verdict": "bullish", "confidence": 0.8}],
                "indicators": {"regime_1h": "TREND-UP"},
                "coordinator": {"action": "act"},
                "symbol": "WIF",
                "ts": "t1",
            },
            "did2": {  # no outcome → excluded
                "decision_id": "did2",
                "voices": [{"name": "v1", "verdict": "bullish", "confidence": 0.8}],
                "indicators": {},
                "coordinator": {},
                "symbol": "JTO",
                "ts": "t2",
            },
        }
        outcomes = {"did1": {"pnl_pct": 1.5}}
        obs = vcr.build_observations(decisions, outcomes)
        assert len(obs) == 1
        assert obs[0].decision_id == "did1"
        assert obs[0].win == 1

    def test_loss_outcome_yields_win_zero(self):
        decisions = {
            "did1": {
                "decision_id": "did1",
                "voices": [{"name": "v1", "verdict": "bullish", "confidence": 0.8}],
                "indicators": {},
                "coordinator": {},
                "symbol": "x",
                "ts": "t",
            }
        }
        outcomes = {"did1": {"pnl_pct": -0.5}}
        obs = vcr.build_observations(decisions, outcomes)
        assert obs[0].win == 0


class TestCalibrateVoice:
    def _obs(self, voice: str, verdict: str, conf: float, pnl: float, **kw) -> vcr.VoiceObservation:
        pred = vcr.voice_to_prediction(verdict, conf)
        return vcr.VoiceObservation(
            decision_id=kw.get("did", "x"),
            voice_name=voice,
            verdict=verdict,
            confidence=conf,
            predicted_prob_win=pred if pred is not None else -1.0,
            win=1 if pnl > 0 else 0,
            pnl_pct=pnl,
            ts=kw.get("ts", "t"),
            symbol=kw.get("symbol", "X"),
            regime_1h=kw.get("regime_1h", ""),
            coordinator_action=kw.get("coordinator_action", "act"),
        )

    def test_no_directional_observations_returns_zero_directional(self):
        observations = [
            self._obs("voiceA", "abstain", 0.0, 1.0, did=f"d{i}") for i in range(5)
        ]
        result = vcr.calibrate_voice("voiceA", observations)
        assert result.n_directional == 0
        assert result.adequacy["reason"] == "no_directional_observations"

    def test_small_n_flags_n_too_small(self):
        observations = [
            self._obs("voiceA", "bullish", 0.85, +0.5, did=f"d{i}") for i in range(5)
        ] + [self._obs("voiceA", "bullish", 0.85, -0.5, did=f"e{i}") for i in range(3)]
        result = vcr.calibrate_voice("voiceA", observations)
        assert result.n_directional == 8
        assert not result.adequacy["n_sufficient"]
        assert "n_too_small" in result.adequacy["reason"]

    def test_constant_confidence_flags_variance_too_small(self):
        # 120 observations, all confidence 0.85 → variance is 0 → flagged
        observations = []
        for i in range(120):
            pnl = +0.5 if i % 2 == 0 else -0.5
            observations.append(self._obs("voiceA", "bullish", 0.85, pnl, did=f"d{i}"))
        result = vcr.calibrate_voice("voiceA", observations)
        assert result.n_directional == 120
        assert result.adequacy["n_sufficient"]
        assert not result.adequacy["variance_sufficient"]
        assert "stddev_too_small" in result.adequacy["reason"]

    def test_well_calibrated_voice_passes_all_checks(self):
        # 150 obs, BIMODAL confidence (mostly 0.1 / 0.9 — high discrimination)
        # with outcomes that match. This is what a *discriminative AND
        # calibrated* voice looks like: most predictions are confident, and
        # they're right. Brier floor for this distribution is ≈ 0.09 (E[p(1-p)]
        # at bimodal 0.1/0.9 ≈ 0.09), well under the 0.20 threshold.
        # Contrast with the uniform-spread case where Brier floors at ~0.22.
        import random

        random.seed(1729)
        observations = []
        for i in range(150):
            # Bimodal: ~75% of opinions are confident (0.85 or 0.15),
            # ~25% are mid-range (uniform 0.3..0.7).
            if i % 4 == 0:
                conf = round(random.uniform(0.3, 0.7), 2)
            elif i % 2 == 0:
                conf = 0.85
            else:
                conf = 0.15
            pnl = +1.0 if random.random() < conf else -1.0
            observations.append(self._obs("voiceA", "bullish", conf, pnl, did=f"d{i}"))
        result = vcr.calibrate_voice("voiceA", observations)
        assert result.n_directional == 150
        assert result.adequacy["n_sufficient"]
        assert result.adequacy["variance_sufficient"]
        # Brier well under the well-calibrated threshold for this distribution.
        assert result.brier_score < vcr.BRIER_WELL_CALIBRATED_THRESHOLD, (
            f"brier {result.brier_score:.4f} should be < {vcr.BRIER_WELL_CALIBRATED_THRESHOLD}"
        )
        assert result.adequacy["well_calibrated"]
        assert result.platt_scaling is not None
        assert result.isotonic_curve is not None
