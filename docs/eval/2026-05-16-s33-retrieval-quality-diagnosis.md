# S33 Retrieval-Quality Diagnosis — why `citation_relevance` is stuck at ~0.52

Date: 2026-05-16
Author: data-engineer (diagnostic lane)
Branch: `s33/paysh-renderer-fix`
Status: DIAGNOSIS ONLY — no code or chunks changed. Fixes route by lane below.

## Question

The trade-research oracle's `citation_relevance` rubric dimension plateaus at
~0.52 (best fixtures 0.35–0.55). Chunks reach the panel (15 retrieved, 15
cited) but the LLM judge rates them only ~half on-target. Founder hypothesis:
the query/retrieval semantics are weak. Confirmed — and the cause is not one
thing but a stack of four, all in the trade-panel retrieval path.

## Retrieval path under test

`run_trade_panel_with_retrieval` → `retrieve_trade_corpus_chunks`
(`packages/gecko-core/src/gecko_core/orchestration/trade_panel/__init__.py`
L440) → `embed([idea])` → Mongo `$vectorSearch` on `chunks_vector` →
post-`$match` on protocol → `$limit top_k=15` → panel.

This path is **completely separate** from `rag.query.rag_query`. Anything
wired into `rag_query` (provider boost, Voyage rerank) does NOT run here.

## Environment / index facts (probed live)

- `gecko_rag.chunks`: 31,560 docs; `dex` vertical: 9,063 docs.
- `chunks_vector` index: `numDimensions: 1024`, `similarity: cosine`,
  `path: embedding`. Filter paths include `vertical`, `protocol`,
  `metadata.deprecated`, `freshness_tier`. Correct shape.
- `.env`: `EMBED_PROVIDER=voyage`, `EMBED_MODEL=voyage-3-large` (1024-dim).
  `GECKO_RERANKER` is **unset**.
- Embedding dimensions in `dex` vertical: 100% are 1024-dim. The 1,408
  stray 1536-dim `web` chunks (legacy OpenAI `text-embedding-3-small`) are
  all outside `dex`, so they do NOT pollute trade retrieval. **Embedding
  model/dimension is consistent for the trade path — not the bug.**

## Ranked diagnosis

### 1. (HIGHEST ROI) No reranker on the trade-panel path — `GECKO_RERANKER` unset AND `retrieve_trade_corpus_chunks` never calls it

Evidence:
- `voyage_rerank` is invoked only from `rag.query.rag_query` (L444–465).
  `retrieve_trade_corpus_chunks` returns raw `$vectorSearch` cosine order
  with zero re-scoring — grep confirms it has no rerank import.
- `.env` has no `GECKO_RERANKER`, so even `rag_query` reranking is off in
  the eval environment; `voyage_rerank._flag_enabled()` returns False →
  pure passthrough.
- The kamino probe (below) shows top-15 cosine scores in a flat
  0.804–0.818 band — vector similarity cannot separate on-target from
  loosely-related chunks at this resolution. A cross-encoder reranker
  (`rerank-2`) is exactly the tool that re-scores a flat ANN slate by
  true query relevance.

Two independent gaps: the flag is off, AND the trade path wouldn't honor
it even if on.

Fix (lane: `ai-ml-engineer` owns rerank wiring + eval; `data-engineer`
supports): wire `voyage_rerank(idea, chunks, top_n=...)` into
`retrieve_trade_corpus_chunks` after the `$vectorSearch` (over-fetch
`limit` is already `top_k*5`, so the rerank input slate exists for free).
Set `GECKO_RERANKER=voyage` in the eval env. This is the single
highest-ROI change: it directly attacks "loosely-related chunks ranked
as if on-target."

### 2. Query is the bare `idea` string — no augmentation, no Voyage `input_type`

Evidence:
- `retrieve_trade_corpus_chunks` does `vectors, _ = await embed([idea])`
  (L491). The query embedded is the raw user question verbatim. No HyDE,
  no query expansion, no protocol/vertical context injected.
- `embedder._embed_voyage` accepts `input_type` but `embed()` never passes
  it (grep: `input_type` appears only as an unused param). Both ingest
  chunks and the query are embedded with `input_type=None` —
  **symmetric**. `voyage-3-large` supports `input_type="query"` /
  `"document"`, which prepend asymmetric instruction prefixes tuned for
  retrieval. Running symmetric forfeits a documented relevance gain.
