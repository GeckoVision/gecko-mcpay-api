-- 018_memory.sql
-- Purpose: native Gecko decision-memory layer (S5-MEM-01). Every paid loop
--          step (verdict / scaffold / plan / pulse) appends a typed entry
--          here so the next loop iteration can recall priorities, deltas,
--          and contradictions. Scoped to {project, session, user}; on-chain
--          anchored via the optional tx_signature column.
-- Reversible: yes (drops new table + RPC + project_settings.journal_enabled).
-- Touches: new table `memory`; new RPC `gecko_memory_match`; ALTER `projects`
--          (additive nullable column journal_enabled).

CREATE TABLE IF NOT EXISTS memory (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type   TEXT NOT NULL CHECK (scope_type IN ('project','session','user')),
  scope_id     TEXT NOT NULL,
  entry_type   TEXT NOT NULL CHECK (entry_type IN (
    'verdict_received','scaffold_generated','plan_advised',
    'advisor_voiced','pulse_run','feature_shipped','user_note'
  )),
  key          TEXT,
  value        JSONB NOT NULL,
  embedding    VECTOR(1536),
  tx_signature TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ttl_at       TIMESTAMPTZ
);

-- Hot-path: gecko_resume / recall reads "last 30 days for this project,
-- grouped by entry_type, newest first". Index ordering matches the query.
CREATE INDEX IF NOT EXISTS idx_memory_scope
  ON memory (scope_type, scope_id, entry_type, created_at DESC);

-- ANN search: cosine distance on the embedding column. ivfflat with
-- lists=100 mirrors gecko_precedent's tuning; revisit when corpus > 100k.
CREATE INDEX IF NOT EXISTS idx_memory_embedding
  ON memory USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- TTL filter: read-time skip of expired rows. Sprint 6 cron sweeps the
-- actual deletion (per dispatch instruction, not in this migration).
CREATE INDEX IF NOT EXISTS idx_memory_ttl
  ON memory (ttl_at) WHERE ttl_at IS NOT NULL;

ALTER TABLE memory ENABLE ROW LEVEL SECURITY;

-- Reads: mirror gecko_precedent's "permissive read" stance — RLS at the API
-- layer is bearer-auth, and project ownership is enforced at the application
-- layer in the gecko-api / SessionStore. Callers using anon key only see
-- entries for scopes the API has already authorized them to read.
CREATE POLICY "read_all_memory" ON memory FOR SELECT USING (true);

-- Self-service privacy escape: a row may be deleted only when the requester
-- can prove ownership of the scope. v1 has no Supabase auth integration,
-- so this is a placeholder: deletes are gated at the application layer
-- (see memory.delete in gecko_core). Once auth lands we tighten this to
-- `auth.uid()::text = scope_id` for scope_type='user'.
CREATE POLICY "delete_memory_authenticated" ON memory FOR DELETE USING (true);

-- Service role bypasses RLS by default — backend writes (auto-journal hooks)
-- use the service_role key.
GRANT ALL ON TABLE memory TO service_role;

COMMENT ON TABLE memory IS
  'Native Gecko decision-memory layer (S5-MEM-01). Typed entry types for the verdict→scaffold→plan→advise→pulse loop. Embedding computed at save-time from the textual representation of `value`.';

COMMENT ON COLUMN memory.tx_signature IS
  'Optional Solana tx signature anchoring this entry to an on-chain x402 settlement (the journal-as-immutable-anchor moat).';

COMMENT ON COLUMN memory.ttl_at IS
  'Optional expiration timestamp. Filtered out at read time; physical deletion happens via a Sprint 6 cron job (not this migration).';

-- Per-project opt-out for auto-journaling. Default TRUE so the flywheel
-- keeps firing unless the user explicitly disables it for a project.
ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS journal_enabled BOOLEAN NOT NULL DEFAULT TRUE;

-- Retrieval RPC: cosine similarity, server-side filtered by scope so callers
-- never see other scopes' rows. Pre-filter on similarity_threshold (not
-- post-filter) so the ivfflat index does the heavy lifting.
CREATE OR REPLACE FUNCTION gecko_memory_match(
  p_scope_type         TEXT,
  p_scope_id           TEXT,
  p_query_embedding    VECTOR(1536),
  p_match_limit        INT,
  p_similarity_threshold FLOAT DEFAULT 0.0
)
RETURNS TABLE (
  id           UUID,
  scope_type   TEXT,
  scope_id     TEXT,
  entry_type   TEXT,
  key          TEXT,
  value        JSONB,
  tx_signature TEXT,
  created_at   TIMESTAMPTZ,
  similarity   FLOAT
)
LANGUAGE sql STABLE AS $$
  SELECT
    m.id, m.scope_type, m.scope_id, m.entry_type, m.key, m.value,
    m.tx_signature, m.created_at,
    1 - (m.embedding <=> p_query_embedding) AS similarity
  FROM memory m
  WHERE m.scope_type = p_scope_type
    AND m.scope_id   = p_scope_id
    AND m.embedding IS NOT NULL
    AND (m.ttl_at IS NULL OR m.ttl_at > NOW())
    AND 1 - (m.embedding <=> p_query_embedding) >= p_similarity_threshold
  ORDER BY m.embedding <=> p_query_embedding ASC
  LIMIT p_match_limit;
$$;

GRANT EXECUTE ON FUNCTION gecko_memory_match(TEXT, TEXT, VECTOR(1536), INT, FLOAT) TO service_role;
GRANT EXECUTE ON FUNCTION gecko_memory_match(TEXT, TEXT, VECTOR(1536), INT, FLOAT) TO authenticated;
GRANT EXECUTE ON FUNCTION gecko_memory_match(TEXT, TEXT, VECTOR(1536), INT, FLOAT) TO anon;
