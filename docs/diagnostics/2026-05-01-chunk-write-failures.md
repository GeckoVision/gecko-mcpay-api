# Chunk-write failure diagnosis — 2026-05-01

Owner: data-engineer. Feeds Sprint 16 plan (staff-engineer in parallel).
Scope: ingestion path from chunker output through `chunks` row insert. No fixes here, diagnosis only.

## 1. Top 3 confirmed failure modes (file:line)

### FM-1. `insert_chunks` swallows partial-batch failures silently

`packages/gecko-core/src/gecko_core/sessions/store.py:611-622` — `insert_chunks` chunks the rows at 500 and accumulates `total_inserted += len(inserted)`. There is no transaction; if batch 2 of 3 raises (read timeout, 504 from PostgREST, single-row pgvector dim mismatch), batches 1 already committed and the source ends up with partial chunks. The exception then bubbles up to `_process_one` which marks the source `failed` (`pipeline.py:286-299`) — even though some rows were written. `set_source_chunk_count` is never called (`pipeline.py:266`), so `sources.chunk_count` stays at the default `0` while `chunks` has rows. Reload of the same session re-ingests via the cache-hit path and writes duplicates if/when the unique constraint is loosened. **Today the only protection is `UNIQUE (source_id, chunk_index)` (init.sql:40)** which converts duplicates to a 23505 — that surfaces as "ingest.upsert.failed" with no per-row detail (pipeline.py:257-265 logs only the first 200 chars of `str(exc)`).

### FM-2. Pre-S8 reproductions of "APIError on every URL" (audit F11) live on as latent shape risk

`docs/audits/integration-audit-2026-04-30.md:11,24-37` records the Sprint 7 dogfood crash: extract OK + embed OK + upsert raises `APIError`. The pipeline now defends against the obvious shape break (`pipeline.py:225-229` raises `RuntimeError` on `len(new_embeddings) != len(missing_texts)`) and filters empty pieces (`pipeline.py:75-84`). The remaining unprotected seam is the **cache hit path**: `get_chunk_cache` (`store.py:827-869`) returns vectors as `list[float]` after best-effort coercion, but never validates `len(emb) == 1536`. A single bad cached row (legacy from a pre-`text-embedding-3-small` write, or partial JSON parse) returns a wrong-dim vector that flows straight into `insert_chunks` and trips Postgres `vector(1536)` mismatch as a per-batch error. The `chunk_embedding_cache` migration (20260430052216) never wiped on the model-default change (the migration explicitly tells you to wipe — line 7-9 — and we have not).

### FM-3. RateLimit retry exhaustion is a cliff, not a degradation

`packages/gecko-core/src/gecko_core/ingestion/embedder.py:36-100` — 4 attempts, fixed `(1,2,4,8)s` backoff, no jitter. With `_EMBED_CONCURRENCY=8` and `MAX_CONCURRENT_SOURCES=5` (pipeline.py:36) the synchronized backoff causes thundering herd: when one source trips TPM, all in-flight sources retry at the same wall-clock instants. After 4 attempts the `RateLimitError` propagates up and the source is marked `failed` (pipeline.py:286). The dogfood matrix re-runs the same idea repeatedly, so every dogfood pass re-pays the same penalty. There is no circuit breaker and no shedding to a smaller batch (the 100-input batch is constant, embedder.py:28).

Tests do not exercise these — `tests/ingestion/test_pipeline.py` uses `FakeStore` whose `insert_chunks` always succeeds and never partial-fails (test_pipeline.py:32-39). All 88 ingestion tests pass on a stub. **Pattern C from CLAUDE.md applies directly**: tests exercise stubs, not real wires.

## 2. Schema audit (`infra/supabase/migrations/`)

- `chunks` (init.sql:33-41): PK `id`, FK `session_id`/`source_id`, `chunk_index INT NOT NULL`, `text TEXT NOT NULL`, `embedding VECTOR(1536) NOT NULL`, `UNIQUE (source_id, chunk_index)`. **No `CHECK (length(text) > 0)`** — a whitespace-only string passes NOT NULL silently. The `_filter_embeddable` filter in pipeline.py:75-84 is the only line of defense; if it ever regresses, schema does not catch it.
- `chunks_temporal` (20260501110000): added `captured_at TIMESTAMPTZ NOT NULL DEFAULT now()` and nullable `project_id UUID`. Pipeline `insert_chunks` (store.py:600-609) does **not** populate either column. `captured_at` rides the default; `project_id` is always NULL on chunks even when the session has one bound via `set_session_project` (store.py:754-778). The partial index `chunks_project_captured_at_idx` (chunks_temporal.sql:43-45) is therefore empty in production — `match_chunks_windowed` falls through to a full ANN scan.
- `chunk_embedding_cache` (20260430052216): PK `(url_hash, chunk_index)`. **No model fingerprint column.** A model swap silently poisons the cache. The migration header tells the operator to wipe — operationally fragile.
- `sources` (init.sql:22-31): `UNIQUE (session_id, url_hash)` is correct for per-session idempotency. There is no global URL dedup, by design.

