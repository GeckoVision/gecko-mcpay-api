-- 20260501110000_chunks_temporal.sql
-- Purpose: S13-PHASE-02 — give chunks a temporal axis (`captured_at`) and a
--          forward-compat project pointer (`project_id`), plus a windowed
--          similarity-search RPC that pre-filters on (project_id,
--          captured_at) before running the vector ANN. This is the
--          retrieval seam S14 gecko_pulse + S15 pulse-delta will hang off.
-- Reversible: yes (additive columns + new index + new RPC).
-- Touches: chunks table; new function match_chunks_windowed.
--
-- Notes:
--  - chunks has no `created_at` column today (init.sql is bare-bones); we
--    backfill `captured_at` from the source row's `indexed_at` since that's
--    the closest temporal anchor we have for legacy rows. New rows pick up
--    the DEFAULT now().
--  - project_id is nullable + FK-reservation only. There IS a `projects`
--    table (migration 20260428000000) so the FK is real, but most chunks
--    today are project-less and stay NULL. The pulse pipeline will
--    populate it going forward.
--  - Partial index on (project_id, captured_at) WHERE captured_at IS NOT
--    NULL keeps the windowed query (project-scoped + time-bounded)
--    index-only. The full-corpus vector ANN index from
--    20260425000100_pgvector_index.sql still covers session-scoped reads.
--  - match_chunks_windowed mirrors match_chunks's return shape for caller
--    symmetry. window_days=NULL means "no temporal cap"; project_id=NULL
--    means "match across projects" (used for cross-project pulses, rare).

ALTER TABLE chunks
  ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS project_id  UUID REFERENCES projects(id);

-- Backfill legacy chunks: borrow `indexed_at` from their parent source so
-- the temporal axis isn't a wall-clock cliff at deploy time. Idempotent —
-- re-running this migration on a fresh DB is a no-op because all rows
-- will already carry the DEFAULT now().
UPDATE chunks
   SET captured_at = sources.indexed_at
  FROM sources
 WHERE chunks.source_id = sources.id
   AND chunks.captured_at >= now() - INTERVAL '1 minute';

-- Project-scoped windowed search index. Partial WHERE keeps it tiny while
-- the project_id rollout is partial.
CREATE INDEX IF NOT EXISTS chunks_project_captured_at_idx
  ON chunks (project_id, captured_at DESC)
  WHERE captured_at IS NOT NULL;

-- Time-windowed similarity search. Pre-filters on (project_id,
-- captured_at) using the partial index above, then runs the vector ANN
-- over the narrowed set. Returns the same shape as match_chunks so
-- callers can swap in this RPC by passing extra kwargs.
--
-- Args:
--   query_embedding: the search vector (1536-dim, OpenAI text-embedding-3-small).
--   window_days:     INTEGER days back from now() to bound captured_at on.
--                    NULL or <=0 disables the temporal filter.
--   p_project_id:    project to scope to. NULL matches across all projects
--                    (caller is responsible for whether that's the right
--                    contract; the windowed RPC is project-aware first).
--   match_count:     LIMIT. Default 8 mirrors match_chunks.
CREATE OR REPLACE FUNCTION match_chunks_windowed(
  query_embedding VECTOR(1536),
  window_days     INTEGER,
  p_project_id    UUID,
  match_count     INT DEFAULT 8
)
RETURNS TABLE (
  id           UUID,
  source_id    UUID,
  source_url   TEXT,
  chunk_index  INT,
  text         TEXT,
  captured_at  TIMESTAMPTZ,
  similarity   FLOAT
)
LANGUAGE sql STABLE AS $$
  SELECT
    c.id,
    c.source_id,
    s.url AS source_url,
    c.chunk_index,
    c.text,
    c.captured_at,
    1 - (c.embedding <=> query_embedding) AS similarity
  FROM chunks c
  JOIN sources s ON s.id = c.source_id
  WHERE (p_project_id IS NULL OR c.project_id = p_project_id)
    AND (
      window_days IS NULL
      OR window_days <= 0
      OR c.captured_at >= now() - make_interval(days => window_days)
    )
  ORDER BY c.embedding <=> query_embedding
  LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION match_chunks_windowed(VECTOR(1536), INTEGER, UUID, INT) TO service_role;
GRANT EXECUTE ON FUNCTION match_chunks_windowed(VECTOR(1536), INTEGER, UUID, INT) TO authenticated;
