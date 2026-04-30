# Sprint 13+ — data-engineer memo

**Date:** 2026-04-30
**Lens:** Supabase schema, pgvector, ingestion storage, embeddings. "The data is correctly stored."
**Predecessors:** `roadmap-vision-2026-04-30.md`, `bazaar-deeper-thesis-2026-04-30.md`.

Current schema baseline: `sessions / sources / chunks` (init), `pulse_runs` (019), `gecko_precedent` (015), `chunk_embedding_cache` (20260430052216), `precedent_outcomes` (20260430054542). `chunks.embedding VECTOR(1536)` matches `text-embedding-3-small`.

---

## Theme 1 — Lifecycle monetization (`gecko_pulse`)

1. **Sequencing.** Sprint 13. Storage shape unblocks every other theme; recurring pulses also drive eval-data flywheel.
2. **Smallest wedge.** Add `chunks.captured_at TIMESTAMPTZ NOT NULL DEFAULT now()` plus `sources.fetched_at`, and a `match_chunks_windowed(session_id, query_embedding, since TIMESTAMPTZ, top_k)` RPC. That alone enables "only chunks from the last 14 days about this idea." Reuse existing pgvector ivfflat index; pre-filter by `session_id AND captured_at >= since` before vector search.
3. **Schema vs query-side?** **Both, minimally.** Schema adds one timestamp column (cheap, additive). The temporal filter is query-side via the RPC's `since` parameter — no partitioning yet. Revisit partitioning only when chunks > 50M rows.
4. **Risks in lane.**
   - Re-grounding pulses across multiple sessions for the same idea will fragment chunks by `session_id`. Need a `project_id` rollup so pulse N+1 can vector-search across pulses N..1. `pulse_runs.project_id` already exists (nullable); extend `chunks.project_id` (nullable, backfilled from `sessions`).
   - ivfflat recall degrades with heavy pre-filter selectivity. If `since` cuts > 90% of chunks, we want a partial index `WHERE captured_at > now() - interval '90 days'` — defer until EXPLAIN shows it.
   - Embedding cache (`chunk_embedding_cache`) is keyed by content hash — safe across pulses, no change.
5. **Cross-lane deps.** `software-engineer` for the pulse runner; `business-manager` for per-pulse SKU; `staff-engineer` for the project-vs-session rollup decision (this is a boundary call).

## Theme 2 — Paragraph creator connector

1. **Sequencing.** Sprint 14. Wedge ships once payment-hop semantics are pinned by `web3-engineer`.
2. **Smallest wedge.** New row in `sources.type` enum check (`'paragraph'`) + a sibling table `source_creators (source_id PK, creator_handle, creator_wallet, platform)`. Don't put `creator_wallet` on `chunks` — it would denormalize across millions of rows for a per-source attribute. Join via `chunks.source_id → sources.id → source_creators`.
3. **Payment recording.** Reuse `x402_settlements` (012). Add `x402_settlements.source_id UUID NULL REFERENCES sources(id)` so a payment row carries `(tx_signature, amount, network, source_id)`. Chunks stay lean; attribution and audit live on the settlement row, which is the right home for a tx hash. Aggregations ("how much did we pay creator X this month") become a single join.
4. **Risks in lane.** Idempotency: re-fetching a Paragraph post must not re-pay the creator. The existing `(session_id, url_hash) UNIQUE` on `sources` covers per-session; we need a global `payments_per_url` ledger lookup before settling. `source_creators` should be upserted, not duplicated per session.
5. **Cross-lane deps.** `web3-engineer` (x402 hop + tx schema); `staff-engineer` (SourceProvider Protocol seam from S12 must define the creator-attribution interface). `chunks.source_url_hash` lives on `sources` already — no chunk-row bloat.

## Theme 3 — App-launching template (`gecko_apps`)

1. **Sequencing.** Sprint 15+. Schema-light from my side; the heavy lift is scaffold tooling.
2. **Minimum schema.** New table:
   ```
   gecko_apps (
     id UUID PK,
     session_id UUID NOT NULL REFERENCES sessions(id),  -- the validation that birthed it
     project_id UUID,
     owner_wallet TEXT NOT NULL,
     bazaar_listing_id TEXT,
     domain TEXT,
     scaffold_template TEXT NOT NULL,
     marketplace_cut_bps INT NOT NULL DEFAULT 150,  -- 1.5%
     created_at TIMESTAMPTZ DEFAULT now(),
     deleted_at TIMESTAMPTZ
   )
   ```
   Plus `app_settlements` view joining `x402_settlements` filtered by registered Bazaar listing IDs — that's how `business-manager` accounts the 1-2% registrar fee without a separate ledger.
