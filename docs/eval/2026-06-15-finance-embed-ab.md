# Finance-tuned embedding A/B — `voyage-finance-2` vs `voyage-3-large`

**Date:** 2026-06-15 (run 2026-06-16 UTC) · **Phase:** 2.3 (founder-approved) · **Owner:** ai-ml-engineer
**Branch:** `feat/ce-finance-embed-ab` · **Script:** `scripts/eval/finance_embed_ab.py`
**Raw output:** `tests/eval/live_runs/2026-06-16-finance-embed-ab.json`

## TL;DR — VERDICT: lean RE-EMBED, but confirm at N≥5 first (INCONCLUSIVE→RE-EMBED)

At the larger sampled run (**3 runs × 200 chunks**, model-independent cross-encoder
ground truth), `voyage-finance-2` shows a **consistent, same-direction lift over the
current default on ranking quality**:

- **recall@10: finance-2 wins all 3 runs** (0.44 > 0.38, 0.52 > 0.46, 0.48 > 0.34;
  mean Δ **+0.087**, spread 0.08 — just clears the noise band).
- **nDCG@10: finance-2 wins all 3 runs** (0.443 > 0.405, 0.462 > 0.375, 0.473 > 0.381;
  mean Δ **+0.072**, spread 0.055 — clears the band).
- recall@3 / recall@5 also positive every run (mean +0.04 / +0.047).
- **provider_kind coverage does NOT improve** (mean roughly flat to slightly negative,
  large spread) — finance-2 keeps about the same canon/protocol mix, not a wider one.

The full re-embed costs only **~$0.99**. Given a consistent positive direction on the
metrics that matter (recall/nDCG) and trivial cost, the lean is **RE-EMBED**. But the
magnitude is small (+0.07-0.09 nDCG/recall@10) and the per-run swing is still wide
(recall@10 ranged 0.06-0.14 lift), so this is **not yet a robust win at N=3**. One
cheaper confirmation run at **N≥5** that holds the same all-runs-positive pattern would
turn the lean into a clean RE-EMBED. Flipping the live default remains a separate,
founder-gated step and is **not** done here.

### Why this verdict moved (the small-N lesson, on the record)

An earlier 2-run × 120-sample pass was genuinely **INCONCLUSIVE leaning DON'T** — the two
runs disagreed in sign on most cells and nothing cleared the spread. Worse, two separate
*executions* of that same 2×120 config produced materially different deltas (one mean-
negative, one mean-positive). That instability is exactly the small-N variance the house
rule guards against. Going to 3 runs × 200 sample shrank the band enough for a consistent
direction to emerge. The lesson is load-bearing: **do not decide an embedding swap on a
single small run — this one would have flipped the wrong way half the time.**

## What was measured (and what was NOT)

- **NOT re-embedded:** the production corpus (24,208 chunks) is untouched. The embedder
  default (`EMBED_MODEL`, currently `voyage-3-large` in env) is untouched.
- **Sampled, self-contained A/B.** The live Atlas index is in the baseline model's vector
  space, so it cannot serve the finance-2 arm. Per run we draw a fresh random sample of
  trade-relevant chunks (text only), embed that sample + the 10 `defi_trade_suite`
  questions with **both** models, rank by cosine, and score each arm against a
  **model-independent ground truth**: the Voyage `rerank-2` cross-encoder labels the
  top-5 chunks per query as "relevant". Metrics: recall@k, nDCG@k (graded), provider_kind
  coverage@k. k ∈ {3, 5, 10}.
- **Rigor:** sample re-drawn each run (seeds 1000+run), per-run deltas + spread reported.
  A "win" is only flagged when `mean_delta > spread` (signal > noise).

> Baseline-name note: the task framed the default as `voyage-context-3`, but the live
> `.env` sets `EMBED_MODEL=voyage-3-large` (1024-dim, same Atlas index). The A/B ran
> against the **actual** configured baseline (`voyage-3-large`). The embedder docstring's
> `voyage-context-3` default is overridden by env at runtime — worth a follow-up
> reconciliation, but it does not change this verdict.

## Sampled lift — primary run (3 runs × 200 sample, $0.44)

finance-2 minus baseline; "win?" = mean Δ > spread.

| metric | k | run0 | run1 | run2 | mean Δ | spread | win? |
|---|---|---|---|---|---|---|---|
| recall | 3  | — | — | — | **+0.040** | 0.040 | yes (boundary) |
| recall | 5  | 0.02 | 0.06 | 0.06 | **+0.047** | 0.040 | yes |
| recall | 10 | 0.06 | 0.06 | 0.14 | **+0.087** | 0.080 | yes (boundary) |
| nDCG   | 3  | — | — | — | **+0.063** | 0.036 | yes |
| nDCG   | 5  | — | — | — | +0.051 | 0.057 | no (boundary) |
| nDCG   | 10 | 0.037| 0.087| 0.092| **+0.072** | 0.055 | yes |
| pk_cov | 3  | — | — | — | −0.008 | 0.025 | no |
| pk_cov | 5  | — | — | — | 0.000 | 0.100 | no |
| pk_cov | 10 | — | — | — | −0.025 | 0.175 | no (finance-2 slightly *narrower*) |

