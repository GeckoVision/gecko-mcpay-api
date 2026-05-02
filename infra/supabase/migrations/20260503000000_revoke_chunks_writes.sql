-- 20260503000000_revoke_chunks_writes.sql
-- Purpose: S18-MONGO-CUTOVER-01 follow-up. After GECKO_CHUNK_STORE=mongo
--          ships and soaks for ≥1 day, revoke writes on the legacy
--          Supabase chunk tables so any forgotten code path fails loudly
--          instead of silently splitting writes between two stores.
-- Reversible: yes — re-GRANT INSERT/UPDATE/DELETE on these tables.
-- Touches: chunks, chunk_embedding_cache, chunks_write_audit.
--
-- DO NOT APPLY UNTIL:
--   1. .env has GECKO_CHUNK_STORE=mongo
--   2. gecko-mcp doctor reports chunk_store:mongo:* all ok
--   3. At least one bb research --tier free run completed against Mongo
--   4. ≥1 day soak with no error_kind != 'none' in chunks_write_audit
--
-- Reads are NOT revoked — a rollback to GECKO_CHUNK_STORE=supabase still
-- needs to query the legacy data. S19-S3 drops the tables entirely.

REVOKE INSERT, UPDATE, DELETE ON chunks FROM service_role, authenticated;
REVOKE INSERT, UPDATE, DELETE ON chunk_embedding_cache FROM service_role, authenticated;
REVOKE INSERT, UPDATE, DELETE ON chunks_write_audit FROM service_role, authenticated;

COMMENT ON TABLE chunks IS
  'LEGACY (S18-MONGO-CUTOVER-01) — read-only after 2026-05-03. New chunks '
  'live in MongoDB Atlas gecko_rag.chunks. Drop scheduled S19-S3.';
COMMENT ON TABLE chunk_embedding_cache IS
  'LEGACY (S18-MONGO-CUTOVER-01) — read-only after 2026-05-03. New cache '
  'in MongoDB Atlas gecko_rag.chunk_embedding_cache. Drop scheduled S19-S3.';
COMMENT ON TABLE chunks_write_audit IS
  'LEGACY (S18-MONGO-CUTOVER-01) — read-only after 2026-05-03. New audit '
  'in MongoDB Atlas gecko_rag.chunks_write_audit. Drop scheduled S19-S3.';
