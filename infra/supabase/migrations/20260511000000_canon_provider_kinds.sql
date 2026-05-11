-- 20260511000000_canon_provider_kinds.sql
-- Purpose: forward-migrate sources_provider_kind_check to admit the
--          investor-canon ProviderKind values that the Python Literal
--          carries as of 2026-05-11. Drift-guarded by
--          tests/test_provider_kind_consistency.py.
--
-- Source of truth: gecko_core.sources.types.ProviderKind. This migration
-- mirrors the 6 new canon_* values added in the same change.
--
-- The canon_* corpus is free + public-domain investor literature blended
-- with live on-chain freshness data — the Gecko wedge for the trade
-- vertical per docs/strategy/2026-05-11-trade-vertical-expansion.md §6.
-- Static freshness tier for canon_marks/damodaran/mauboussin/youtube/
-- berkshire; daily for canon_macro (Fed/BIS/IMF release cadence).
--
-- chunks table is intentionally not touched. Per
-- memory/project_supabase_chunks_dropped_2026_05_08, chunks live in
-- Mongo Atlas only since 2026-05-08; the Supabase chunks table no longer
-- exists. The Python ProviderKind Literal is shared between the Mongo
-- writer and the Postgres `sources` provenance row, so admitting the new
-- values on the surviving CHECK is enough to unblock end-to-end ingest.
--
-- Reverse: drop the constraint and re-add the prior 13-value list. Don't
-- ship rollback unless every canon_* row in `sources` is reclassified or
-- deleted; otherwise rollback raises 23514 itself.

ALTER TABLE sources
  DROP CONSTRAINT IF EXISTS sources_provider_kind_check;
ALTER TABLE sources
  ADD CONSTRAINT sources_provider_kind_check
  CHECK (provider_kind IN (
    'web',
    'youtube',
    'bazaar',
    'arxiv',
    'twitsh',
    'hn',
    'reddit',
    'gecko_precedent',
    'judge_corpus',
    'paysh_manifest',
    'paysh_live',
    'bazaar_manifest',
    'bazaar_live',
    'canon_marks',
    'canon_damodaran',
    'canon_mauboussin',
    'canon_youtube',
    'canon_berkshire',
    'canon_macro'
  ));

COMMENT ON COLUMN sources.provider_kind IS
  'Mirrors gecko_core.sources.types.ProviderKind.';
