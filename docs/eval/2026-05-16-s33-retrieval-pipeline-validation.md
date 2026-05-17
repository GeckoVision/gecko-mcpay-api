# S33-#81 — Retrieval Pipeline Validation (stage-by-stage instrumented trace)

**Date:** 2026-05-16
**Branch:** `s33/paysh-renderer-fix`
**Ticket:** S33-#81
**Author:** data-engineer
**Scope:** DIAGNOSIS + harness DESIGN only. No retrieval-code or chunk changes.

---

## TL;DR

`citation_relevance` bounces 0.21–0.52 because **canon investor-literature
chunks never reach the panel** — not for any one fixture, for **all of them**.
The raw `$vectorSearch` candidate slate is 100% `protocol_native` (1–2 stray
`web`/`bazaar_live`). Zero `canon_*` chunks enter the top-75 candidate set,
even though the corpus holds **5,380 canon chunks correctly tagged
`vertical='dex'`** and every fixture's `must_cite_provider_kinds` lists
`canon_marks` / `canon_damodaran` / `canon_berkshire`.

The loss is at **Stage 4 — `$vectorSearch` ANN ranking**. It is an
**embedding / query-construction** problem, not an index, filter, or
ingest-tagging problem. Owning lane: **`ai-ml-engineer`**.

The `$match` protocol filter, the `vertical` pre-filter, the reranker, the
final `top_k`, and the panel formatter are all behaving correctly. The
reranker genuinely runs — but it can only reorder a slate that already
contains zero canon, so it cannot fix relevance.

---

## Stage diagram

```
  fixture.idea (raw text)
        │
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ STAGE 2/3  embed([idea], input_type="query")                 │
 │   voyage-3-large · 1024-dim · L2-normalised (norm=1.0)        │
 │   embedded text = BARE idea (no augmentation)                 │
 └─────────────────────────────────────────────────────────────┘
        │  query_vector (1024)
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ STAGE 4  $vectorSearch  (Atlas ANN, index=chunks_vector)      │
 │   filter: vertical=dex AND metadata.deprecated != true        │
 │   numCandidates=300 · limit=75 · exact=false                  │
 │   score = (1 + cosine) / 2                                    │
 │   ►► RELEVANCE LOST HERE — slate is 100% protocol_native ◄◄   │
 └─────────────────────────────────────────────────────────────┘
        │  ≤75 raw hits + vectorSearchScore
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ STAGE 5  $match  protocol ∈ {proto} OR [] OR missing          │
 │   then $limit 75 · $project (+score meta)                     │
 │   correct shape — but nothing to admit: 0 canon in slate      │
 └─────────────────────────────────────────────────────────────┘
        │  matched dicts
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ STAGE 6  voyage_rerank_dicts  (rerank-2 cross-encoder)        │
 │   GECKO_RERANKER=voyage · genuinely ran · input cap 20        │
 │   reorders by relevance, truncates to top_k=15                │
 └─────────────────────────────────────────────────────────────┘
        │  reranked top_k
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ STAGE 7  retrieve_trade_corpus_chunks returns 15 dicts        │
 └─────────────────────────────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ STAGE 8  _format_chunks → "[idx] (source) text" numbered      │
 │   block, capped at _RAG_CONTEXT_CHAR_CAP, into opening prompt │
 └─────────────────────────────────────────────────────────────┘
```

---

## Per-stage instrumented trace (kamino, drift, jupiter, jito)

Probe: `embed(input_type="query")` → literal `$vectorSearch` pipeline →
`$match` → `voyage_rerank_dicts` → `retrieve_trade_corpus_chunks`. Throwaway
scripts under `.gecko/s33-81-probe/` (gitignored, not committed).

### Stage 1 — Raw question
The verbatim fixture `idea` string. Example (kamino):
`"I'm considering depositing $5k into the Kamino JLP-USDC multiply vault at
current parameters. Entry now or wait?"`

### Stage 2/3 — Embedded text & query vector

| fixture | embedded text | input_type | model | dim | L2 norm | tokens |
|---|---|---|---|---|---|---|
| kamino | bare idea | `query` | voyage-3-large | 1024 | 1.000000 | 26 |
| drift | bare idea | `query` | voyage-3-large | 1024 | 1.000000 | 32 |
| jupiter | bare idea | `query` | voyage-3-large | 1024 | 1.000000 | 28 |
| jito | bare idea | `query` | voyage-3-large | 1024 | 1.000000 | 30 |

