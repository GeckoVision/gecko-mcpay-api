"""Sprint 6 Phase A — Parquet writers + DuckDB query helper.

Parquet is the persistent format (small, fast, columnar, dbt-friendly). DuckDB is
the in-process SQL engine — point it at the Parquet dataset for ad-hoc analytics.
This keeps the data substrate small enough to commit-as-artifact (or .gitignore)
while leaving the door open to a real warehouse later.

Output layout (default ANALYSIS_DIR = ``analysis/data/``, gitignored):

    analysis/data/
      decisions_clean.parquet     ← collapsed + annotated decision rows
      bot_state_positions.parquet ← closed-position ledger
      artifacts.parquet           ← all artifact_*.jsonl events
      poll_snapshots.parquet      ← all eval_telemetry_*.jsonl polls
      declined_candidates.parquet ← subset of artifacts: kind=candidate_blocked + local_panel/decline
      manifest.json               ← row counts + source ts + writer version per file

Use ``register_views_in_duckdb(con)`` to expose the parquets as SQL views.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ANALYSIS_DIR = REPO_ROOT / "analysis" / "data"

WRITER_VERSION = 1


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_parquet(df: pd.DataFrame, path: Path | str) -> None:
    """Write df to parquet. NaN-safe; preserves UTC tz on timestamp columns."""
    p = Path(path)
    ensure_dir(p.parent)
    if df.empty:
        # write an empty parquet anyway so downstream can register it as a view.
        df.to_parquet(p, index=False)
        return
    df.to_parquet(p, index=False)


def write_manifest(
    out_dir: Path | str,
    parquet_stats: dict[str, dict[str, Any]],
    source_paths: dict[str, str] | None = None,
) -> Path:
    """Write a manifest.json next to the parquets recording provenance + counts."""
    out = ensure_dir(out_dir)
    manifest = {
        "writer_version": WRITER_VERSION,
        "written_at_utc": datetime.now(timezone.utc).isoformat(),
        "parquets": parquet_stats,
        "source_paths": source_paths or {},
    }
    p = out / "manifest.json"
    p.write_text(json.dumps(manifest, indent=2, default=str))
    return p


def persist_all(
    decisions_clean: pd.DataFrame,
    bot_state_positions: pd.DataFrame,
    artifacts: pd.DataFrame,
    poll_snapshots: pd.DataFrame,
    declined_candidates: pd.DataFrame,
    out_dir: Path | str = DEFAULT_ANALYSIS_DIR,
    source_paths: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Persist every analysis-ready table to its parquet + write the manifest.

    Returns dict {name: parquet_path} for downstream wiring / DuckDB registration.
    """
    out = ensure_dir(out_dir)
    paths = {
        "decisions_clean": out / "decisions_clean.parquet",
        "bot_state_positions": out / "bot_state_positions.parquet",
        "artifacts": out / "artifacts.parquet",
        "poll_snapshots": out / "poll_snapshots.parquet",
        "declined_candidates": out / "declined_candidates.parquet",
    }
    tables = {
        "decisions_clean": decisions_clean,
        "bot_state_positions": bot_state_positions,
        "artifacts": artifacts,
        "poll_snapshots": poll_snapshots,
        "declined_candidates": declined_candidates,
    }
    stats: dict[str, dict[str, Any]] = {}
    for name, df in tables.items():
        write_parquet(df, paths[name])
        try:
            rel = str(paths[name].relative_to(REPO_ROOT))
        except ValueError:
            rel = str(paths[name])  # paths outside the repo (e.g. tmp dirs in tests)
        stats[name] = {
            "rows": int(len(df)),
            "cols": int(len(df.columns)),
            "path": rel,
        }
    write_manifest(out, stats, source_paths=source_paths)
    return paths


def register_views_in_duckdb(con, parquet_paths: dict[str, Path | str]) -> None:
    """Register each parquet as a DuckDB VIEW named after its table key.

    Usage:
        import duckdb
        con = duckdb.connect()
        register_views_in_duckdb(con, paths)
        con.sql("SELECT outcome_label, COUNT(*) FROM decisions_clean GROUP BY 1").show()
    """
    for name, path in parquet_paths.items():
        con.sql(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{path}')")


def open_query_connection(parquet_paths: dict[str, Path | str]):
    """Return a DuckDB connection with all parquets registered as views.

    Caller responsible for ``con.close()``. Defaults to in-memory DB.
    """
    import duckdb  # local import — keeps it optional for callers that don't query

    con = duckdb.connect(":memory:")
    register_views_in_duckdb(con, parquet_paths)
    return con


__all__ = [
    "DEFAULT_ANALYSIS_DIR",
    "WRITER_VERSION",
    "ensure_dir",
    "open_query_connection",
    "persist_all",
    "register_views_in_duckdb",
    "write_manifest",
    "write_parquet",
]
