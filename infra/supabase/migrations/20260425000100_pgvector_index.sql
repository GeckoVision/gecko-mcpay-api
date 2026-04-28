-- 20260425000100_pgvector_index.sql
-- Purpose: indexes for retrieval. Pre-filter by session_id (btree), then vector ANN.
-- Reversible: yes (DROP INDEX is safe; data preserved).
-- Touches: chunks table indexes only.
--
-- Query pattern (see gecko_core/rag): filter chunks by session_id, then order by
-- embedding <=> query for cosine similarity. The btree narrows the candidate set
-- before the IVFFlat probe so per-session searches stay fast even as the table grows.

CREATE INDEX IF NOT EXISTS chunks_session_id_idx
  ON chunks (session_id);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
  ON chunks USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
