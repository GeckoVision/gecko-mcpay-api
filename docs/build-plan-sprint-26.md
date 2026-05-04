# Sprint 26 — Dogfood Bug Fixes

Bugs surfaced by running gecko MCP tools on Gecko itself (2026-05-04 session).

---

## S26-VERDICT-FIDELITY-01 — Low-grounding floor must not override PIVOT

**Root cause:** In `models.py::derive_verdict()`, the `is_low_grounding → REFINE` guard fires before
`gap in ("Full", "False") → PIVOT`. A session with a well-classified Full/False gap and fewer-than-threshold
citations returns REFINE instead of PIVOT — the verdict is softened when evidence is sparse, hiding a clear
invalidation signal.

**Fix:** Move the PIVOT check before the low-grounding floor. PIVOT means "the gap doesn't exist" — no amount
of weak grounding changes that signal. The floor should only apply to ambiguous gaps.

**Files:** `packages/gecko-core/src/gecko_core/models.py`

---

## S26-CITE-03 — twitsh:// synthetic URI leaks into citation source_url

**Root cause:** `to_chunks()` stores the per-tweet URL in `ProviderChunk.metadata["tweet_url"]` but
`RagChunk` has no `metadata` field. MongoDB projections don't return `metadata`. Citation assembly in
`workflows.py` uses `c.source_url` directly, so users see `twitsh://session/<id>` as the citation URL
instead of the actual tweet URL.

**Fix (3 parts):**
1. Add `metadata: dict[str, Any]` to `RagChunk`.
2. Include `metadata: 1` in all three MongoDB `$project` stages in `mongo_reads.py`; propagate through `_row_from_doc`.
3. In citation assembly (`ask()` and `research()`), resolve `twitsh://` URIs via `metadata["tweet_url"]`.

**Files:**
- `packages/gecko-core/src/gecko_core/rag/query.py`
- `packages/gecko-core/src/gecko_core/db/mongo_reads.py`
- `packages/gecko-core/src/gecko_core/workflows.py`

---

## S26-SOURCE-DIVERSITY-01 — Pro sessions never index twitsh chunks into Mongo

**Root cause:** `_dispatch_stub_integration_providers` (which indexes twitsh/Bazaar/arXiv chunks into Mongo)
is only called in the basic `research()` flow. The pro flow (`_run_pro_debate`) calls `_dispatch_v1_sources`
which builds a V1 text block for agents but does NOT write any chunks to Mongo. So when the debate agents
do `rag_query`, twitsh chunks are absent and `provider_mix_flag = "single_provider_dominates"` fires.

**Fix:** Call `_dispatch_stub_integration_providers` before the pro debate runs. The basic pre-run inside
`_run_pro_debate` already populates the Tavily chunks; the twitsh dispatch is cheap and idempotent.

**Files:** `packages/gecko-core/src/gecko_core/workflows.py`

---

## Tests

- `tests/test_derive_verdict_priority.py` — PIVOT wins even when `is_low_grounding=True`
- `tests/test_rag_chunk_metadata.py` — `RagChunk.metadata` round-trips; twitsh URI resolved in citations
- `tests/test_pro_source_diversity.py` — pro flow triggers twitsh dispatch
