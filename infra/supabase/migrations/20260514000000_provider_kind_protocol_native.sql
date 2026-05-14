-- 20260514000000_provider_kind_protocol_native.sql
-- Purpose: extend sources_provider_kind_check to admit the new
--          'protocol_native' ProviderKind added for S31-#50 Jito MEV
--          ingest. Mirrors Pattern A — the canonical Python literal lives
--          at gecko_core.sources.types.ProviderKind; this CHECK is the
--          SQL side of that contract. Drift is guarded by
--          tests/test_provider_kind_consistency.py.
-- Reversible: yes (drop the constraint and re-add the prior 20-value list).
--             Don't ship rollback unless every protocol_native row in
--             `sources` is reclassified or deleted; otherwise rollback
--             raises 23514 itself.
-- Touches: sources table (CHECK constraint replacement only).
--
-- chunks table is intentionally not touched. Per
-- memory/project_supabase_chunks_dropped_2026_05_08, chunks live in Mongo
-- Atlas only since 2026-05-08; the Supabase chunks table no longer
-- exists. The Python ProviderKind Literal is shared between the Mongo
-- writer and the Postgres `sources` provenance row, so admitting the new
-- value on the surviving CHECK is enough to unblock end-to-end ingest.

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
    'canon_macro',
    'protocol_native'
  ));

COMMENT ON COLUMN sources.provider_kind IS
  'Mirrors gecko_core.sources.types.ProviderKind.';