- Semantic-gap symptom: a terse question ("Should I deposit USDC into a
  Kamino vault?") vs verbose data chunks ("Drift SOL-PERP funding record
  — funding rate -0.000359583, long rate ...") sit far apart in cosine
  space. The kamino probe's flat 0.80 band is the fingerprint of this gap.

Fix (lane: `ai-ml-engineer`): (a) thread `input_type` through `embed()`
and call ingest with `"document"`, retrieval with `"query"`; (b) consider
a light query augmentation — prepend protocol + vertical + a one-line
HyDE-style hypothetical answer before embedding. (a) is low-risk and
should ship first; it requires a `data-engineer` coordination note
because existing chunks were embedded `input_type=None` — a mixed corpus
is acceptable for cosine but a full re-embed at `"document"` is the clean
end state (see §4).

### 3. Corpus duplication floods the top-k with identical chunks (lost-in-the-middle)

Evidence (live probes, `top_k=15`):
- **kamino** "deposit USDC" query: positions [6]–[14] are NINE byte-identical
  copies of one 111-char chunk: `"Protocol-native API:
  kamino/kamino-vaults ... NOTE: API returned 144 entries; showing first
  40 ..."` — a chunk with **zero substantive content** (it's the sampling
  notice, not vault data). 9 of 15 slots burned on one empty string.
- **drift** query: 13 of 15 chunks are near-identical per-record funding
  lines differing only in the rate digits.
- Corpus-wide (`dex` vertical): 1,807 redundant exact-text copies out of
  9,063 docs = **19.9% of the dex corpus is duplicate text**. Worst
  offenders: 78× identical `kamino-vaults` empty chunk, 48× identical
  `paysh_live` `"data: []"` empty chunk.
- The judge sees 15 citations; when 9 are the same empty string, the
  measured `citation_relevance` is mathematically capped low regardless
  of how good the other 6 are.

Root cause is in ingestion: `ingest_protocol_native.py` is idempotent per
`(source_id, chunk_index)` where `source_id = uuid5(url + day_bucket)`. A
re-run on a *new* day creates a new `source_id`, so every daily re-ingest
appends a fresh full copy instead of replacing — the corpus accretes one
duplicate set per ingest day. The empty `kamino-vaults` chunk also should
never have been embedded: `_render_entity_list` emitted a bare header +
`"Kamino kamino-vaults."` because the payload entities lacked the expected
name keys.

Fix (lane: `data-engineer`):
- De-dup the `dex` corpus: drop exact-text duplicates, keep newest
  `as_of_date`. ~1,800 docs.
- Make daily re-ingest replace, not append: delete prior
  `provider_kind=protocol_native` chunks for a `(protocol, slug)` before
  inserting the new day's set, OR drop `day_bucket` from `source_id` and
  let the `(source_id, chunk_index)` unique index upsert in place.
- Filter empty/degenerate chunks at ingest: reject any rendered chunk
  whose body (text minus provenance header) is < N chars or contains no
  digit/entity. The `_fetch` empty-guard catches `{"data":[]}` but not a
  *rendered* near-empty chunk.

### 4. Provenance header dominates short chunks' embedding vector

Evidence:
- Every `protocol_native` chunk leads with
  `"Protocol-native API: <protocol>/<slug> (as of <date>)."` (~65 chars).
- Probed `drift-market-prices` chunks total 230 chars: 65 header + 165
  body → **28% of the embedded vector is boilerplate** shared across
  hundreds of chunks. For the empty `kamino-vaults` chunk (111 chars) the
  header is ~60% of the signal.
- The header is identical across many chunks, so it pulls their vectors
  toward a common centroid and *compresses* the cosine spread — directly
  producing the flat 0.80 band that defeats ranking (feeds §1 and §2).
- `embedder.embed()` embeds exactly the stored `text`. There is no
  separate "embedding text" vs "cited text" — the header is in both. A
  header useful for the *judge* (it wants provenance) is noise for the
  *embedder*.

Fix (lane: `data-engineer`, with `ai-ml-engineer` on the split decision):
decouple embedded text from stored/cited text. Embed the body only
(header stripped); keep the full header+body as the stored `text` the
panel cites. Requires an `embed_text` field + a re-embed of
`protocol_native` chunks. Pair this re-embed with the `input_type`
="document" change from §2 so the corpus is re-embedded exactly once.

## Probe appendix (kamino, abbreviated)

```
Q: Should I deposit USDC into a Kamino lending vault right now?  protocol=kamino
 [ 0] 0.8175 protocol_native  Kamino Maple Market — syrupUSDC leverage pool ...
 [ 2] 0.8146 protocol_native  Kamino Ethena Market — USDe/stables pool ...
 [ 6] 0.8044 protocol_native  kamino/kamino-vaults ... NOTE: API returned 144 ... (EMPTY)
 [ 7..14] 0.8044  <eight more byte-identical copies of [6]>
```

Score band 0.804–0.818 across all 15. 9/15 are the same empty chunk.
No on-target lending-APY/utilization chunk surfaces at all.

## Recommended sequencing

1. `ai-ml-engineer`: wire `voyage_rerank` into `retrieve_trade_corpus_chunks`;
   set `GECKO_RERANKER=voyage`. (§1 — biggest single move, no re-ingest.)
2. `data-engineer`: de-dup `dex` corpus + fix daily-re-ingest append bug +
   empty-chunk ingest filter. (§3 — removes the mechanical cap.)
3. `data-engineer` + `ai-ml-engineer`: one combined re-embed of
   `protocol_native` — body-only embedding text (§4) + `input_type`
   asymmetry (§2).
4. `ai-ml-engineer`: re-measure; only then consider query augmentation/HyDE.

Items 1–2 require no re-embed and should land first; re-measure
`citation_relevance` between each.
