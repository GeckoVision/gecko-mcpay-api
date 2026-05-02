# S17-WEDGE-WIRE-01 — Path B Design Memo

**Date:** 2026-05-02
**Author:** staff-engineer
**Status:** for build (data-eng + software-eng + ai-ml)
**Reversibility:** mostly two-way (column add, code refactor); the `provider_kind` Literal is one-way once skills/API consumers depend on the values.

---

## RECOMMENDATION

Add `provider_kind` as a non-null defaulted column to both `chunks` and `sources`, route dispatched provider payloads through a thin `ingest_provider_chunks()` helper that reuses the existing embedder + `insert_chunks` path, and **keep `v1_block` as a prepended-context layer for now** (deprecate in S18). Gate the whole thing behind `GECKO_WEDGE_WIRE_ENABLED` so d57b8fd remains the demo fallback.

## WHY

- The diagnosis is correct: dispatched chunks today hit the cost ledger but never reach the LLM's retrieval context. The fix is structural, not prompt-plumb.
- The `chunks` table is already the right shape (text + 1536-dim vector + session_id). Adding `provider_kind` plus a synthetic `sources` row per (session, provider) is the smallest change that makes structured payloads first-class.
- Reusing the existing embedder + cache + audit + halving-retry path costs us one adapter per provider and zero new failure modes. A parallel ingestion path would double the surface area we have to keep in sync.
- v1_block does a *different* job (prepended absence-of-signal headings even when sources are empty) and the pro-debate prompt depends on its positional structure. Tearing it out in demo week is not the right risk.

## REPO(S) AFFECTED

`gecko-mcpay-api` only. No `gecko-mcpay-app` or `gecko-mcpay-skills` impact (the API contract on `match_chunks` gains a field — additive, frontend ignores until ai-ml ships citation rendering).

---

## 1. Schema decisions

### 1.1 Canonical `ProviderKind` Literal (Pattern A)

Lives in **`packages/gecko-core/src/gecko_core/sources/types.py`** (new module, or extend the existing one if present):

```python
ProviderKind = Literal["web", "youtube", "bazaar", "arxiv", "twitsh", "hn", "reddit", "gecko_precedent"]
PROVIDER_KINDS: tuple[str, ...] = get_args(ProviderKind)
```

Every provider module imports from here. `bazaar.types`, `arxiv.provider`, `twit_sh` get their `provider_kind` constant by reference, never by re-declaration.

A schema-drift test at `tests/test_provider_kind_consistency.py` mirrors `test_payment_mode_consistency.py`: asserts `get_args(ProviderKind)` equals the SQL `CHECK` constraint values. **This is non-negotiable** — Pattern A bit us four times on `PaymentMode`.

### 1.2 `chunks` column

```sql
ALTER TABLE chunks
  ADD COLUMN provider_kind TEXT NOT NULL DEFAULT 'web'
  CHECK (provider_kind IN ('web','youtube','bazaar','arxiv','twitsh','hn','reddit','gecko_precedent'));
COMMENT ON COLUMN chunks.provider_kind IS 'Mirrors gecko_core.sources.types.ProviderKind. Drift caught by tests/test_provider_kind_consistency.py.';
CREATE INDEX chunks_provider_kind_idx ON chunks (provider_kind);
```

`NOT NULL DEFAULT 'web'` covers backfill in one statement — every existing row is Tavily web. Migration is purely additive, fully reversible (`DROP COLUMN`).

### 1.3 `sources` column

Add the same column to `sources` with the same default. Rationale: the join in `match_chunks` already pulls `s.url`; surfacing `provider_kind` from `chunks` is sufficient for retrieval, but having it on `sources` lets `list_sources` group by provider for the dashboard without a chunk scan.

### 1.4 `sources` row strategy for non-URL providers

**Decision: one synthetic `sources` row per (session_id, provider_kind, resource_id).**

- Bazaar: `resource_id` = service slug (e.g. `bazaar://crypto-onramp/coinbase`). `url` column gets the synthetic URI; `url_hash` = sha256 of it. `type` stays as the existing `Literal["youtube","web"]` — **add `"provider"` to that Literal** as part of the same migration (Pattern A again — extend `infra/supabase/migrations/...sources_type_check.sql` CHECK).
- Arxiv: `url` = the actual arxiv abstract URL (it has one). `provider_kind='arxiv'`. Free real URL — no synthetic URI needed.
- twit.sh: one synthetic row per session, `url = twitsh://session/<session_id>`. Tweets are chunks under that one source. Rationale: tweets don't have stable canonical URLs we want to ingest individually, and one source row keeps `list_sources` readable.

This means `insert_source` gains a `provider_kind` and tolerates `type="provider"`. The existing `(session_id, url_hash)` UNIQUE handles idempotency for re-runs.

### 1.5 `match_chunks` RPC

