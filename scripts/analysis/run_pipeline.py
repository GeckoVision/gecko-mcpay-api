"""Sprint 6 Phase A — runner. Extract → transform → persist → smoke summary.

Run:
    uv run python scripts/analysis/run_pipeline.py
    # or with custom output dir:
    uv run python scripts/analysis/run_pipeline.py --out-dir /tmp/gecko-analysis

Produces five Parquet files + manifest.json under ``analysis/data/`` (default).
Prints row counts + a few SQL-driven sanity numbers after persistence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/analysis/run_pipeline.py` invocation: put the repo root
# on sys.path so `from scripts.analysis...` resolves the same as `python -m`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

from scripts.analysis.data_pipeline import extract, persist, transform  # noqa: E402


def _derive_declined_candidates(artifacts: pd.DataFrame) -> pd.DataFrame:
    """Subset of artifacts: every event where the bot DID NOT open a position."""
    if artifacts.empty or "kind" not in artifacts.columns:
        return artifacts
    decline_kinds = {"candidate_blocked", "local_panel"}
    sub = artifacts[artifacts["kind"].isin(decline_kinds)].copy()
    if "payload_action" in sub.columns:
        # local_panel rows include both 'decline' AND 'act' — keep only declines.
        not_act = (sub["kind"] != "local_panel") | (sub["payload_action"] == "decline")
        sub = sub[not_act]
    return sub.reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(persist.DEFAULT_ANALYSIS_DIR))
    ap.add_argument("--min-win-pct", type=float, default=transform.DEFAULT_MIN_REALIZED_WIN_PCT)
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)

    print("==> reading raw sources...")
    raw_decisions = extract.read_decisions()
    raw_artifacts = extract.read_artifacts()
    raw_positions = extract.read_bot_state()
    raw_telemetry = extract.read_eval_telemetry()
    print(
        f"    raw decisions: {len(raw_decisions):6d}  artifacts: {len(raw_artifacts):6d}  "
        f"positions: {len(raw_positions):3d}  telemetry: {len(raw_telemetry):6d}"
    )

    print("==> transforming...")
    decisions_clean = transform.annotate_full(
        raw_decisions, raw_positions, raw_telemetry, min_win_pct=args.min_win_pct
    )
    print(f"    decisions_clean: {len(decisions_clean)} rows ({len(decisions_clean.columns)} cols)")
    if not decisions_clean.empty and "outcome_label" in decisions_clean.columns:
        print("    label distribution:")
        for k, v in decisions_clean["outcome_label"].value_counts().items():
            print(f"      {v:4d}  {k}")
        if "regime_at_entry" in decisions_clean.columns:
            print("    regime-at-entry distribution:")
            for k, v in decisions_clean["regime_at_entry"].value_counts(dropna=False).items():
                print(f"      {v:4d}  {k}")

    declined = _derive_declined_candidates(raw_artifacts)
    print(f"    declined_candidates: {len(declined)} rows (filtered from {len(raw_artifacts)} artifacts)")

    print(f"==> persisting to {out_dir}...")
    paths = persist.persist_all(
        decisions_clean=decisions_clean,
        bot_state_positions=raw_positions,
        artifacts=raw_artifacts,
        poll_snapshots=raw_telemetry,
        declined_candidates=declined,
        out_dir=out_dir,
        source_paths={
            "decision_runs_dir": str(extract.DEFAULT_DECISION_RUNS_DIR),
            "bot_state_path": str(extract.DEFAULT_BOT_STATE_PATH),
            "artifact_glob": str(extract.DEFAULT_ARTIFACT_GLOB),
            "telemetry_glob": str(extract.DEFAULT_TELEMETRY_GLOB),
        },
    )
    for name, p in paths.items():
        print(f"    {name:25s} → {p}")
    manifest_path = out_dir / "manifest.json"
    print(f"    manifest                  → {manifest_path}")

    print("==> SQL sanity checks via DuckDB...")
    con = persist.open_query_connection(paths)
    try:
        for label, sql in [
            ("decisions by outcome_label × regime",
             "SELECT regime_at_entry, outcome_label, COUNT(*) AS n FROM decisions_clean GROUP BY 1,2 ORDER BY 1,2"),
            ("ledger expectancy",
             "SELECT COUNT(*) AS n, ROUND(AVG(outcome_pnl_pct),3) AS mean_pct, "
             "ROUND(SUM(CASE WHEN outcome_label='win' THEN 1 ELSE 0 END)*1.0/COUNT(*),3) AS strict_wr "
             "FROM decisions_clean WHERE outcome_pnl_pct IS NOT NULL"),
            ("declined by reason (top 10)",
             "SELECT payload_coordinator_rule_fired AS rule, COUNT(*) AS n "
             "FROM declined_candidates GROUP BY 1 ORDER BY 2 DESC LIMIT 10"),
        ]:
            print(f"    [{label}]")
            res = con.sql(sql).fetchall()
            cols = [d[0] for d in con.sql(sql).description]
            for row in res:
                rec = dict(zip(cols, row, strict=False))
                print(f"      {rec}")
    finally:
        con.close()

    print("==> done.")
    # surface the manifest one more time for redirect-to-file usage
    print(json.dumps(json.loads(manifest_path.read_text())["parquets"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
