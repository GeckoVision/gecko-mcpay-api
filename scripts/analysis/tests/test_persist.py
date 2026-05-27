"""Unit tests for scripts.analysis.data_pipeline.persist."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from scripts.analysis.data_pipeline import persist


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"decision_id": "d1", "symbol": "WIF", "ts": pd.Timestamp("2026-05-26T12:00", tz="UTC"), "outcome_label": "win"},
            {"decision_id": "d2", "symbol": "JTO", "ts": pd.Timestamp("2026-05-26T13:00", tz="UTC"), "outcome_label": "loss"},
        ]
    )


def test_write_parquet_roundtrips(tmp_path: Path) -> None:
    df = _sample_df()
    p = tmp_path / "x.parquet"
    persist.write_parquet(df, p)
    assert p.exists()
    back = pd.read_parquet(p)
    assert len(back) == 2
    assert list(back["outcome_label"]) == ["win", "loss"]


def test_write_parquet_empty_df_still_writes_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.parquet"
    persist.write_parquet(pd.DataFrame(), p)
    assert p.exists()
    assert pd.read_parquet(p).empty


def test_write_parquet_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "deep" / "nest" / "x.parquet"
    persist.write_parquet(_sample_df(), p)
    assert p.exists()


def test_write_manifest_records_writer_version_and_stats(tmp_path: Path) -> None:
    p = persist.write_manifest(
        tmp_path,
        {"decisions_clean": {"rows": 2, "cols": 4, "path": "decisions_clean.parquet"}},
        source_paths={"decision_runs_dir": "/contest_bot/decision_runs/"},
    )
    assert p.exists()
    m = json.loads(p.read_text())
    assert m["writer_version"] == persist.WRITER_VERSION
    assert "written_at_utc" in m
    assert m["parquets"]["decisions_clean"]["rows"] == 2
    assert m["source_paths"]["decision_runs_dir"] == "/contest_bot/decision_runs/"


def test_persist_all_writes_all_5_parquets_plus_manifest(tmp_path: Path) -> None:
    paths = persist.persist_all(
        decisions_clean=_sample_df(),
        bot_state_positions=_sample_df(),
        artifacts=_sample_df(),
        poll_snapshots=_sample_df(),
        declined_candidates=_sample_df(),
        out_dir=tmp_path,
    )
    assert set(paths.keys()) == {
        "decisions_clean",
        "bot_state_positions",
        "artifacts",
        "poll_snapshots",
        "declined_candidates",
    }
    for p in paths.values():
        assert p.exists()
    assert (tmp_path / "manifest.json").exists()
    m = json.loads((tmp_path / "manifest.json").read_text())
    for name in paths:
        assert m["parquets"][name]["rows"] == 2


def test_register_views_in_duckdb_exposes_parquets_as_sql_views(tmp_path: Path) -> None:
    paths = persist.persist_all(
        decisions_clean=_sample_df(),
        bot_state_positions=_sample_df(),
        artifacts=_sample_df(),
        poll_snapshots=_sample_df(),
        declined_candidates=_sample_df(),
        out_dir=tmp_path,
    )
    con = duckdb.connect(":memory:")
    persist.register_views_in_duckdb(con, paths)
    result = con.sql(
        "SELECT outcome_label, COUNT(*) AS n FROM decisions_clean GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert result == [("loss", 1), ("win", 1)]
    con.close()


def test_open_query_connection_returns_usable_duckdb_con(tmp_path: Path) -> None:
    paths = persist.persist_all(
        decisions_clean=_sample_df(),
        bot_state_positions=_sample_df(),
        artifacts=_sample_df(),
        poll_snapshots=_sample_df(),
        declined_candidates=_sample_df(),
        out_dir=tmp_path,
    )
    con = persist.open_query_connection(paths)
    try:
        n = con.sql("SELECT COUNT(*) FROM decisions_clean").fetchone()[0]
        assert n == 2
    finally:
        con.close()


def test_persist_all_returns_paths_dict_for_duckdb_registration(tmp_path: Path) -> None:
    paths = persist.persist_all(
        decisions_clean=pd.DataFrame(),
        bot_state_positions=pd.DataFrame(),
        artifacts=pd.DataFrame(),
        poll_snapshots=pd.DataFrame(),
        declined_candidates=pd.DataFrame(),
        out_dir=tmp_path,
    )
    # Even with empty inputs, all parquets exist + manifest records 0-row stats.
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert all(m["parquets"][name]["rows"] == 0 for name in paths)