```sql
RETURNS TABLE (
  id UUID, source_id UUID, source_url TEXT, chunk_index INT,
  text TEXT, similarity FLOAT,
  provider_kind TEXT  -- NEW
)
```

Add `c.provider_kind` to the SELECT. **No other shape changes.** Per-provider score boosts are applied in Python by ai-ml (their lane) so retrieval stays cheap and tunable without DB redeploys.

`match_chunks_windowed` gets the same field added.

---

## 2. Embedding pipeline integration

### 2.1 Adapter location

Each provider module owns its `to_embedding_text()` adapter:
- `gecko_core/sources/bazaar/embed_adapter.py`
- `gecko_core/sources/arxiv/embed_adapter.py`
- `gecko_core/sources/twit_sh/embed_adapter.py`

Each exposes `def to_chunks(payload: dict) -> list[ProviderChunk]` where `ProviderChunk` is a tiny dataclass: `(resource_id: str, chunk_index: int, text: str, metadata: dict)`. **No shared `_embed_adapter.py` module** — the rendering logic per provider is sufficiently different (Bazaar JSON description vs. Arxiv abstract vs. tweet body) that a shared adapter would be a switch statement masquerading as abstraction.

### 2.2 Ingest path

**One new function** in `gecko_core/ingestion/pipeline.py`:

```python
async def ingest_provider_chunks(
    *, session_id: UUID, provider_kind: ProviderKind,
    resource_id: str, chunks: list[ProviderChunk], store: SessionStore,
) -> int
```

Internally:
1. `store.insert_source(session_id, url=synthetic_uri, url_hash=..., type_="provider", provider_kind=provider_kind)` (idempotent).
2. Filter empties (existing `_filter_embeddable`).
3. Look up `get_chunk_cache(url_hash, indices)` — same model fingerprint check as Tavily.
4. Embed the misses via existing `Embedder` (same retry semantics, same budget).
5. `store.put_chunk_cache(...)` + `store.insert_chunks(session_id, source_id, chunks_with_provider_kind=...)`.
6. Audit row via existing `chunks_write_audit`.

`insert_chunks` gains a `provider_kind` parameter (defaults to `"web"` for Tavily back-compat). Single new path, single new column on the DB write.

### 2.3 Cost delta

Today's failing run dispatched ~8 structured chunks. text-embedding-3-small at $0.02/1M tokens, ~200 tokens/chunk avg → **~$0.000032/run added embed cost**. Negligible. No budget gate adjustment needed; the existing `budget_gate` in the embedder already covers it.

### 2.4 Failure isolation

A single chunk failing to embed must not fail the session. Existing `Embedder` retry shape covers transient OpenAI errors; persistent failures already write a `chunks_write_audit` row with `error_kind`. The new path inherits this — **no new failure modes**. If the *entire* provider's chunks fail to embed, the session continues with whatever chunks did land plus Tavily — exactly today's degradation contract.

---

## 3. Retrieval + scoring

### 3.1 RPC shape

Already covered in §1.5: just `provider_kind` added to the return tuple. ai-ml-engineer is unblocked the moment data-eng + software-eng land their tickets.

### 3.2 Citation format

**Recommendation: keep the existing `[N] <uri>` format. Use the URI scheme as the type signal.**

- Web/YouTube: `[1] https://...`
- Bazaar: `[2] bazaar://<service>/<resource>`
- Arxiv: `[3] https://arxiv.org/abs/2401.12345` (real URLs, no scheme trick needed)
- twit.sh: `[4] twitsh://<tweet_id>` with the handle in the chunk text itself

Rationale: the basic-tier citation validator (`orchestration/basic.py`) already parses `[N] <token>` and only strict-validates `https://`. Extending it to accept `bazaar://` / `twitsh://` is a 5-line addition. A typed citation shape (`{n: 1, kind: "bazaar", uri: "..."}`) is a contract change that ripples to the API, the frontend, and the eval harness — too much surface for one ticket. Defer to S18 if ai-ml needs structured citations for richer pro-tier rendering.

The pro-tier judge prompt (CITE-03 ticket) needs one new line: *"Citations may use https://, bazaar://, twitsh:// or arxiv URIs. All are valid evidence."*

---

## 4. V1 block coexistence

**Decision: keep v1_block as-is for now. Do NOT route HN/Reddit/twit.sh through chunks in this sprint.**

Reasoning:
- v1_block's "always render the heading even when empty" contract is what makes the pro-debate prompt's positional reasoning work. Removing it changes pro-tier verdict shape — out of scope for a wedge-wire ticket.
- twit.sh appears in BOTH paths now (v1_block for pro debate + chunks for retrieval). That's intentional — pro tier gets prepended structured signal AND retrieval-grounded evidence. The cost duplication is one extra embed per tweet (~$0.00001/run) and stub mode pays nothing.
- Bazaar and Arxiv are NEW; they only flow through the chunks path. No duplication.
- gecko_precedent stays in v1_block — it's already a typed retrieval over a different table; folding it into `chunks` is a separate refactor.

