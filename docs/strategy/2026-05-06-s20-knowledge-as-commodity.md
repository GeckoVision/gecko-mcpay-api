# S20 Plan — Knowledge as Commodity

**Window:** 2026-05-10 → 2026-05-17 (proposed, ~6 working days solo)
**Predecessor:** S19 (Voyage/Mongo hardening — H1/H2/H4 shipped 2026-05-05)
**Author:** staff-engineer (synthesis), data-engineer (Track A), web3-engineer (Track B), ai-ml-engineer (Track C)
**Theme:** Lay the foundation for the categorized, compounding knowledge base. Verdicts become the output format of consuming the base; the moat is the categorized vector base that gets denser per query and re-sells categorized retrieval endpoints to external agents via MCP/x402.

**Reference docs:**
- Manifest sketch: `docs/strategy/2026-05-05-agent-skills-manifest-sketch.md`
- Pricing math: same doc (verified against live `bb research` smoke 2026-05-05–06)
- Memory: `project_knowledge_as_commodity_pivot`, `reference_pay_sh`

**Verbosity-smoke verification (2026-05-06):** local gecko-api booted with `LOG_LEVEL=DEBUG`, two `bb research` runs at `tier=basic preset=budget` produced clean OpenRouter dispatch (`openai/gpt-4.1-mini-2025-04-14` via OpenRouter), Voyage embed (1024-dim Mongo), and zero errors. Total cost per session: ~$0.043. Proceed.

---

## Three tracks

### Track A — Mongo consolidation + categorized-knowledge schema (data-engineer)

Spine of the sprint. Six tickets, ordered by dependency.

| # | Ticket | Owner | Effort | Acceptance |
|---|---|---|---|---|
| **A1** | **S20-A-TAXONOMY-01** | data-eng | XS | Single-source-of-truth module `packages/gecko-core/src/gecko_core/knowledge/taxonomy.py`. `Category` Literal (7 values), `Subcategory` map, `KnowledgeSource` Literal (`web` \| `tavily` \| `twit_sh` \| `bazaar` \| `pay_sh` \| `user_query` \| `enriched_output`), `ChunkMetadata` TypedDict (`confidence: float`, `usage_count: int`, `timestamp: datetime`). Schema-drift test mirrors `tests/test_payment_mode_consistency.py`. Pattern A enforced. |
| **A2** | **S20-A-CHUNK-SCHEMA-01** | data-eng | M | Extend `MongoChunkDoc` (`mongo_chunks.py:108-125`) with `category`, `subcategory`, `source`, `metadata.{confidence,usage_count,timestamp}`. Alias `provider_kind` → `source` (deprecated read-only mirror for one sprint). New `gecko_core/knowledge/classifier.py` (`gpt-4o-mini`, `response_format=json_object`, ≤1.5k input tokens, batch=20). Reject writes missing `category`/`source`. Mongo validator JSON enforces enum from A1. |
| **A3** | **S20-A-LEGACY-REVOKE-01** | data-eng | S | Per `project_mongo_cutover_no_backfill`: stamp legacy chunks `category="legacy_uncategorized"`, `metadata.deprecated=true`. Default `rag_query` filter excludes legacy unless `include_legacy=True`. Build index on `(category, project_id, captured_at)`. |
| **A4** | **S20-A-PRECEDENT-PORT-01** | data-eng | M | Port `gecko_precedent` Postgres table → Mongo `precedents` collection (Voyage 1024). Eliminates the 1536-dim Postgres tail that produced S19's dimension churn. Spike eval: ≥0.7 Jaccard top-5 overlap vs current pgvector before merge. Postgres migration `revoke_writes_gecko_precedent.sql` keeps table for read-fallback one sprint. |
| **A5** | **S20-A-MEMORY-PORT-01** | data-eng | M | Same shape as A4 for `memory` table. After this lands, pgvector has zero active write paths. `embed_for_postgres_vector` is unreferenced (grep guard). |
| **A6** | **S20-A-USAGE-COUNT-01** | sw-eng | S | `usage_count` bumps on **citation in output** (not retrieval). Synth emits `cited_doc_ids`; async batch `$inc` per cited chunk. Structured log line `chunk_cited` with `chunk_id`, `category`, `confidence`. |

**Track A risks:**
- Old-vs-new chunk boundary → fresh-start cutover (A3), reject classifier-on-read.
- Classifier latency on ingest → batch=20, gpt-4o-mini, +~8s per 100-chunk session is acceptable.
- `provider_kind` / `source` semantic drift → alias one sprint, drop in S21.
- Voyage-1024 retrieval quality on precedents → spike eval before A4 merge.
- Mongo Atlas index storage with new `(category, …)` compound → monitor; budget paid tier.

---

### Track B — Manifest publishing + per-skill x402 dispatch (web3-engineer)

Six tickets. Wire the publishing surface and the gate.

