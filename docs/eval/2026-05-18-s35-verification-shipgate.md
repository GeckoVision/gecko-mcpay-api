# S35 Verification Ship-Gate — envelope split (#99) + panel via OpenRouter (#101)

**Date:** 2026-05-18
**Branch:** `s35/panel-openrouter`
**Tag:** `s35-#103`
**Author:** quant-analyst
**Run type:** founder-authorized N=30 re-measure (3 pooled runs of the 10-fixture rubric suite)

## Question

Did the S35 verdict-envelope split (#99 — `evidence_citations[]` scored for
`citation_relevance`, `framework_context[]` scored only for
`provider_kind_coverage`) structurally lift `citation_relevance` past the 0.50
ship threshold? Did `provider_kind_coverage` hold once it is computed over
`framework_context` for canon kinds? The S34 baseline (#89, clean pooled N=30)
was `citation_relevance` 0.468, ship-gate 3/6.

## Run integrity

- **Retrieval pre-gate** (deterministic, no-LLM, production `top_k=15`):
  `canon_floor_rate=1.0` (target 0.80), `provider_kind_coverage=0.967`
  (target 0.80). **PASSED** — artifact
  `tests/eval/live_runs/2026-05-18-s33-retrieval-eval-run-10.json`.
- **Panel provider:** OpenRouter (`LLM_ROUTER=openrouter`, `openai/gpt-4o-mini`),
  resolved through the same `resolve_router()` path the production
  `/trade_research` endpoint uses (#101). Rubric judge on direct Anthropic
  (`claude-sonnet-4-6`, temperature 0).
- **Contamination:** all 3 runs `contaminated=false`, `n_dropped=0`. 30/30 rows
  scored. **No OpenRouter rate-limiting.** This is a clean N=30 — not a
  contaminated run masquerading as one.
- Eval-runner note: `_build_llm_config` was patched (this branch, `s35-#103`)
  to honor `LLM_ROUTER` so the ship-gate exercises the *shipped* provider path
  rather than the legacy hand-wired `api.openai.com` config. Without this the
  eval would not have verified #101.

## Statistical gate — pooled N=30

Bootstrap percentile 95% CI, 10,000 resamples, seed 4242. A dimension
**locks** only when its CI lower bound clears the threshold.

### Before (#89, S34 baseline) / After (#103, S35) — 6 dimensions

| Dimension | Thr | #89 mean | #89 CI | #89 lock | #103 mean | #103 CI | #103 lock |
|---|---|---|---|---|---|---|---|
| verdict_accuracy | 0.85 | 0.933 | [0.833, 1.000] | not | **1.000** | [1.000, 1.000] | **LOCKED** |
| citation_relevance | 0.50 | 0.468 | [0.422, 0.512] | not | **0.703** | [0.622, 0.779] | **LOCKED** |
| provider_kind_coverage | 0.70 | 1.000 | [1.000, 1.000] | LOCKED | 1.000 | [1.000, 1.000] | LOCKED |
| hallucination_score | 0.30 | 0.467 | [0.300, 0.633] | LOCKED | 0.367 | [0.200, 0.533] | **not** |
| dissent_grounding | 0.50 | 0.603 | [0.557, 0.653] | LOCKED | 0.637 | [0.577, 0.700] | LOCKED |
| confidence_calibration | 0.55 | 0.588 | [0.547, 0.628] | not | 0.630 | [0.588, 0.668] | **LOCKED** |

- **#89: 3/6 locked**, `ship_gate_pass=False`.
- **#103: 5/6 locked**, `ship_gate_pass=False`.

## The citation_relevance verdict — HEADLINE

**The envelope split worked.** `citation_relevance` moved 0.468 → **0.703**
(+0.235). The CI lower bound is **0.622** — not merely past the 0.50 threshold,
but past it by 0.12 with room to spare. This dimension is **LOCKED**.

The mechanism is exactly the #99 hypothesis: in #89, canon framework prose sat
in the single mixed `citations[]` list and dragged the relevance score down
because the judge (correctly) penalized non-protocol-specific cites. Post-split,
the judge scores only `evidence_citations` — and the envelope is genuinely
split in the data (pooled N=30 average: 5.87 evidence cites vs 6.00 framework
cites per row). Canon can no longer dilute the relevance-scored list.

`provider_kind_coverage` **held** at a perfect 1.000, CI [1.000, 1.000]. The
#99 decoupling — protocol kinds satisfied in `evidence_citations`, canon kinds
in `framework_context` — did not regress it. The split did not rob Peter to pay
Paul.

Two further dimensions also locked vs #89 (`verdict_accuracy`,
`confidence_calibration`), partly run-to-run variance and partly the
cleaner-provider draw.

## What still blocks 6/6

**`hallucination_score`** is the sole blocker. Mean 0.367 clears the 0.30
threshold on the point estimate, but the CI is [0.200, 0.533] — lower bound
0.200 < 0.30, so it does **not** lock.

This is a variance problem, not (only) a level problem. `hallucination_score`
is a per-fixture binary (0/1); the per-run means were 0.30 / 0.60 / 0.20 — a
0.40 swing across three N=10 draws. Pooled std ≈ 0.49, the maximum for a
binary, so even N=30 yields a ±0.17 half-width. The dimension is not
*structurally* failing — its mean is above the bar — but the panel still
emits an ungrounded specific figure on roughly 6 of every 10 fixtures, and the
sample cannot certify the 0.30 floor. This is unchanged in character from #89
(0.467, CI lower bound exactly 0.300 — it "locked" there only by landing the
boundary) and is **not** something the envelope split was designed to fix.

## Ship decision

- `ship_gate_pass`: **False**
- Dimensions locked: **5 / 6**
- Run clean: **yes** (N=30, 0 contamination, 0 dropped rows)

S35's envelope split is verified successful on its own terms — it lifted
`citation_relevance` past 0.50 with margin and did not regress
`provider_kind_coverage`. The ship gate does not pass because `hallucination_score`
remains uncertified. Closing 6/6 requires a hallucination-suppression change
(grounding-or-abstain on numeric claims), not more eval runs — and likely a
larger N to certify a binary dimension with this much variance.

## Artifacts

- `tests/eval/live_runs/2026-05-18-s33-retrieval-eval-run-10.json` — retrieval pre-gate
- `tests/eval/live_runs/2026-05-18-s24-defi-rubric-s35-103-shipgate-r1-10.json`
- `tests/eval/live_runs/2026-05-18-s24-defi-rubric-s35-103-shipgate-r2-10.json`
- `tests/eval/live_runs/2026-05-18-s24-defi-rubric-s35-103-shipgate-r3-10.json`
