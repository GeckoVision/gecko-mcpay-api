# Runbook — Supabase → MongoDB Atlas chunk store cutover

**Sprint:** S18-MONGO-CUTOVER-01 (M5)
**Owner:** staff-engineer
**Last verified:** 2026-05-02 (against M1–M4 commits 596779e, 8eef893, 84c6e03)

This runbook flips the chunk store from Supabase pgvector to MongoDB Atlas Vector Search. Solo-user fresh-start cutover — no backfill, no dual-write. The legacy Supabase chunks table is left intact for one sprint as rollback insurance, then dropped in S19-S3.

## Pre-flight checklist

Before flipping the flag, verify all four are green:

- [ ] M1 indexes ready. Run `gecko-mcp doctor` with `GECKO_CHUNK_STORE=mongo` set; expect `chunk_store:mongo:index:chunks_vector` and `:chunks_text` both `ready`.
- [ ] M3 write tests pass: `uv run pytest tests/db/test_mongo_chunks.py -q`.
- [ ] M4 read tests pass: `uv run pytest tests/db/test_mongo_reads.py -q`.
- [ ] Voyage rerank flag is OFF (`GECKO_RERANKER=none`). Cutover should isolate the storage variable; reranker A/B is S19.

## Flip steps

1. **Set env in `.env`:**

   ```
   GECKO_CHUNK_STORE=mongo
   MONGODB_CHUNK_DB=gecko_rag
   # MONGODB_URI=mongodb+srv://...   already present (transcript store)
   ```

2. **Restart any long-running services** (`gecko-mcp serve`, `gecko-api`) so they pick up the new flag.

3. **Run a smoke ingest:**

   ```
   uv run bb research --idea "demo idea" --tier free
   ```

   Confirm the run produces ≥3 distinct `provider_kind` citations in the verdict footer. The first run will write fresh chunks to Mongo; subsequent runs will hit the Mongo cache path.

4. **Verify in Atlas:** the MCP plugin can do this without leaving the editor:

   ```
   list-collections database=gecko_rag
   count database=gecko_rag collection=chunks
   ```

   Expect a non-zero count after step 3.

5. **Run the holdout-live eval (slim version):**

   ```
   uv run pytest tests/eval/test_holdout_live.py -q
   ```

   Verdict-accuracy should land within 5pp of the S17 baseline (≥0.75). Investigate any drop ≥10pp before continuing — that's likely a hybrid-search parity bug, not a real model regression.

## Revoke writes on legacy Supabase chunks

After cutover has soaked for ≥1 day with no errors, revoke writes on the legacy Supabase tables so any code path that still tries to write hits a hard error instead of silent split-brain. Apply the migration in `infra/supabase/migrations/2026051X000000_revoke_chunks_writes.sql` (drafted but **not yet applied** — staff-engineer reviews and runs it manually).

Reads stay allowed for the rollback window. S19-S3 drops the tables entirely.

## Rollback (if cutover surfaces a regression)

The cutover is single-flag-reversible:

1. Revert env: `GECKO_CHUNK_STORE=supabase`.
2. Re-grant writes if step 6 already ran: `GRANT INSERT, UPDATE ON chunks, chunk_embedding_cache, chunks_write_audit TO service_role;`.
3. Restart services.
4. Open a `S18-MONGO-CUTOVER-ROLLBACK` issue with the failure mode + reproduction.

The Mongo `gecko_rag` data is left intact — no need to drop it. A future re-cutover attempt picks up where it left off.

## Known limitations after cutover

- **No data migration.** Pre-cutover sessions live in Supabase chunks and are **not** queryable from the new Mongo path. This is intentional (solo-user, see `project_mongo_cutover_no_backfill` memory). If you need to re-query an old session, flip the flag back to `supabase` for that one query; the rest of the system keeps working.
- **`source_url` on Mongo chunks comes from `insert_chunks(source_url=...)`** — the pipeline already passes it. If you write chunks via a custom path that bypasses the pipeline, `source_url` will be `null` and citation rendering will degrade. Run all writes through `SessionStore.insert_chunks`.
- **Hybrid search parity is behavioral, not byte-exact.** `match_chunks_hybrid_mongo` mirrors the SQL CTE 1:1, but Atlas Vector Search uses HNSW under the hood vs Postgres pgvector's IVFFlat — top-K can vary by ±1 position on borderline scores. The verdict-accuracy gate is the truth.