| # | Ticket | Owner | Effort | Acceptance |
|---|---|---|---|---|
| **B1** | **S20-B-SKILL-REGISTRY-01** | sw-eng | M (1.5d) | Canonical `Skill` dataclass + 12 entries in `gecko_core/skills/registry.py`. `manifest.py` builds the pay.sh v1.0 shape with `pricing` and `gecko_knowledge_category` extension fields. Schema-drift test against pay.sh required keys + price floors matching existing `/pricing`. |
| **B2** | **S20-B-MANIFEST-ENDPOINT-01** | sw-eng | S (0.5d) | Publish at `app.geckovision.tech/.well-known/agent-skills/index.json`. `Cache-Control: public, max-age=300`, ETag. **Description copy gate:** business-manager + product-designer must sign off on the 12 description strings before merge — per memory `project_output_layer_positioning`, must position as "structured insight layer" not "API at $X." |
| **B3** | **S20-B-X402-DISPATCH-01** | web3-eng | M (2d) | Single `POST /skills/{skill_name}` route — no 12 hard-coded paths. New `payments/gate.py` and `payments/dispatch.py` (facilitator-neutral). Reuses existing `X402Client`, `get_client(mode)`. Switching `X402_CHAIN` env requires zero code change. Skills declare `supported_chains`, never a facilitator. |
| **B4** | **S20-B-CREDIT-PACK-01** | web3-eng | M (2d) | `credit-pack` ($10 / 1.5M tokens) — Ed25519-signed JWT (`sub=wallet, jti=on_chain_tx_sig, tokens_remaining, exp`). Server-held key; `jti` is settlement tx signature (anti-replay). Mongo collection `credit_tokens(jti PK, ...)`. Atomic decrement with row-lock; double-spend test fails one cleanly. |
| **B5** | **S20-B-DISPATCH-HANDLERS-01** | sw-eng | M (1.5d) | Thin per-skill handlers in `gecko_core/skills/handlers.py`. `retrieve-*` → `rag_query`, `research-*` → existing pro orchestration, `research-full` → full pipeline. Bundled-token meter enforced (50K/100K/200K/500K caps → overage billed via x402 supplemental intent OR credit-token decrement). |
| **B6** | **S20-B-CONTRACT-TESTS-01** | web3-eng | S (1d) | (a) pay.sh-style discovery contract — fetch our manifest, resolve each skill URL, assert 402 shape. (b) Facilitator `/verify` contract tests with VCR-recorded fixtures (Pattern C) for frames.ag (Solana) + CDP (Base). `live_skills` pytest marker, gated on `RUN_LIVE_SKILLS=1`. |

**Track B risks:**
- **Bulk-credit token forgery** → Ed25519 JWT with `jti=settlement_sig`, server-held key. Document key-rotation procedure.
- **Facilitator hard-coding** → single dispatcher; schema-drift test asserts no skill hard-codes a facilitator URL.
- **gecko-claude / pay.sh discovery mispositioning** → B2 description copy gate. Use `gecko_knowledge_category` values that signal layer-position (`insight.retrieval`, `insight.debate`, `insight.pipeline`).

---

### Track C — Citation extraction + enrichment loop (ai-ml-engineer)

Seven tickets. Closes the compounding flywheel.

| # | Ticket | Owner | Effort | Acceptance |
|---|---|---|---|---|
| **C1** | **S20-C-CITATION-CONTRACT-01** | ai-ml + sw-eng | S | Extend synth output schema with `cited_doc_ids: list[str]` and `citations: list[Citation]`. `[N]` markers in prose map 1:1 to `citations[i].idx`. Post-validate; drop unmatched IDs; log drop rate. Touches `models.py`, `judges/synth.py`, `orchestration/pro/post_processors.py`, `orchestration/basic.py`. |
| **C2** | **S20-C-CONFIDENCE-PROMPT-01** | ai-ml | S | Per-team confidence self-rating prompt scoring 3 dimensions (evidence_floor, dissent_quality, citation_density), returning `min`. Per-section emission + document-level min aggregate. Calibration target: 0.9 = dense base + multi-citation; 0.3 = sparse + live-fetch dominant. 5-idea fixture suite, manually-graded ±0.15 on 4/5. |
| **C3** | **S20-C-CLASSIFIER-01** | ai-ml | S | Query-time category classifier (gpt-4o-mini, ≤$0.001/call) wired in `workflows.ask` and `orchestration/basic.py` entry. 50-query labeled fixture: top-1 ≥0.75, top-3 recall ≥0.92. Categories imported from canonical enum (Pattern A). |
| **C4** | **S20-C-ENRICHMENT-WRITER-01** | ai-ml + sw-eng | M | New `gecko_core/flywheel/enrichment.py`: concat `query+verdict.summary+cited_chunk_texts`, embed via Voyage, search top-1 in same `(category, subcategory)`. **De-dup threshold cosine ≥ 0.93** → bump existing chunk's `usage_count` + append `query` to `metadata.queries[]` (cap 20). Else insert with `source=enriched_output`. Threshold env-tunable (`GECKO_ENRICH_DEDUP_COSINE`). |
| **C5** | **S20-C-CONFIDENCE-GATE-01** | ai-ml | XS | Only enrich when `verdict.confidence ≥ 0.6`. Lower-confidence outputs pollute the base. Threshold env-tunable, ratchet up as base densifies. |
| **C6** | **S20-C-REACHABILITY-TEST-01** | ai-ml | S | `tests/integration/test_enrichment_loop.py`: run `bb research` twice. Asserts (a) confidence emitted, (b) `cited_doc_ids` propagated to `usage_count` bumps, (c) enriched chunk visible in run-2 retrieval. Per `feedback_wedge_reachability_check` — every "X is wired" claim demands end-to-end audit. |
| **C7** | **S20-C-EVAL-LIVE-01** | ai-ml | S | Parallel `runner_live.py --enrichment-loop` records confidence, cited_doc_ids, enriched_chunk_id into `tests/eval/live_runs/`. Track over 5 runs: base density (chunk count by category), live-fetch ratio, mean confidence drift. 2 baseline runs before any threshold tuning. Closes `feedback_eval_harness_rag_gap` for the new pipeline. |

