-- Adds freshness_tier to chunks. Mirrors gecko_core.sources.types.FreshnessTier.
-- Defaults existing rows to 'static' (preserves current retrieval behavior).
-- Pattern A: any addition here must update FreshnessTier literal in the same commit.

ALTER TABLE chunks
  ADD COLUMN IF NOT EXISTS freshness_tier text NOT NULL DEFAULT 'static';

ALTER TABLE chunks
  DROP CONSTRAINT IF EXISTS chunks_freshness_tier_check;

ALTER TABLE chunks
  ADD CONSTRAINT chunks_freshness_tier_check
  CHECK (freshness_tier IN ('static', 'daily', 'live_only'));

CREATE INDEX IF NOT EXISTS chunks_freshness_tier_idx ON chunks (freshness_tier);