**S18 follow-up ticket** (not part of this sprint): unify v1_block dispatch with the chunks path, with v1_block becoming a *render layer* over retrieved chunks rather than a parallel dispatcher. That's the right end state. Demo week is not the time.

---

## 5. Ticket breakdown

### S17-WEDGE-DATA-01 — data-engineer

**Acceptance:** migration applied; `match_chunks` and `match_chunks_windowed` return `provider_kind`; `tests/test_provider_kind_consistency.py` passes; existing chunks all read `provider_kind='web'`.

**Touches:** `infra/supabase/migrations/20260502000000_provider_kind.sql`, `gecko_core/sources/types.py` (new), `gecko_core/sessions/store.py` (extend `ChunkMatch` + `insert_source` signature; do NOT change `insert_chunks` body — that's WIRE-02), drift test.

**Don't touch:** dispatcher in `workflows.py`, ingestion pipeline, prompts.

### S17-WEDGE-WIRE-02 — software-engineer

**Acceptance:** `bb research --idea "..."` in stub mode produces `chunks` rows with `provider_kind` in `{web, bazaar, arxiv, twitsh}`; SQL spot-check shows ≥1 row per dispatched provider; existing Tavily ingestion unchanged; `_dispatch_stub_integration_providers` returns the same progress string today plus structured-attribution metrics; gated behind `GECKO_WEDGE_WIRE_ENABLED` (default `true` post-merge, `false` for the demo fallback build).

**Touches:** `gecko_core/ingestion/pipeline.py` (new `ingest_provider_chunks`), `gecko_core/sessions/store.py` (`insert_chunks` gains `provider_kind`), `gecko_core/sources/{bazaar,arxiv,twit_sh}/embed_adapter.py` (3 new files), `workflows.py` `_dispatch_stub_integration_providers` (call ingest after dispatch).

**Don't touch:** prompts, citation validator, retrieval scoring, v1_block.

### S17-WEDGE-CITE-03 — ai-ml-engineer

**Acceptance:** basic-tier citation validator accepts `bazaar://`, `twitsh://` URIs; pro-tier judge prompt updated; per-provider retrieval boost weights (their original ticket) applied in the Python-side post-RPC reranker; eval harness shows ≥1 non-web citation on the failing 2026-04-30 fixture rerun.

**Touches:** `gecko_core/orchestration/basic.py` citation regex, pro judge prompt module, retrieval reranker.

**Don't touch:** schema, ingestion path, dispatcher.

### (No 4th ticket needed.) v1_block stays untouched.

---

## 6. Demo-week risk + rollback (Pattern C)

### 6.1 Rollback story

`GECKO_WEDGE_WIRE_ENABLED=false` in env → `_dispatch_stub_integration_providers` falls back to the d57b8fd code path (cost ledger only, no chunk ingest). One env flip, no redeploy. **This is the demo fallback.**

If schema migration is the problem (unlikely — additive), `ALTER TABLE chunks DROP COLUMN provider_kind` is clean. The drift test will fail loudly first.

### 6.2 Contract test (Pattern C)

`tests/sources/test_provider_chunk_contract.py` per provider:
- Recorded fixture of a real Bazaar/Arxiv/twit.sh response.
- Run through `ingest_provider_chunks` against a test Supabase project.
- Assert: `chunks` rows exist with correct `provider_kind`, embeddings are 1536-dim, `match_chunks` returns them with the new field populated.

Gated by `live_provider_ingest` marker mirroring the `live_cdp` pattern from S12.5-TEST-04. Adding a new provider is gated on this test passing — exactly the Pattern C encoding.

### 6.3 Schedule risk

- Mon: DATA-01 lands (small migration, low risk).
- Tue: WIRE-02 lands behind flag, smoke-tested locally.
- Wed AM: Flip `GECKO_WEDGE_WIRE_ENABLED=true` in staging, run dogfood matrix.
- Wed PM: CITE-03 lands; verdict eval shows non-web citations.
- Thu: contract tests + demo dry-run.

If WIRE-02 slips past Wed, ship demo with flag off. The wedge claim ("structured providers are first-class") becomes a Friday-after-demo fast-follow rather than the demo centerpiece.

---

## OPEN QUESTIONS

1. **Pro-tier RAG retrieval scope:** does `_run_pro_debate` currently call `match_chunks` over the full session corpus, or only over Tavily sources? If the former, WIRE-02 is sufficient; if there's a Tavily-only filter somewhere, ai-ml needs to drop it as part of CITE-03.
2. **Bazaar live-mode dispatch:** today the dispatcher gates on `payment_mode == "stub"`. WIRE-02 ingesting Bazaar chunks is fine in stub. Live-mode wiring for Bazaar chunk ingest is a separate ticket coordinated with web3-eng.
