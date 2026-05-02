# Voyage Rerank Chunk-Level A/B — S19 R3 Result

**Date:** 2026-05-02
**Owner:** ai-ml-engineer
**Harness:** `scripts/voyage_chunk_ab.py`
**Output:** `tests/eval/live_runs/2026-05-02-s19-r3-chunk-ab.json`
**Decision input for:** S19 plan §2a R3 — should `GECKO_RERANKER` default flip from `none` to `voyage`?

## Gate result

**NOT TRIPPED.** Both legs fail.

| Leg | Spec | Observed | Pass? |
|---|---|---|---|
| Citation precision lift | delta_mean_pp >= +10 | **-9.38 pp** | no |
| Latency p50 regression | delta_p50_ms <= +300 | **+526 ms** | no |

Recommendation: **keep `GECKO_RERANKER` default OFF.** Do not flip in code, do not flip in env, do not promote in S19 demo runbook. This is a clear "don't ship" signal for the default; `voyage` remains opt-in.

## Spend

| Vendor | Calls | Tokens | $ |
|---|---|---|---|
| Voyage rerank-2 | 8 | n/a | ~$0.0004 |
| OpenAI text-embedding-3-small (query encode) | 16 | ~400 | ~$0.000008 |
| **Total est.** | | | **~$0.0004** |

Well under the $5 cap. No abort triggered.

## Methodology

### Scope reduction

The S19 plan §2a R3 gate is written against verdict-accuracy + latency. The chunk-level harness measures **retrieval precision + latency only**. Verdict-accuracy is a downstream synthesis property of the 5-agent debate; voyage_rerank only controls retrieval. Measuring it at the chunk layer would be category-confused — and the reachability finding (`feedback_eval_harness_rag_gap`) is what got us here in the first place: we don't have a working eval-layer rag_query path to graft "verdict" onto, and synthesizing one would re-trip the same Pattern A trap.

### Ground truth: proxy, NOT real

The holdout-live suite (`tests/eval/suites/general_holdout_live.json`) does not populate `must_cite_sources` for any of its 10 ideas. We use a **top-3 proxy**: for each query, arm A's top-3 cosine results are treated as the "ideal" surrogate set, and citation_precision is computed against that.

This proxy is **strict against arm B** by construction — arm A defines the ground truth, so any reorder that B introduces necessarily lowers B's overlap. A perfect-score B would have to leave A's top-3 inside its own top-8 *and* reorder the rest. The observed -9.38 pp is therefore an upper bound on how much worse B is; the true semantic-quality delta is unknown.

What this proxy **does** validate: voyage_rerank actually ran (rerank_score populated on all 8 queries, 8/8) and meaningfully reordered the slate (4/8 queries had at least one of A's top-3 evicted from B's top-8). The reranker is wired and reachable. That alone closes the open question from the prior reachability audit at this layer.

### Corpus

Reused the existing rich Mongo session `6cc0a982-8e21-4517-9d9f-565a867ef58d` (59 chunks, web/bazaar/twitsh) populated by an earlier `bb research` run on agentic-payments / x402 content. Querying the holdout-live ideas (FAA AME intake, Twilio webhook replay, etc.) against this corpus would yield zero retrieval signal for either arm — the corpus is off-topic for those ideas. So we crafted 8 on-topic queries about x402 / MCP / agentic payments that the corpus has dense coverage of.

This is the right tradeoff for a chunk-level A/B: a thin corpus with no signal would tell us nothing about the reranker's behavior; a topic-matched corpus tells us what voyage_rerank does to a realistic slate. The cost is that we cannot generalize this single-session result to "voyage helps on saas/devtools/regulated ideas" — the corpus is one-topic.

### Arms

- **Arm A:** `GECKO_RERANKER=none` → cosine + provider-boost + per-kind quota. Voyage no-op.
- **Arm B:** `GECKO_RERANKER=voyage` → same plus Voyage rerank-2 trim from K=20 to N=8.

The flag is read fresh on every call (`voyage_rerank._flag_enabled` is not lru-cached); env flip per query is safe.

## Per-query results

8/8 queries: arm B's `rerank_score` populated → Voyage actually ran end-to-end.
4/8 queries: B's citation_precision dropped (Voyage reordered enough that A's top-3 no longer all fit in B's top-8).
4/8 queries: tied at 0.375.
0/8 queries: B improved over A on the proxy (consistent with proxy bias).

Latency: B is consistently 200–700 ms slower than A (rerank-2 round-trip) — well within the 2.5s graceful-degrade timeout, but past the 300 ms p50 budget the gate sets.

## Caveats stacked

1. **Top-3 proxy, not real ground truth.** The numbers are a bias floor, not a clean measurement.
2. **Single corpus, single topic.** N=8 queries on one session_id. We cannot infer whether voyage helps on the full provider mix or on different idea phyla (regulated / crypto / saas).
3. **No verdict-quality signal.** voyage_rerank's claimed value-add is "the LLM cites better stuff" — that's measurable end-to-end, not at the chunk layer. A real R3 needs a live `bb research` A/B against the holdout-live suite, which is what `feedback_eval_harness_rag_gap` flagged as the missing harness.

## What would change the answer

Two things would put voyage back on the table:

1. **A real ground-truth fixture.** Hand-label `must_cite_sources` (or `must_cite_chunk_keys`) on 5–10 ideas tied to a fresh corpus. With real labels, a strict +10pp gate is meaningful; today it isn't.
2. **An end-to-end live A/B.** Run `bb research` on the holdout-live suite twice with the flag flipped, score the resulting verdicts and citations against the rubric. Cost is the blocker — that's ~$1.50/run × 2 arms × 1 rerun = ~$3, plus a working rerun harness. The reachability gap encoded in `feedback_eval_harness_rag_gap` is the prerequisite.

Until either of those exists, **keep the default off and call this question parked, not answered.**

## Files staged

- `scripts/voyage_chunk_ab.py` — harness (new)
- `tests/eval/live_runs/2026-05-02-s19-r3-chunk-ab.json` — raw run output (new)
- `docs/audits/2026-05-02-voyage-rerank-ab-result.md` — this memo (new)

No production code changed. No defaults flipped. No env changes committed.

## S20 flag

The Voyage rerank evaluation question is **blocked on a real RAG eval harness**, not on more A/B runs. S20 should prioritize building a labelled fixture suite (10–20 ideas with hand-graded `must_cite_chunk_keys`) so retrieval-quality questions can be answered with single-digit-dollar runs instead of orchestration-round-trip live evals. Without that fixture, every "should we flip the reranker?" question burns cycles re-deriving the same proxy methodology with the same caveat stack.
