# S20 RAG Architecture — Build-Context Layer

**Date:** 2026-05-06 (data-engineer + staff-engineer / data-architect collaboration)
**Predecessor:** `docs/strategy/2026-05-06-s20-knowledge-as-commodity.md`
**Theme:** State-of-the-art RAG for the categorized build-context layer. Hybrid search + source-aware chunking + filterable compound vector index + opt-in HyDE + three-tier memory + default-on rerank for build-context endpoints.

---

## TL;DR — three new tickets for S20

| Ticket | Owner | Effort | Acceptance |
|---|---|---|---|
| **S20-RAG-01 — Source-aware chunker dispatch** | data-engineer | 3d | `chunker.py` dispatches by `source_kind`; `chunk_strategy` field on every chunk; backfill flag for re-chunk on next ingest; eval shows recall@10 ≥ baseline on gold set. |
| **S20-RAG-02 — Filterable compound vector index** | data-engineer | 2d | Atlas index declares `vertical`, `category`, `provider_kind`, `source_kind`, `deleted_at` as filterable; pre-filter pushdown verified via `explain`; p95 query latency ≤ current. Depends on RAG-01 schema fields. |
| **S20-RAG-03 — Default-on Voyage rerank for `gecko_build_context`** | ai-ml-engineer | 2d | `gecko_build_context` reranks by default; `retrieve.{category}` does not; kill-switch flag `GECKO_RERANKER_BUILD_CONTEXT`; cost telemetry per call; eval shows answer-accuracy lift ≥ 8pts on labeled set. Depends on RAG-02. |

---

## Architecture (summary)

### Chunking — source-aware dispatch

Reject single recursive 400/20 splitter. Dispatch by `source_kind`:

| Source | Strategy | Size / Overlap |
|---|---|---|
| Tavily web pages, Bazaar listings | Semantic (sentence-window) + parent-doc retrieval | 600–900 / 80 |
| twit.sh threads | Thread-atomic; whole thread if <1.5K chars | — |
| pay.sh / provider docs | Markdown-aware (heading + code-fence preservation) | up to 1.2K tokens / atomic code blocks |
| Regulated text (BCB, FinCEN, EU rules) | Section-aware (clause boundaries) | 800 / 100, never split clauses |
| Deep-research synthesis | Already structured; per H2 section | — |

Every chunk carries `chunk_strategy` field for retrieval-time A/B.

### Embedding model

- **Default:** `voyage-3` (1024-dim) — already in production.
- **Opt-in `voyage-3-large` (1024-dim) for `business_financial` + `investment_signals`** — domains where retrieval precision pays off.
- **`voyage-3-lite` for cheap-tier `retrieve.{category}` calls.**
- **Reject** multi-embedding-per-chunk: 2× storage and write-amp for marginal recall gain. The two-step pipeline (embed + rerank) gets us most of the intent-routing benefit at query time.

### Index design — single collection, filterable compound

Atlas filterable vector index. Declare `vertical`, `category`, `provider_kind`, `source_kind`, `freshness_bucket`, `deleted_at` as filterable on `chunks_vector` and `chunks_text`. Pre-filter pushes down before ANN.

Reject per-vertical sharding: 11 collections × 2 indexes = 22 to maintain, breaks cross-vertical queries (some build steps span verticals — neobank+infra_devtool, dex+wallet_tooling). Atlas filterable vector index is purpose-built for the multi-tenant shape.

### Retrieval pipeline

```
query
  → classify(vertical, category)                          # gpt-4o-mini, ~$0.0001
  → pre-filter {vertical, category, deleted_at: null}
  → parallel:
       $vectorSearch(top_k=40)
       $search BM25(top_k=40)
  → RRF fusion → top 20
  → Voyage rerank → top 5                                  # default-on for build-context
  → parent-doc expansion (if chunk has parent_doc_id)
  → return {text, source_url, score, parent_excerpt}
```

**HyDE: gated.** Only on pioneer-cell queries (sparse base). Adds ~1 LLM call (~150ms); not worth it on dense cells.

### Memory — three tiers

| Tier | Scope | Persistence | Vector-indexed? |
|---|---|---|---|
| Session memory | per `session_id` | TTL 24h | yes |
| Per-user project memory | per `(user_id, project_id)` | durable | yes — LangGraph checkpoint pattern |
| Per-vertical shared memory | anonymized aggregate | durable | yes — fused at RRF stage with weight 0.3 |

`gecko_build_context` queries all three. `retrieve.{category}` queries only the base.

### Pioneer-cell ingestion

