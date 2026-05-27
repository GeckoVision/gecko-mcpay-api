"""Sprint 6 — decision-data pipeline + analysis substrate.

This package turns the bot's persistent telemetry (decision_runs/, artifact_*.jsonl,
bot_state.json, eval_telemetry_*.jsonl) into a clean Parquet dataset for analysis,
counterfactual backtest, and the memory_voice v2 pre-trade evaluator.

Sub-modules:
- data_pipeline.extract   — readers per source (returns pandas DataFrames)
- data_pipeline.transform — cleansing + annotation
- data_pipeline.persist   — Parquet writers + DuckDB query helper

See private/strategy/2026-05-26-sprint-6-phase-a-data-pipeline.md (deliverable doc).
"""