### Absolute @10 (context for the deltas)

| run | baseline R@10 / nDCG@10 / pkcov@10 | finance-2 R@10 / nDCG@10 / pkcov@10 |
|---|---|---|
| 0 | 0.38 / 0.405 / 0.90 | 0.44 / 0.443 / 0.95 |
| 1 | 0.46 / 0.375 / 0.73 | 0.52 / 0.462 / 0.61 |
| 2 | 0.34 / 0.381 / 0.68 | 0.48 / 0.473 / 0.68 |

finance-2's recall@10 and nDCG@10 are higher in **every** run. The remaining variance is
sample-draw variance (baseline recall@10 itself swings 0.34-0.46), which is why N≥5 would
firm up the magnitude.

## Earlier run (2 runs × 120 sample) — kept for the variance record

Two separate executions of the 2×120 config:
- exec A: recall Δ mean ≈ −0.01 (runs disagreed in sign), nothing cleared spread → DON'T.
- exec B: recall Δ mean ≈ +0.06-0.11, nDCG@3/@10 flagged wins → lean RE-EMBED.

Same config, opposite leans. This is the headline caution: **N=2 × 120 is too small to
decide.** Both are in git history of the raw artifact; the 3×200 run supersedes them.

## Full-corpus re-embed cost estimate

Source: live Atlas `gecko_rag.chunks` counts × char-sum ÷ 4 chars/token × $0.12/1M
(`voyage-finance-2` list price, mirrors `embedder._EMBED_RATES_USD_PER_1M`).

| scope | chunks | est. tokens | **est. cost** |
|---|---|---|---|
| full corpus (shared Atlas index — required) | 24,208 | ~8.23M | **~$0.99** |
| trade-relevant subset only (informational) | 7,088 | ~4.08M | ~$0.49 |

Time: ~8.2M tokens at Voyage batch throughput is a single-digit-minutes job. **Cost is
not the blocker.**

> Caveat: the Atlas vector index is shared across all verticals, so a model swap requires
> re-embedding the *full* 24k corpus (you cannot mix two embedding spaces under one ANN
> index), even though only the 7k trade-relevant subset is what we're optimizing. Budget
> the full $0.99. The general-research `web` chunks (17k of the 24k) get re-embedded too;
> finance-2's effect on those was not measured here — only on the trade-relevant slate.

## Spend for this measurement

Primary run: `embed_tokens=751,096`, `rerank_pairs=6,000`, **$0.44** (ceiling $6.00).
Earlier 2×120 runs: ~$0.17 each. Total Voyage spend for Phase 2.3: <$1.

## Verdict & next step

**Lean RE-EMBED; confirm at N≥5 before flipping (INCONCLUSIVE→RE-EMBED).**

- Consistent same-direction lift on recall@10 (+0.087) and nDCG@10 (+0.072) — every run,
  for a finance-tuned model on a finance corpus, is the expected and plausible result.
- pk_coverage does not improve (slightly worse, noisy) — finance-2 sharpens ranking, not
  corpus-kind breadth; the canon-floor quota in the trade-panel already guards coverage
  structurally, so this is acceptable.
- Re-embed is ~$0.99 and minutes — cheap enough that a small-but-consistent win justifies
  it, *provided the direction holds at a larger N.*

**Cheapest decisive next step** (the only thing gating a clean RE-EMBED call):

```bash
uv run python -m scripts.eval.finance_embed_ab --runs 5 --sample 200 --budget-usd 6.0
```

If recall@10 and nDCG@10 stay positive in ≥4 of 5 runs with mean Δ > spread → **RE-EMBED**
(re-embed full corpus to finance-2, then run a live `defi_trade_suite` rubric pass to
confirm the retrieval lift survives into verdict quality before flipping the default).
If the direction breaks → hold on `voyage-3-large`. Flipping the live default is a
separate, founder-gated step.

## Reproduce

```bash
# cost estimate only ($0):
uv run python -m scripts.eval.finance_embed_ab --cost-only

# primary sampled A/B (~$0.44, 3 runs):
uv run python -m scripts.eval.finance_embed_ab --runs 3 --sample 200 --budget-usd 6.0

# decisive confirmation (~$0.7), gates the clean RE-EMBED call:
uv run python -m scripts.eval.finance_embed_ab --runs 5 --sample 200 --budget-usd 6.0
```

Requires `VOYAGE_API_KEY` + `MONGODB_URI` in `.env` and the `voyageai` extra installed.
Without the key the script emits the cost estimate only and a "needs key" note.
Note: rerank-2 has a 2M-tokens/min TPM cap and embed batches cap at 120k tokens; the
script sub-batches embeds (64/call) and retries reranks on RateLimit, so large samples
degrade to "slower", not "crash".