3. **Risks.** Marketplace-cut accounting needs a settlement source of truth. If we only see settlements that route through our facilitator, off-platform settlements silently leak. Make this constraint explicit with `business-manager` before promising % cuts.
4. **Cross-lane deps.** `web3-engineer` (Bazaar registration receipts), `business-manager` (cut % + COGS), `staff-engineer` (do we host the app, or just record it?).

## Theme 4 — Cloudflare x402 (consumer)

1. **Sequencing.** Sprint 14, parallel to Paragraph.
2. **Schema impact.** **None confirmed.** `sources.type` extends to `'cloudflare'`; `x402_settlements.network` already accepts new providers (012). Embeddings unchanged. The chunks table is provider-agnostic by design — that's the point of SourceProvider Protocol.
3. **Risks.** Cost. Cloudflare-gated content can be expensive per fetch; the embedding cache is essential to avoid re-paying for the same URL. Confirm `chunk_embedding_cache` keys on content hash, not URL — it does.

---

## Transcripts archive (S12-EVAL-01) — DB or flat-file?

**Recommendation: stay flat-file in S12; promote to `judge_transcripts` table in S13 only if rubric v2 needs cross-run queries.**

Argument for flat: transcripts are immutable artifacts, append-only, rarely queried by ID, and large (full debate JSON). Filesystem + git-LFS or S3 is cheaper and faster than Postgres TOAST. JSON-blob queries in Postgres are slow without indexes we won't have time to design under S12.

Argument for DB (rubric v2 trigger): if rubric v2 wants "show me all transcripts where reviewer-A scored < 3 on dimension-X across the last 30 runs," that's a SQL query, not a `find | jq` shell pipeline. The moment a second consumer (eval gate UI, regression dashboard) shows up, flat-file ages badly.

**Concrete proposal:** keep flat-file as the source of truth; add a **thin index table** `judge_transcripts (id, run_id, fixture_id, rubric_version, scores_json, transcript_path, created_at)` that points at the file. No transcript text in Postgres. Pay the cost of the index only, not the storage. This is the standard "metadata in DB, blobs on disk" pattern and it composes with future S3 backing.

Defer to S14 unless eval-gate consumers materialize in S12.

---

## Sprint 13 ticket — S13-DATA-01

**Title:** Time-windowed chunk retrieval for `gecko_pulse`

**Migration:** `infra/supabase/migrations/20260501000000_chunks_temporal.sql`

**Scope (3-4 days):**
1. Add `chunks.captured_at TIMESTAMPTZ NOT NULL DEFAULT now()` (backfill = `sources.indexed_at`).
2. Add `chunks.project_id UUID NULL` with FK + nullable backfill from `sessions`.
3. New RPC `match_chunks_windowed(p_scope_id UUID, p_scope TEXT, p_query VECTOR(1536), p_since TIMESTAMPTZ, p_top_k INT)` where `p_scope` ∈ `('session','project')`. Pre-filter on scope + `captured_at >= p_since` before vector op.
4. Index `idx_chunks_project_captured ON chunks (project_id, captured_at DESC) WHERE project_id IS NOT NULL`.

**Acceptance criteria:**
- [ ] Migration applies cleanly on `supabase db reset` and forward-only on existing dev DB.
- [ ] `pytest packages/gecko-core/tests/rag/` passes; new test: query with `since=now() - 14 days` returns only fresh chunks.
- [ ] EXPLAIN on `match_chunks_windowed` shows `session_id`/`project_id` + `captured_at` filter applied before ivfflat scan.
- [ ] `gecko-mcp doctor` green; existing `match_chunks` RPC unchanged (no regression).
- [ ] No write-path change for ingestion; `captured_at` defaults at insert.

This unblocks Theme 1 directly and is reusable by Theme 2 (Paragraph posts have publish dates that map cleanly to `captured_at`).