Things missing that would surface failures cleanly:
- `CHECK (length(text) > 0)` on `chunks.text`.
- A `vector_dim(embedding) = 1536` CHECK is not directly expressible without a function, but a trigger or a `cardinality(embedding::real[]) = 1536` analog would catch FM-2.
- An `embed_model TEXT` column on `chunk_embedding_cache` (or a fingerprint hash) so a model change is a constraint violation, not silent corruption.
- An `ingested_at` column on `chunks` (separate from `captured_at`) so we can distinguish "when the source was captured" from "when we wrote the row" — currently entangled.

## 3. Observability gap

We have INFO logs at every pipeline step (`ingest.start`, `ingest.extracted`, `ingest.chunked`, `ingest.embed.start`, `ingest.embed.failed`, `ingest.upsert.failed`, `ingest.indexed`, `ingest.failed`) but they are unstructured strings via stdlib logging. We cannot answer "what fraction of failures in the last 24h were upsert vs embed vs extract" without grepping logs.

Proposal: a `chunks_write_audit` table — one row per `_process_one` exit, columns `(session_id, source_id, url_hash, outcome TEXT, failure_class TEXT, failure_detail TEXT, raw_chunks INT, embeddable_chunks INT, cache_hits INT, embedded INT, inserted INT, vector_dim INT, embed_tokens INT, attempt_started_at, attempt_finished_at)`. Written at the end of `_process_one` regardless of outcome (best-effort, separate try/except so audit failure does not mask the real outcome). Indexed on `(outcome, attempt_finished_at DESC)` and `(failure_class, attempt_finished_at DESC)`. This gives us a single SQL query to bucket the dominant failure mode and turns FM-1 (silent partial writes) into a visible discrepancy: `inserted < embeddable_chunks` with `outcome = 'failed'`.

Pair it with structlog (already a soft dep elsewhere) for the existing `logger.info` calls so the same fields land in stdout — Supabase Logs becomes a real-time view, the audit table is the historical record.

## 4. Fix priority (3 tickets, impact/effort ordered)

**S16-INGEST-01 — chunks_write_audit table + structured outcome logging.**
Acceptance: new migration creates `chunks_write_audit`. `_process_one` writes one row per exit (success/skip/fail) with all fields above. Existing `logger.info` calls switched to structured kwargs. SQL query in PR description shows the failure-mode histogram for the last 24h of dogfood.

**S16-INGEST-02 — make `insert_chunks` transactional + cache dim-validate.**
Acceptance: `insert_chunks` writes all batches inside a single Postgres transaction (RPC or `supabase-py` batched-via-rpc); on failure no rows persist. `get_chunk_cache` (store.py:827-869) drops any row whose embedding length != 1536 and logs a `cache_dim_mismatch` audit event. Add `CHECK (length(text) > 0)` to `chunks.text` via migration. Test: an injected dim-bad cache row causes the source to mark `failed` cleanly with audit row, no partial chunks in DB.

**S16-INGEST-03 — embed retry jitter + per-batch shedding; `chunk_embedding_cache.embed_model` column.**
Acceptance: `_RETRY_BACKOFFS_S` becomes `expo + uniform(0, 1)s` jitter; on `RateLimitError` after attempt 2, halve the batch and retry the halves before giving up. New migration adds `embed_model TEXT NOT NULL DEFAULT 'text-embedding-3-small'` to `chunk_embedding_cache`, PK becomes `(url_hash, chunk_index, embed_model)`, and `get_chunk_cache` filters on the active model. Backfill marks existing rows with the legacy model name. Smoke: 5-idea dogfood matrix completes without `RateLimitError` cliff under the same TPM ceiling.

## Files referenced (absolute)

- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/ingestion/pipeline.py
- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/ingestion/embedder.py
- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/ingestion/chunker.py
- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/sessions/store.py
- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/infra/supabase/migrations/20260425000000_init.sql
- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/infra/supabase/migrations/20260425000100_pgvector_index.sql
- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/infra/supabase/migrations/20260430052216_chunk_embedding_cache.sql
- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/infra/supabase/migrations/20260501110000_chunks_temporal.sql
- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/tests/ingestion/test_pipeline.py
- /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/docs/audits/integration-audit-2026-04-30.md