**Track C risks:**
- Model hallucinates doc IDs not in retrieval → post-validate, drop unmatched, log rate.
- Confidence collapses to single value → forced-spread instruction or swap min→mean.
- 0.93 dedup threshold from intuition → calibrate with 100 real queries post-S20.
- Enrichment-loop confound with retrieval changes → pin embedder + retrieval params; only enrichment varies.

---

## Cross-track dependencies

```
A1 ─┬─ A2 ─┬─ A3 ─┬─ A4 ─┬─ A5
    │      │      │      │
    │      │      └─ A6 ─┘
    │      │             │
C3 ─┘      │             │
            └─ C1 ─ C2 ─ C4 ─ C5 ─ C6 ─ C7

B1 ─ B2 ─┬─ B3 ─┬─ B5 ─ B6
         │      │
         └─ B4 ─┘
```

**Critical path (5d):** A1 → A2 → C1 → C4 → C6 + B1 → B3 → B5. Everything else parallelizes.

**Soft order:**
- Day 1: A1, B1, C3 in parallel.
- Day 2: A2, B2, C1.
- Day 3: A3 + B3 starts + C2.
- Day 4: A4 + B3/B4 in parallel + C4.
- Day 5: A5 + B5 + C5.
- Day 6: A6 + B6 + C6 + C7.

---

## Sprint total

**19 tickets, ~13 dev-days of work compressed via parallel tracks into 6 wall-clock days.**

Effort mix: 1×XS (A1, C5), 8×S, 9×M, 0×L. No XL — Pattern C eats the long pole here (contract tests + reachability), and we deliberately avoided one big "ship the whole flywheel" ticket.

---

## Out of scope (S21+)

- Quality-tier multiplier or token-only billing for Claude Opus calls. Today's flat-fee floor handles budget/balanced; quality needs a separate pricing surface.
- Manifest version 1.1 with `bundled_tokens_consumed` reporting headers (so agents see remaining bundle).
- pay.sh-side discovery telemetry (do they actually crawl us? how often?). Wait until B2 ships.
- twit.sh broadening to non-X social via Apify — explicitly deferred (locked: X-only for now).
- Drop legacy Supabase pgvector tables — wait for ≥3 days of doctor-green post-A5 before A5-followup `S21-DROP-PGVECTOR`.
- Quality / quality-tier multipliers, tiered bulk packs ($25, $100), team-dedicated retrieval quotas.

---

## Verification checklist

End-of-sprint smoke (after all tracks merge):

```bash
# 1. Doctor — Voyage live ping + Mongo dim verify both green
uv run gecko-mcp doctor --live

# 2. Mongo schema test
uv run pytest packages/gecko-core/tests/knowledge/ tests/integration/test_enrichment_loop.py -q

# 3. Manifest endpoint
curl -s http://localhost:8000/.well-known/agent-skills/index.json | jq '.skills | length'   # expect 12

# 4. x402 dispatch (stub mode)
RUN_LIVE_SKILLS=0 uv run pytest packages/gecko-api/tests/contract/ -q

# 5. End-to-end research with enrichment
uv run bb research --idea "S20 dogfood smoke" --tier basic --tier-preset budget
# expect: ≥1 cited_doc_id, confidence emitted, follow-up `bb research` on similar idea retrieves the enriched chunk
```

---

## Decision log

- **2026-05-05** — pivot from "judgment as commodity" to "knowledge as commodity" (memory `project_knowledge_as_commodity_pivot`).
- **2026-05-05** — pricing model locked: flat per-call + token bundled + overage + bulk credit pack. 12 skills total.
- **2026-05-06** — twit.sh = X-specific (Apify deferred).
- **2026-05-06** — confidence = LLM self-rating (citation-count deferred until judge corpus is mature).
- **2026-05-06** — `usage_count` bumps on **citation in output**, not retrieval.
- **2026-05-06** — no voice-prompt refactor; new teams are additive, current 5-voice advisor stays.
- **2026-05-06** — verbosity smoke against local gecko-api passed clean. Proceed.
