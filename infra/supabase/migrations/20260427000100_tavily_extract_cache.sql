-- 20260427000100_tavily_extract_cache.sql
-- Purpose: cache Tavily Extract responses keyed by sha256(url) so repeated
--          dev/devnet runs on the same idea don't re-pay $0.004 per URL.
-- Reversible: yes (additive, idempotent).
-- TTL: 7 days. The pipeline checks freshness via fetched_at; older rows are
--      ignored (and overwritten) without an explicit purge job.

CREATE TABLE IF NOT EXISTS tavily_extract_cache (
  url_hash    TEXT PRIMARY KEY,
  url         TEXT NOT NULL,
  raw_content TEXT NOT NULL,
  fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS tavily_extract_cache_fetched_at_idx
  ON tavily_extract_cache (fetched_at DESC);

-- Service role writes; no other roles need access.
GRANT SELECT, INSERT, UPDATE, DELETE ON tavily_extract_cache TO service_role;
