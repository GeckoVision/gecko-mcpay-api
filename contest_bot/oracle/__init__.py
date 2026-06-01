"""Sprint 29 — Cross-source oracle ingest.

Three subsystems:
- pyth_client: Pyth Hermes REST client (sub-second fair value)
- jupiter_client: Jupiter Aggregator price API (executable price)
- snapshot_sink: Mongo `oracle_snapshots` writer
- snapshot_query: read helpers

The voice that consumes these snapshots is contest_bot.voices.oracle_voice
(env-gated default OFF via GECKO_ORACLE_VOICE_ENABLED).

The ingest itself is env-gated via GECKO_ORACLE_INGEST=1 — without the
flag the cron script no-ops cleanly. Both gates default OFF so bot
runtime is unchanged until the founder flips.

Per docs/build-plan-sprint-29-oracle-ingest.md.
"""
