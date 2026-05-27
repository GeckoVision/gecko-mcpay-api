"""Unit tests for scripts.analysis.data_pipeline.transform.

Lean fixtures per feedback_lighter_tests: tiny synthetic DataFrames, no
end-to-end pipeline execution, no monkeypatch sprawl.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.analysis.data_pipeline import transform


def _entry_close_pair(decision_id: str, symbol: str, pnl_pct: float | None) -> list[dict]:
    """Synthesize a decisions.jsonl entry+close pair (mirrors real bot output)."""
    entry = {
        "decision_id": decision_id,
        "symbol": symbol,
        "signal_type": "price_breakout",
        "coordinator_action": "act",
        "coordinator_rule": "all_voices_aligned",
        "indicator_adx": 28.0,
        "indicator_regime_1h": "TREND-UP",
        "voice_chart_analyst_verdict": "bullish",
        "voice_chart_analyst_confidence": 0.85,
        "voice_risk_voice_verdict": "bullish",
        "voice_memory_voice_verdict": "abstain",
        "voice_regime_analyst_verdict": "abstain",
        "outcome_pnl_pct": None,
    }
    close = {
        "decision_id": decision_id,
        "symbol": None,  # close row drops most context per real bot behavior
        "outcome_pnl_pct": pnl_pct,
        "outcome_exit_reason": "take_profit" if (pnl_pct or 0) > 0 else "stop_loss",
    }
    return [entry, close]


# ---------------- collapse_decision_pairs ----------------


def test_collapse_pairs_empty_df_passthrough() -> None:
    assert transform.collapse_decision_pairs(pd.DataFrame()).empty


def test_collapse_pairs_merges_two_rows_into_one() -> None:
    df = pd.DataFrame(_entry_close_pair("d1", "WIF", 0.85))
    out = transform.collapse_decision_pairs(df)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["decision_id"] == "d1"
    assert r["symbol"] == "WIF"
    assert r["signal_type"] == "price_breakout"
    assert r["outcome_pnl_pct"] == 0.85
    assert r["outcome_exit_reason"] == "take_profit"


def test_collapse_pairs_preserves_decisions_that_didnt_act() -> None:
    df = pd.DataFrame(
        [
            {
                "decision_id": "no_act",
                "symbol": "WIF",
                "coordinator_action": "defer",
                "outcome_pnl_pct": None,
            }
        ]
    )
    out = transform.collapse_decision_pairs(df)
    assert len(out) == 1
    assert out.iloc[0]["coordinator_action"] == "defer"


def test_collapse_pairs_handles_three_rows_same_id_via_bfill_ffill() -> None:
    df = pd.DataFrame(
        [
            {"decision_id": "d1", "symbol": "X", "outcome_pnl_pct": None, "extra_col": None},
            {"decision_id": "d1", "symbol": None, "outcome_pnl_pct": 1.0, "extra_col": None},
            {"decision_id": "d1", "symbol": None, "outcome_pnl_pct": None, "extra_col": "late"},
        ]
    )
    out = transform.collapse_decision_pairs(df)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["symbol"] == "X"
    assert r["outcome_pnl_pct"] == 1.0
    assert r["extra_col"] == "late"


# ---------------- label_outcome ----------------


@pytest.mark.parametrize(
    "pnl,expected",
    [
        (1.5, "win"),
        (0.5, "win"),
        (0.49, "scratch"),
        (0.0, "scratch"),
        (-0.49, "scratch"),
        (-0.5, "loss"),
        (-3.1, "loss"),
        (None, "unknown"),
    ],
)
def test_label_outcome_thresholds(pnl, expected: str) -> None:
    df = pd.DataFrame([{"outcome_pnl_pct": pnl}])
    out = transform.label_outcome(df, min_win_pct=0.5)
    assert out["outcome_label"].iloc[0] == expected


def test_label_outcome_missing_col_returns_unknown_for_all() -> None:
    df = pd.DataFrame([{"x": 1}, {"x": 2}])
    out = transform.label_outcome(df)
    assert list(out["outcome_label"]) == ["unknown", "unknown"]


def test_label_outcome_custom_min_win_pct() -> None:
    df = pd.DataFrame([{"outcome_pnl_pct": 0.8}])
    # raise threshold above the value → no longer a win
    assert transform.label_outcome(df, min_win_pct=1.0).iloc[0]["outcome_label"] == "scratch"


# ---------------- annotate_regime ----------------


def test_annotate_regime_prefers_1h_over_base() -> None:
    df = pd.DataFrame(
        [
            {"indicator_regime_1h": "TREND-UP", "indicator_regime": "chop"},
            {"indicator_regime_1h": None, "indicator_regime": "TREND-DOWN"},
            {"indicator_regime_1h": "unknown", "indicator_regime": None},  # 'unknown' kept (not the null sentinel)
            {"indicator_regime_1h": None, "indicator_regime": None},
        ]
    )
    out = transform.annotate_regime(df)
    assert list(out["regime_at_entry"]) == ["trend_up", "trend_down", "unknown", None]


def test_annotate_regime_handles_missing_columns() -> None:
    df = pd.DataFrame([{"x": 1}])
    out = transform.annotate_regime(df)
    assert out["regime_at_entry"].iloc[0] is None


# ---------------- classify_voice_consensus ----------------


def test_classify_voice_consensus_basic_counts() -> None:
    df = pd.DataFrame(
        [
            {
                "voice_a_verdict": "bullish",
                "voice_b_verdict": "bullish",
                "voice_c_verdict": "bearish",
                "voice_d_verdict": "abstain",
            }
        ]
    )
    out = transform.classify_voice_consensus(df)
    r = out.iloc[0]
    assert r["voice_bull_count"] == 2
    assert r["voice_bear_count"] == 1
    assert r["voice_abstain_count"] == 1
    assert r["voice_neutral_count"] == 0
    assert r["voice_total_count"] == 4


def test_classify_voice_consensus_no_voice_cols_returns_zero_counts() -> None:
    df = pd.DataFrame([{"x": 1}])
    out = transform.classify_voice_consensus(df)
    assert out["voice_total_count"].iloc[0] == 0


# ---------------- join_with_outcome ----------------


def test_join_with_outcome_left_join_prefixes_ledger_cols() -> None:
    dec = pd.DataFrame([{"decision_id": "d1", "symbol": "WIF"}, {"decision_id": "d2", "symbol": "JTO"}])
    pos = pd.DataFrame(
        [
            {
                "decision_id": "d1",
                "symbol": "WIF-USDC",
                "entry_price": 2.3,
                "exit_price": 2.5,
                "pnl_pct": 1.5,
                "status": "closed",
                "mode": "paper",
                "exit_reason": "take_profit",
            }
        ]
    )
    out = transform.join_with_outcome(dec, pos)
    assert len(out) == 2
    assert "ledger_pnl_pct" in out.columns
    assert out.loc[out["decision_id"] == "d1", "ledger_pnl_pct"].iloc[0] == 1.5
    assert pd.isna(out.loc[out["decision_id"] == "d2", "ledger_pnl_pct"].iloc[0])


def test_join_with_outcome_empty_ledger_passthrough() -> None:
    dec = pd.DataFrame([{"decision_id": "d1", "symbol": "WIF"}])
    out = transform.join_with_outcome(dec, pd.DataFrame())
    assert len(out) == 1
    assert "ledger_pnl_pct" not in out.columns


# ---------------- derive_entry_timing_features ----------------


def test_derive_entry_timing_features_computes_distance_from_pre_high() -> None:
    decisions = pd.DataFrame(
        [
            {
                "decision_id": "d1",
                "ledger_symbol": "WIF-USDC",
                "ledger_entry_ts": pd.Timestamp("2026-05-26T12:00:00", tz="UTC"),
                "ledger_entry_price": 2.0,
            }
        ]
    )
    tele = pd.DataFrame(
        [
            {"symbol": "WIF", "ts": pd.Timestamp("2026-05-26T11:30:00", tz="UTC"), "price": 2.2},
            {"symbol": "WIF", "ts": pd.Timestamp("2026-05-26T11:50:00", tz="UTC"), "price": 1.9},
            {"symbol": "WIF", "ts": pd.Timestamp("2026-05-26T12:00:00", tz="UTC"), "price": 2.0},  # AT entry; excluded by `<`
        ]
    )
    out = transform.derive_entry_timing_features(decisions, tele, lookback_minutes=60)
    r = out.iloc[0]
    assert r["entry_pre_lookback_max_price"] == 2.2
    assert r["entry_pre_lookback_min_price"] == 1.9
    # entry 2.0 vs pre-high 2.2 → (2.2 - 2.0) / 2.2 * 100 = ~9.09%
    assert abs(r["entry_dist_from_pre_high_pct"] - 9.0909) < 0.01


def test_derive_entry_timing_features_missing_telemetry_returns_nans() -> None:
    decisions = pd.DataFrame(
        [
            {
                "decision_id": "d1",
                "ledger_symbol": "UNKNOWN",
                "ledger_entry_ts": pd.Timestamp("2026-05-26T12:00:00", tz="UTC"),
                "ledger_entry_price": 1.0,
            }
        ]
    )
    tele = pd.DataFrame(
        [{"symbol": "OTHER", "ts": pd.Timestamp("2026-05-26T11:30:00", tz="UTC"), "price": 5.0}]
    )
    out = transform.derive_entry_timing_features(decisions, tele)
    assert pd.isna(out["entry_dist_from_pre_high_pct"].iloc[0])


# ---------------- annotate_full ----------------


def test_annotate_full_end_to_end_pipeline() -> None:
    decisions = pd.DataFrame(_entry_close_pair("d1", "WIF", 0.85))
    positions = pd.DataFrame(
        [
            {
                "decision_id": "d1",
                "symbol": "WIF-USDC",
                "entry_price": 2.0,
                "exit_price": 2.017,
                "pnl_pct": 0.85,
                "status": "closed",
                "mode": "paper",
                "exit_reason": "take_profit",
            }
        ]
    )
    out = transform.annotate_full(decisions, positions)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["decision_id"] == "d1"
    assert r["outcome_label"] == "win"
    assert r["regime_at_entry"] == "trend_up"
    assert r["voice_bull_count"] == 2
    assert r["voice_abstain_count"] == 2
    assert r["ledger_pnl_pct"] == 0.85