- The embedded string is the **bare idea** — no protocol/vertical/as-of
  augmentation, no canon-priming context.
- 1024-dim matches the corpus: `protocol_native` and `canon_*` chunks both
  store 1024-dim vectors. **Dim/model are consistent.** No 1536/1024 drift.
- Query vector is L2-normalised (norm = 1.000000); stored chunk vectors are
  also normalised (norm = 1.000000).

### Stage 4 — `$vectorSearch` (literal pipeline issued)

```json
{"$vectorSearch": {
  "index": "chunks_vector", "path": "embedding",
  "queryVector": "<1024-float query vector>",
  "numCandidates": 300, "limit": 75, "exact": false,
  "filter": {"vertical": {"$eq": "dex"},
             "metadata.deprecated": {"$ne": true}}}}
```

Raw candidate slate (before `$match`):

| fixture | raw hits | score max | score min | provider_kind distribution |
|---|---|---|---|---|
| kamino | 75 | 0.7761 | 0.7485 | **protocol_native ×75** |
| drift | 75 | 0.8059 | 0.7693 | protocol_native ×73, web ×2 |
| jupiter | 75 | 0.8075 | 0.7658 | protocol_native ×73, bazaar_live ×2 |
| jito | 75 | 0.7877 | 0.7314 | **protocol_native ×75** |

**Verdict: WRONG.** Zero `canon_*` chunks in any candidate slate.
`score = (1 + cosine) / 2` (reconciled exactly against stored vectors —
atlas_score 0.7761 == `(1 + 0.5523)/2`). So the live band is **true cosine
0.55–0.61** — flat and narrow. The slate is monoculture protocol_native.

### Stage 5 — `$match` protocol filter

| fixture | survived | dropped | survived pk distribution |
|---|---|---|---|
| kamino | 65 | 10 | protocol_native ×65 |
| drift | 75 | 0 | protocol_native ×73, web ×2 |
| jupiter | 62 | 13 | protocol_native ×62 |
| jito | 50 | 25 | protocol_native ×50 |

**Verdict: filter shape is CORRECT** — `protocol == proto` OR `$size:0` OR
missing. The drops are other-protocol `protocol_native` chunks (e.g. jito's
743-chunk corpus filtered down for a kamino query), which is intended. The
filter cannot admit canon because **no canon chunk ever arrived from
Stage 4**. The `protocol=[]` branch is live and correct; it has nothing to
match.

### Stage 6 — Rerank

| fixture | input | output | reranker_ran | top rerank_score |
|---|---|---|---|---|
| kamino | 65 | 15 | **true** | populated |
| drift | 75 | 15 | **true** | populated |
| jupiter | 62 | 15 | **true** | populated |
| jito | 50 | 15 | **true** | 0.676 → 0.414 |

**Verdict: reranker GENUINELY RAN** — every output dict carries a populated
`rerank_score` (not the silent `chunks[:top_n]` degrade path). `rerank-2`
re-ordered the slate by relevance. But it can only reorder protocol_native
chunks; it cannot inject canon that was never retrieved. Note: the reranker
input is capped at `RERANK_TOP_K_INPUT=20` inside `voyage_rerank_dicts`, so
only the top-20 of the 50–75 matched chunks are actually re-scored — the
rest are discarded. That cap is fine here, but it means the over-fetch
`top_k*5` slate is mostly thrown away before rerank.

### Stage 7 — Final `top_k`

All four fixtures: `retrieve_trade_corpus_chunks` returns 15 chunks,
**100% `protocol_native`**, 0% canon.

### Stage 8 — Panel view

`_format_chunks` renders `[idx] (source) text`, numbered for citation,
char-capped. Shape is correct. The panel is handed 15 protocol_native API
dumps and **zero investor-canon framework chunks** — so when the LLM judge
scores `citation_relevance` against fixtures that demand
`canon_marks`/`canon_damodaran` citations, it cannot win. The 0.21–0.52
bounce is the judge reacting to which protocol_native chunks happened to
survive rerank — pure noise on an already-broken slate.

---

## Hand-built "ideal" vs issued pipeline (kamino)

**Issued** (Stage 4 above) → 75/75 protocol_native, 0 canon.