Latency budget: **8s p50, 15s p95** for first call. Beyond → return partial + stream rest.

Fan-out: parallel Tavily(10) + twit.sh + Bazaar + pay.sh, 4s timeout each. Dedup by URL hash + MinHash near-dup (0.85 Jaccard). Classify via `gpt-4o-mini json_object`. Chunk per source-kind rules above. Embed in batches of 100. Pioneer's-tax surcharge calibrated post-hoc from real telemetry per cell — not pre-estimated.

### Reranking default

| Endpoint | Rerank default |
|---|---|
| `gecko_build_context(vertical, category, query)` | **ON** — high-stakes, low-volume, rerank cost ~$0.0005/call is noise vs downstream LLM cost |
| `retrieve.{category}` | **OFF** — cheap-tier wedge; opt-in only |

---

## Architect's critique (sanity-check on the design)

**Scalability.** 100k × 11 verticals × 7 categories = **7.7M chunks**. Atlas Vector Search HNSW at 1024-dim ≈ 6KB/vector raw + graph overhead → **~70GB working set** = M30+ tier minimum, RAM-bound. Filterable index helps query latency but doesn't shrink the graph. **Mitigation:** scalar quantization (int8) at 4× compression → ~17GB working set, recall loss <2% per Voyage benchmarks. **Plan quantization rollout at 2M chunks**, not 7M (revisit threshold quarterly).

**Quality drift.** As cells densify, cosine distributions compress (everything looks similar). Top-k recall stays flat but discrimination drops. **Rerank becomes load-bearing, not optional** — strongest argument for default-on rerank on build-context. Per-cell `score_threshold` recalibration quarterly; bake into eval harness.

**Operational complexity.** Single Atlas cluster + multi-tenancy via filterable index = operationally simple but blast-radius is total. One bad ingestion run poisons all verticals. Mitigations:
- Per-cell write quota.
- Ingestion dry-run mode.
- Continuous Atlas backup (default).
- Index rebuild as migration with maintenance window — 7M corpus rebuild is hours, not minutes.

**Cost trajectory.**
- One-shot embed at 100k×77 cells × 500 tok avg = 3.85B tokens × $0.06/M = **$231**.
- Re-embed on model change = same.
- Recurring rerank: 1M build-context calls/mo × $0.0005 = **$500/mo**. Acceptable; monitor.
- Atlas storage at M30+: ~$700–$1500/mo depending on tier.

**Eval methodology — three layers, all needed:**
1. **Recall@10** on labeled gold set per `(vertical, category)` — automated, nightly.
2. **Answer-accuracy** via LLM-judge on synthesized build-step queries — weekly.
3. **Build-step success rate** — did the user's next build step succeed? **The only metric that matters.** Instrument via session-outcome telemetry. Lagging but truthful.

---

## MongoDB-AI training tracks to take *now*

Per the user's screenshot, three modules are highest-leverage given this architecture:

1. **Vector Search Performance** (60 min, advanced) — quantization, RAM sizing, multi-tenancy. Directly informs the M30 vs M40 sizing decision and the 2M-chunk quantization trigger.
2. **Voyage AI with MongoDB** (45 min, foundational, NEW) — two-step pipeline + auto-embedding. Validates the default-on rerank choice.
3. **Memory for AI Applications** (60 min, intermediate, NEW) — LangGraph + Atlas Vector Search pattern. Informs the three-tier memory design.

The other modules (AI Data Strategy, Vector Search Fundamentals, RAG with MongoDB, AI Agents) are foundation-level and can be deferred or skimmed; the three above are the ones with direct architectural implications for S20.

---

## Sequencing within S20

Insert into existing dependency graph:

```
A1 — A2 — A3 — A4 — A5
      │
RAG-01 (chunker) ──┐
RAG-02 (filterable index) ──┤
                  C4 — C6 — C7
RAG-03 (rerank default) ────┘
```

RAG-01 unblocks RAG-02 unblocks RAG-03. RAG-03 should land after Track C's enrichment writer (C4) so rerank is exercised on freshly-enriched chunks.

**Effort:** +7 dev-days. S20 was 13d compressed into 6 wall-clock days; adding 7d compresses harder. **Recommendation:** stretch S20 to 8 wall-clock days, OR defer RAG-01 (chunker rewrite) to S21 since today's chunker still works (just suboptimal).

**My recommendation: defer RAG-01 to S21.** Ship RAG-02 + RAG-03 in S20 (4d). Chunker rewrite is a quality optimization, not a correctness fix; the moat ships first, the polish comes second.
