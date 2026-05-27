"""Unit tests for scripts.analysis.data_pipeline.extract.

Per feedback_lighter_tests: tiny synthetic fixtures, no monkeypatch sprawl. Each
test exercises one reader against a tmp-path fixture; no real bot data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.analysis.data_pipeline import extract


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


# ---------------- read_decisions ----------------


def test_read_decisions_empty_dir_returns_empty_df(tmp_path: Path) -> None:
    assert extract.read_decisions(tmp_path).empty


def test_read_decisions_missing_dir_returns_empty_df(tmp_path: Path) -> None:
    assert extract.read_decisions(tmp_path / "nonexistent").empty


def test_read_decisions_flattens_voices_indicators_oracle(tmp_path: Path) -> None:
    run = tmp_path / "run_abc"
    run.mkdir()
    row = {
        "decision_id": "d1",
        "run_id": "run_abc",
        "symbol": "JTO",
        "symbol_group": "majors",
        "ts": "2026-05-26T05:15:55.208027+00:00",
        "signal": {"fired": True, "type": "price_breakout"},
        "indicators": {"adx": 28.0, "rsi": 65.0, "chop": 42.0},
        "voices": [
            {"name": "chart_analyst", "verdict": "bullish", "confidence": 0.85, "reasoning": "strong"},
            {"name": "memory_voice", "verdict": "abstain", "confidence": 0.0, "reasoning": "cold"},
        ],
        "oracle": {"verdict": "defer", "confidence": 0.65, "citations": 7, "grounded": True},
        "coordinator": {"action": "act", "rule": "all_voices_aligned"},
        "outcome": {"pnl_pct": 0.5, "pnl_usd": 0.25},
    }
    _write_jsonl(run / "decisions.jsonl", [row])
    df = extract.read_decisions(tmp_path)
    assert len(df) == 1
    r = df.iloc[0]
    assert r["decision_id"] == "d1"
    assert r["symbol"] == "JTO"
    assert bool(r["signal_fired"]) is True
    assert r["signal_type"] == "price_breakout"
    assert r["indicator_adx"] == 28.0
    assert r["indicator_chop"] == 42.0
    assert r["voice_chart_analyst_verdict"] == "bullish"
    assert r["voice_chart_analyst_confidence"] == 0.85
    assert r["voice_memory_voice_verdict"] == "abstain"
    assert r["oracle_verdict"] == "defer"
    assert bool(r["oracle_grounded"]) is True
    assert r["coordinator_action"] == "act"
    assert r["outcome_pnl_pct"] == 0.5
    assert df["ts"].dt.tz is not None  # UTC tz preserved


def test_read_decisions_skips_malformed_jsonl_lines(tmp_path: Path) -> None:
    run = tmp_path / "run_xyz"
    run.mkdir()
    (run / "decisions.jsonl").write_text(
        json.dumps({"decision_id": "ok", "symbol": "X"}) + "\nNOT-JSON\n"
        + json.dumps({"decision_id": "ok2", "symbol": "Y"}) + "\n"
    )
    df = extract.read_decisions(tmp_path)
    assert sorted(df["decision_id"]) == ["ok", "ok2"]


def test_read_decisions_handles_runs_without_decisions_file(tmp_path: Path) -> None:
    (tmp_path / "empty_run").mkdir()  # no decisions.jsonl
    populated = tmp_path / "populated"
    populated.mkdir()
    _write_jsonl(populated / "decisions.jsonl", [{"decision_id": "d1", "symbol": "S"}])
    df = extract.read_decisions(tmp_path)
    assert len(df) == 1


# ---------------- read_artifacts ----------------


def test_read_artifacts_empty_glob_returns_empty_df(tmp_path: Path) -> None:
    assert extract.read_artifacts(str(tmp_path / "no_match_*.jsonl")).empty


def test_read_artifacts_flattens_payload_and_records_source_file(tmp_path: Path) -> None:
    f = tmp_path / "artifact_20260526.jsonl"
    rows = [
        {
            "decision_id": "d1",
            "kind": "local_panel",
            "ts": "2026-05-26T00:00:46.660729+00:00",
            "payload": {"instrument": "JUP", "action": "decline", "voice_count": 4},
        },
        {
            "decision_id": "d2",
            "kind": "candidate_blocked",
            "ts": "2026-05-26T00:01:00+00:00",
            "payload": {"instrument": "BONK", "reason": "btc_overlay"},
        },
    ]
    _write_jsonl(f, rows)
    df = extract.read_artifacts(str(tmp_path / "artifact_*.jsonl"))
    assert len(df) == 2
    assert set(df["kind"]) == {"local_panel", "candidate_blocked"}
    assert df["source_file"].iloc[0] == "artifact_20260526.jsonl"
    assert df["payload_instrument"].iloc[0] == "JUP"
    assert df["payload_voice_count"].iloc[0] == 4
    assert df["payload_reason"].iloc[1] == "btc_overlay"


def test_read_artifacts_filters_by_kind(tmp_path: Path) -> None:
    f = tmp_path / "artifact_X.jsonl"
    _write_jsonl(
        f,
        [
            {"decision_id": "d1", "kind": "local_panel", "ts": "2026-05-26T00:00:00+00:00", "payload": {}},
            {"decision_id": "d2", "kind": "heartbeat", "ts": "2026-05-26T00:01:00+00:00", "payload": {}},
            {"decision_id": "d3", "kind": "candidate_blocked", "ts": "2026-05-26T00:02:00+00:00", "payload": {}},
        ],
    )
    df = extract.read_artifacts(str(tmp_path / "artifact_*.jsonl"), kinds=["local_panel", "candidate_blocked"])
    assert sorted(df["kind"]) == ["candidate_blocked", "local_panel"]


def test_read_artifacts_concats_across_files_in_filename_order(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "artifact_20260525.jsonl",
        [{"decision_id": "early", "kind": "k", "ts": "2026-05-25T00:00:00+00:00", "payload": {}}],
    )
    _write_jsonl(
        tmp_path / "artifact_20260526.jsonl",
        [{"decision_id": "late", "kind": "k", "ts": "2026-05-26T00:00:00+00:00", "payload": {}}],
    )
    df = extract.read_artifacts(str(tmp_path / "artifact_*.jsonl"))
    assert list(df["decision_id"]) == ["early", "late"]


# ---------------- read_bot_state ----------------


def test_read_bot_state_missing_file_returns_empty_df(tmp_path: Path) -> None:
    assert extract.read_bot_state(tmp_path / "no.json").empty


def test_read_bot_state_unnests_signal_data_and_coerces_ts(tmp_path: Path) -> None:
    p = tmp_path / "bot_state.json"
    p.write_text(
        json.dumps(
            {
                "positions": [
                    {
                        "token": "T1",
                        "symbol": "JUP-USDC",
                        "entry_price": 0.207,
                        "entry_ts": "2026-05-24T06:10:38",
                        "exit_ts": "2026-05-24T07:00:00",
                        "status": "closed",
                        "pnl_pct": 1.5,
                        "pnl_usd": 0.7,
                        "signal_data": {
                            "primitive": "volume_spike",
                            "multiplier_observed": 2.35,
                            "regime_1h": "TREND-UP",
                        },
                    }
                ]
            }
        )
    )
    df = extract.read_bot_state(p)
    assert len(df) == 1
    r = df.iloc[0]
    assert r["symbol"] == "JUP-USDC"
    assert r["signal_primitive"] == "volume_spike"
    assert r["signal_multiplier_observed"] == 2.35
    assert r["signal_regime_1h"] == "TREND-UP"
    assert df["entry_ts"].dt.tz is not None


def test_read_bot_state_handles_missing_signal_data(tmp_path: Path) -> None:
    p = tmp_path / "bot_state.json"
    p.write_text(json.dumps({"positions": [{"token": "T", "symbol": "X", "entry_price": 1.0}]}))
    df = extract.read_bot_state(p)
    assert len(df) == 1
    assert "signal_primitive" not in df.columns  # no signal_data → no signal_ cols


def test_read_bot_state_handles_empty_positions(tmp_path: Path) -> None:
    p = tmp_path / "bot_state.json"
    p.write_text(json.dumps({"positions": []}))
    assert extract.read_bot_state(p).empty


# ---------------- read_eval_telemetry ----------------


def test_read_eval_telemetry_empty_glob_returns_empty_df(tmp_path: Path) -> None:
    assert extract.read_eval_telemetry(str(tmp_path / "no_match_*.jsonl")).empty


def test_read_eval_telemetry_loads_rows_flat(tmp_path: Path) -> None:
    f = tmp_path / "eval_telemetry_20260526.jsonl"
    _write_jsonl(
        f,
        [
            {
                "ts": "2026-05-26T18:37:20.890180+00:00",
                "symbol": "PYTH",
                "price": 0.040,
                "rsi": 41.42,
                "action": "no_signal",
            },
            {
                "ts": "2026-05-26T18:37:21.000000+00:00",
                "symbol": "WIF",
                "price": 2.3,
                "rsi": 65.0,
                "action": "no_signal",
            },
        ],
    )
    df = extract.read_eval_telemetry(str(tmp_path / "eval_telemetry_*.jsonl"))
    assert len(df) == 2
    assert set(df["symbol"]) == {"PYTH", "WIF"}
    assert df["source_file"].iloc[0] == "eval_telemetry_20260526.jsonl"
    assert df["ts"].dt.tz is not None


def test_read_eval_telemetry_skips_malformed_lines(tmp_path: Path) -> None:
    f = tmp_path / "eval_telemetry_X.jsonl"
    f.write_text(
        json.dumps({"ts": "2026-05-26T00:00:00+00:00", "symbol": "OK"}) + "\nNOT-JSON\n"
        + json.dumps({"ts": "2026-05-26T00:01:00+00:00", "symbol": "OK2"}) + "\n"
    )
    df = extract.read_eval_telemetry(str(tmp_path / "eval_telemetry_*.jsonl"))
    assert sorted(df["symbol"]) == ["OK", "OK2"]


# ---------------- live-data probe (exercise against the real repo files if present) ----------------


@pytest.mark.parametrize(
    "reader,path_attr",
    [
        (extract.read_decisions, "DEFAULT_DECISION_RUNS_DIR"),
        (extract.read_bot_state, "DEFAULT_BOT_STATE_PATH"),
    ],
)
def test_live_data_smoke(reader, path_attr: str) -> None:
    """If the bot directory exists at the canonical path, the readers don't crash on real data.

    Pure smoke — doesn't assert specific row counts (data churns). Skips silently
    if the live bot directory isn't present (CI / fresh checkout).
    """
    path = getattr(extract, path_attr)
    if not Path(path).exists():
        pytest.skip(f"{path} not present (expected on CI / fresh checkout)")
    df = reader()
    assert isinstance(df, pd.DataFrame)
