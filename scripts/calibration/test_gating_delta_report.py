"""Unit tests for ``gating_delta_report`` — Sprint 3 S3-3.

Per ``feedback_lighter_tests`` — pure helpers + analyze_rule on synthetic
data, no JSONL files needed, no network.
"""

from __future__ import annotations

import pytest

from scripts.calibration import gating_delta_report as gdr


class TestClassifyRule:
    def test_act_rules_classified(self):
        for r in ("all_voices_aligned", "chop_high_conviction", "1h_adverse_high_conviction"):
            assert gdr.classify_rule(r) == "act"

    def test_decline_rules_classified(self):
        for r in (
            "risk_veto",
            "chart_below_threshold",
            "chop_below_high_bar",
            "1h_adverse_below_high_bar",
            "memory_contradicts",
            "chart_voice_missing",
        ):
            assert gdr.classify_rule(r) == "decline"

    def test_unknown_returns_unknown(self):
        assert gdr.classify_rule("totally_made_up_rule") == "unknown"
        assert gdr.classify_rule("") == "unknown"


class TestBootstrapMeanCi:
    def test_empty_returns_nan(self):
        import math

        low, high = gdr.bootstrap_mean_ci([])
        assert math.isnan(low) and math.isnan(high)

    def test_single_value_collapses(self):
        low, high = gdr.bootstrap_mean_ci([1.0], n_resamples=200)
        assert low == 1.0 and high == 1.0

    def test_ci_brackets_mean(self):
        values = [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]
        low, high = gdr.bootstrap_mean_ci(values, n_resamples=2000, seed=42)
        true_mean = sum(values) / len(values)
        assert low <= true_mean <= high


class TestAnalyzeRule:
    def _decision(self, did: str, rule: str, symbol: str = "X") -> dict:
        return {
            "decision_id": did,
            "coordinator": {"rule": rule, "action": gdr.classify_rule(rule)},
            "symbol": symbol,
            "ts": "2026-05-26T00:00:00Z",
            "voices": [],
            "indicators": {},
        }

    def _outcome(self, pnl: float, exit_reason: str = "take_profit") -> dict:
        return {
            "pnl_pct": pnl,
            "pnl_usd": pnl * 0.5,
            "exit_reason": exit_reason,
            "duration_min": 15.0,
        }

    def test_act_rule_with_outcomes_computes_pnl_stats(self):
        data = [
            (self._decision(f"d{i}", "all_voices_aligned"), self._outcome(pnl))
            for i, pnl in enumerate([+1.0, -0.5, +0.5, -1.0, +2.0])
        ]
        stats = gdr.analyze_rule("all_voices_aligned", data, total=5)
        assert stats.fire_count == 5
        assert stats.fire_fraction == 1.0
        assert stats.rule_kind == "act"
        assert stats.n_with_outcome == 5
        assert stats.mean_pnl_pct == pytest.approx(0.4)
        assert stats.win_rate == pytest.approx(0.6)
        assert stats.pnl_ci_low is not None
        assert stats.pnl_ci_high is not None
        # n=5 < MIN_N_FOR_PNL_CLAIM (30) → flagged as exploratory
        assert not stats.n_sufficient_for_pnl_claim

    def test_act_rule_meets_min_n_threshold(self):
        data = [
            (self._decision(f"d{i}", "all_voices_aligned"), self._outcome(0.5))
            for i in range(40)
        ]
        stats = gdr.analyze_rule("all_voices_aligned", data, total=40)
        assert stats.n_sufficient_for_pnl_claim

    def test_decline_rule_skips_pnl_computation(self):
        data = [
            (self._decision(f"d{i}", "risk_veto"), None)
            for i in range(10)
        ]
        stats = gdr.analyze_rule("risk_veto", data, total=10)
        assert stats.fire_count == 10
        assert stats.rule_kind == "decline"
        assert stats.n_with_outcome == 0
        assert stats.mean_pnl_pct is None

    def test_act_rule_without_outcomes_zero_n(self):
        # Decision was act, but the outcome row isn't present (mid-run snapshot)
        data = [
            (self._decision(f"d{i}", "all_voices_aligned"), None)
            for i in range(5)
        ]
        stats = gdr.analyze_rule("all_voices_aligned", data, total=5)
        assert stats.fire_count == 5
        assert stats.n_with_outcome == 0
        assert stats.mean_pnl_pct is None

    def test_act_rule_with_2_outcomes_does_not_compute_ci(self):
        # Below the n>=5 CI threshold — bootstrap skipped
        data = [
            (self._decision(f"d{i}", "all_voices_aligned"), self._outcome(pnl))
            for i, pnl in enumerate([1.0, -1.0])
        ]
        stats = gdr.analyze_rule("all_voices_aligned", data, total=2)
        assert stats.n_with_outcome == 2
        assert stats.mean_pnl_pct == 0.0
        assert stats.pnl_ci_low is None
        assert stats.pnl_ci_high is None

    def test_fire_fraction_respects_total(self):
        data = [
            (self._decision(f"d{i}", "risk_veto"), None) for i in range(3)
        ] + [
            (self._decision(f"e{i}", "all_voices_aligned"), self._outcome(0.5))
            for i in range(7)
        ]
        # Total = 10; risk_veto fires 3 → 30%
        stats = gdr.analyze_rule("risk_veto", data, total=10)
        assert stats.fire_fraction == 0.3
        # all_voices_aligned fires 7 → 70%
        stats2 = gdr.analyze_rule("all_voices_aligned", data, total=10)
        assert stats2.fire_fraction == 0.7
