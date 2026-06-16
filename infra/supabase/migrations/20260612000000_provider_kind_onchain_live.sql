-- 20260612000000_provider_kind_onchain_live.sql
-- Purpose: Phase 0.2 (context-engineering) adds the 'onchain_live' provider
--          kind — the synthetic, single-call live on-chain safety /
--          Information-MEV chunk injected into the trade-panel slate BEFORE
--          the voices run (so the risk_manager SEES it and the grounding gate
--          treats its numbers as grounded-by-construction). Pattern A: the
--          Python Literal (gecko_core.sources.types.ProviderKind) gains the
--          value; this migration restores the SQL side of the contract so the
--          latest CHECK matches the Literal exactly. Drift test
--          tests/test_provider_kind_consistency.py enforces both sides.
-- Reversible: yes (drop + re-add the prior 21-value list) — but don't ship a
--             rollback unless every onchain_live row is reclassified/deleted
--             (the chunk is never persisted, so in practice there are none).
-- Touches: sources.provider_kind CHECK.
--
-- chunks table is intentionally NOT touched — chunks live in Mongo Atlas since
-- 2026-05-08 (memory/project_supabase_chunks_dropped_2026_05_08). The Python
-- ProviderKind Literal is the source of truth, shared by the Mongo writer and
-- the Postgres `sources` provenance row. The onchain_live chunk in particular
-- is purely in-memory (freshness_tier="hot") and is never written to either
-- store; this CHECK extension keeps the Pattern A drift test green.

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
    'market_data',
    'protocol_native',
    'onchain_live'
  ));

COMMENT ON COLUMN sources.provider_kind IS
  'Mirrors gecko_core.sources.types.ProviderKind.';