**Hand-built ideal:** the same query embed run against the index with **no
`vertical` filter** and `limit=100` returned `protocol_native ×99,
canon_marks ×1`. With a deliberately canon-phrased query
(*"Howard Marks on the risk of leverage and the importance of liquidity in a
downturn"*) the top-30 came back **canon_marks ×24, canon_berkshire ×5,
canon_macro ×1**.

**Divergence:** the issued pipeline's filter and index are fine — canon is
fully reachable and correctly `vertical='dex'`. The divergence is purely
**embedding-space distance**: a *trade-idea-phrased* query sits ~0.55 cosine
to protocol_native API text and only ~0.38 to canon prose. The pipeline
issues a structurally correct query; the *query text/embedding* is the
defect. No NL2Query step exists, as expected — the "query" is the embedded
idea, and that idea, embedded bare, simply does not land near canon.

---

## Asymmetric-embedding sub-finding

Measured cosine of the kamino idea vs a fixed `canon_marks` chunk and a
`protocol_native/kamino` chunk, by `input_type`:

| query input_type | cos vs canon_marks | cos vs pn_kamino |
|---|---|---|
| `query` (what retrieval uses) | 0.3828 | 0.3627 |
| `document` | 0.5275 | 0.5614 |
| `None` | 0.4103 | 0.4090 |

The live `$vectorSearch` band is true-cosine ~0.55, which matches the
**`document`** row, not the `query` row — i.e. the **stored corpus vectors
behave as if the effective query/corpus pairing lands in the document-style
band**. The S33-#79 change embeds the *query* with `input_type="query"`
while #80 re-embedded the corpus with `input_type="document"`. The numbers
show `query`-side embedding *widens* the gap (canon drops to 0.38) rather
than closing it. **This needs `ai-ml-engineer` to confirm the asymmetric
pairing is actually net-positive** — on this evidence, symmetric
(`None`/`None`) or `document`/`document` would rank canon higher.

---

## Ranked findings (each tagged with owning lane)

| # | Severity | Finding | Lane |
|---|---|---|---|
| 1 | **CRITICAL** | Canon chunks never enter the `$vectorSearch` candidate slate (0/75 every fixture). Trade-idea queries are ~0.55 cosine to protocol_native API text, ~0.38 to canon prose — canon loses the ANN race outright. Every fixture's `must_cite_provider_kinds` demands canon. | **ai-ml-engineer** (query construction / embedding) |
| 2 | **HIGH** | `input_type="query"` *widens* the query↔canon gap (0.41→0.38) vs symmetric. The S33-#79 asymmetric-retrieval assumption is unverified and the measured numbers contradict it. Validate before keeping. | **ai-ml-engineer** (rerank/embed tuning) |
| 3 | **HIGH** | Single ANN pool with no per-`provider_kind` quota. `rag_query` already has `_rerank_by_provider` quota rescue (see `voyage_rerank.py` docstring); the trade-panel path does **not** — it goes straight from `$vectorSearch` to `voyage_rerank_dicts`. Canon has no structural floor. | **ai-ml-engineer** (retrieval architecture) / data-engineer (if a separate canon `$vectorSearch` leg is added) |
| 4 | MEDIUM | Reranker only re-scores `RERANK_TOP_K_INPUT=20` of the 50–75 matched chunks; the rest of the `top_k*5` over-fetch is discarded pre-rerank. Over-fetch width is partly wasted. | ai-ml-engineer (rerank tuning) |
| 5 | LOW | Embedded text is the bare idea — no protocol/as-of/vertical priming. A retrieval-oriented query rewrite could pull canon closer. | ai-ml-engineer (query construction) |
| 6 | INFO | `vertical` filter, `protocol` `$match` (incl. `protocol=[]` branch), dim/model consistency (1024 across all pk), reranker execution, `_format_chunks` — **all verified correct.** No data-engineer index/ingest defect found. | — |

**No `data-engineer`-lane defect.** The index advertises the right
filterable paths, canon is tagged `vertical='dex'` and `protocol=[]`
correctly, dims are uniform 1024, and `protocol_native` ingest tagging is
correct. The fix is entirely in the `ai-ml-engineer` lane: query
construction, the asymmetric-embedding decision, and adding a canon
retrieval floor.

---

## Deliverable 2 — Deterministic retrieval eval (no LLM judge)

### Why

`citation_relevance` is an LLM judge — at N=10 its variance swamps signal
(see `2026-05-16-s33-rubric-statistical-review.md`). A deterministic eval
isolates *"is retrieval finding the right chunks"* from *"is the panel
reasoning well"* and is bit-for-bit reproducible. It would have caught
finding #1 in one run instead of six rubric runs.

### Ground truth — where it lives

Extend each fixture in `tests/eval/suites/defi_trade_rubric_suite.json`
with a `retrieval_expectations` block. Ground truth is defined by
**provider-kind composition + content signatures**, NOT a brittle hardcoded
chunk-id list (chunk ids churn every daily protocol_native re-ingest):

```json
"retrieval_expectations": {
  "required_provider_kinds": {
    "protocol_native": 1,
    "canon_marks": 1,
    "canon_damodaran": 1
  },
  "required_protocol_match": "kamino",
  "content_signatures": [
    {"label": "kamino_vault_params",
     "any_substring": ["JLP-USDC", "multiply", "leverage factor"],
     "must_match_provider_kind": "protocol_native"},
    {"label": "leverage_prudence_canon",
     "any_substring": ["liquidity", "leverage", "downturn"],
     "must_match_provider_kind": "canon_marks"}
  ],
  "k": 15
}
```

A "relevant" retrieved chunk = its `provider_kind` is in
`required_provider_kinds` **and** (if it carries a `content_signature`
constraint) its text matches one signature. This keeps ground truth stable
across re-ingests because it matches on *kind + content*, not *id*.

### Metrics (all deterministic)

For each fixture, against the slate `retrieve_trade_corpus_chunks` returns:

- **provider_kind coverage** — fraction of `required_provider_kinds`
  present at all in the top-k. (This single metric is 0.0 today for canon.)
- **precision@k** — relevant chunks ÷ k.
- **recall@k** — distinct required kinds satisfied ÷ required kinds.
- **MRR** — reciprocal rank of the first relevant chunk per required kind,
  averaged.
- **canon_floor** — boolean: ≥1 `canon_*` chunk in the final slate.
  (Direct probe for finding #1; would be `false` for all 10 fixtures now.)

Report mean ± per-fixture breakdown. Also dump the **Stage-4 raw slate
pk-distribution** so a regression in ANN ranking is visible even when the
reranker masks it downstream.

### Harness shape

New script `tests/eval/scripts/retrieval_eval.py` (proposal — not wired to
CI yet). Mirrors the existing `tests/eval/scripts/` layout:

```
for fixture in defi_trade_rubric_suite.json:
    slate = await retrieve_trade_corpus_chunks(
        idea=fixture.text, protocol=fixture.protocol,
        vertical=fixture.vertical, top_k=fixture.retrieval_expectations.k)
    score = grade_retrieval(slate, fixture.retrieval_expectations)
emit JSON → tests/eval/live_runs/<date>-s33-retrieval-eval.json
```

- **No LLM.** Pure set-membership + substring matching. Runs in seconds,
  costs only the embed + Atlas query (~$0).
- **Plugs in alongside the rubric, not inside it.** The rubric keeps
  grading panel *reasoning*; this grades retrieval *inputs*. Run it
  *before* the rubric — if `canon_floor` is `false`, the rubric run is
  known-uninformative and can be skipped, ending the fix→rubric loop.
- **CI gating deferred.** Land as an on-demand script first; once stable,
  gate on `canon_floor == true` for ≥8/10 fixtures and
  `provider_kind_coverage >= 0.8` mean.

### Contract test

Add a fixture↔corpus contract check (extends the S33-#76 pattern in
`a05f90f`): every `provider_kind` named in any `retrieval_expectations`
block must exist in the live corpus with `count > 0`. Stops a fixture from
demanding a `provider_kind` that was never ingested.

---

## Appendix — probe method

Throwaway scripts (`.gecko/s33-81-probe/`, gitignored, not committed):
`embed()` with `input_type` variants; literal `$vectorSearch`/`$match`
pipelines run via `chunks_collection().aggregate`; `voyage_rerank_dicts`
called directly; `retrieve_trade_corpus_chunks` as the real entrypoint.
Env: `set -a; source .env; set +a` — `EMBED_PROVIDER=voyage`,
`EMBED_MODEL=voyage-3-large`, `GECKO_RERANKER=voyage`, `GECKO_CHUNK_STORE=mongo`.

Corpus state at probe time: 29,359 chunks total — `web` 22,414,
`canon_damodaran` 2,408, `canon_berkshire` 1,525, `protocol_native` 1,321,
`canon_marks` 610, `canon_mauboussin` 439, `canon_macro` 398,
`market_data` 81, `paysh_manifest` 72, `bazaar` 54, `bazaar_live` 26,
`bazaar_manifest` 10, `paysh_live` 1. All `canon_*` are `vertical='dex'`,
`protocol=[]`. All embeddings 1024-dim.
