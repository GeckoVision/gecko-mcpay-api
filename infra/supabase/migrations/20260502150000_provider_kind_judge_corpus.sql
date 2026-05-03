-- 20260502150000_provider_kind_judge_corpus.sql
-- Purpose: S21-JUDGE-CORPUS-01 — extend ProviderKind to include
--          'judge_corpus', the new chunk kind for ingested tweets from
--          named program judges (kukasolana, shimas_sol, kauenet, ...).
--          Mirrors gecko_core.sources.types.ProviderKind. Pattern A drift
--          test asserts SQL ↔ Python parity.
-- Reversible: yes (re-add the prior CHECK without 'judge_corpus').
-- Touches: chunks.provider_kind CHECK, sources.provider_kind CHECK.

ALTER TABLE chunks
  DROP CONSTRAINT IF EXISTS chunks_provider_kind_check;
ALTER TABLE chunks
  ADD CONSTRAINT chunks_provider_kind_check
  CHECK (provider_kind IN (
    'web','youtube','bazaar','arxiv','twitsh','hn','reddit','gecko_precedent','judge_corpus'
  ));

ALTER TABLE sources
  DROP CONSTRAINT IF EXISTS sources_provider_kind_check;
ALTER TABLE sources
  ADD CONSTRAINT sources_provider_kind_check
  CHECK (provider_kind IN (
    'web','youtube','bazaar','arxiv','twitsh','hn','reddit','gecko_precedent','judge_corpus'
  ));
