-- 20260425000200_rag_match.sql
-- Purpose: SQL function for per-session pgvector similarity search.
-- Reversible: yes (DROP FUNCTION).
-- Touches: chunks read path only.
--
-- Called from gecko_core.rag.query.rag_query via supabase RPC. Pre-filters by
-- session_id (uses chunks_session_id_idx), then orders by cosine distance
-- against the embedding ANN index. Returns the chunk text + similarity in
-- [0, 1] (1.0 = exact match).

CREATE OR REPLACE FUNCTION match_chunks(
  p_session_id  UUID,
  query_embedding VECTOR(1536),
  match_count   INT DEFAULT 8
)
RETURNS TABLE (
  id           UUID,
  source_id    UUID,
  source_url   TEXT,
  chunk_index  INT,
  text         TEXT,
  similarity   FLOAT
)
LANGUAGE sql STABLE AS $$
  SELECT
    c.id,
    c.source_id,
    s.url AS source_url,
    c.chunk_index,
    c.text,
    1 - (c.embedding <=> query_embedding) AS similarity
  FROM chunks c
  JOIN sources s ON s.id = c.source_id
  WHERE c.session_id = p_session_id
  ORDER BY c.embedding <=> query_embedding
  LIMIT match_count;
$$;
