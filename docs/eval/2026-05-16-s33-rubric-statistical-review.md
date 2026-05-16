# S33 trade-rubric — statistical review

**Date:** 2026-05-16
**Scope:** vetting the `s33-fixture-fix` N=10 run before anyone calls S33 "done."
**Method:** bootstrap (10k resamples) on the per-fixture rows; paired test on the citRel jump.

## 1. Bootstrap 95% CIs — s33-fixture-fix, N=10

| Dimension | mean | 95% CI | threshold | P(true mean passes) | read |
|---|---|---|---|---|---|
| verdict_accuracy | 0.90 | [0.70, 1.00] | 0.85 | 74% | **not locked** — CI straddles |
| citation_relevance | 0.52 | [0.43, 0.61] | 0.50 | 67% | **not locked** — coin-flip |
| provider_kind_coverage | 1.00 | [1.00, 1.00] | 0.70 | 100% | **locked** |
| hallucination_score | 0.10 | [0.00, 0.30] | 0.30 | 7% | **solidly failing** |
| dissent_grounding | 0.61 | [0.50, 0.73] | 0.50 | 100% | **locked** |
| confidence_calibration | 0.54 | [0.46, 0.61] | 0.55 | 42% | **not locked** — coin-flip |

**"4/6 GREEN" is half-illusory.** Only **2** dimensions are statistically locked (provider_kind_coverage, dissent_grounding). Two of the four "passing" dims — verdict_accuracy and citation_relevance — are coin-flips: a re-run could land either side of the threshold.

## 2. The borderline calls

- **citation_relevance 0.52 vs 0.50** — P(true mean ≥ 0.50) = **67%**. Leans pass, but a third of the time a re-run fails it.
- **confidence_calibration 0.54 vs 0.55** — P(true mean ≥ 0.55) = **42%**. Leans fail, but it's a coin-flip — not a stable red.

Both margins are ≈0.02 against a per-fixture spread of ~0.16. N=10 cannot resolve them.

## 3. verdict_accuracy is not a stable estimate

Across the three S33 runs: **0.60 → 0.90 → 0.90** — a 0.30 range. The current 0.90 is not a fixed property of the system; it's a draw from a wide distribution. P(true mean ≥ 0.85) is only 74%. Treat verdict_accuracy as *un-pinned*.

## 4. The citRel improvement IS real — that part is not in doubt

Paired comparison, same 10 fixtures, `s33-curated` → `s33-fixture-fix`: mean delta **+0.31, all 10 fixtures improved, P(delta > 0) = 1.0000**. The #76 fix unambiguously worked. The corpus-quality arc (Phase 1 renderers + #75 curation) is real progress — that conclusion is solid. The doubt is *only* about whether 0.52 clears a 0.50 bar, not about whether things got better.

## 5. Sample size — N=10 cannot certify this gate

For the citation_relevance CI half-width to be smaller than its 0.02 margin over threshold: **N ≈ 236**. N=10 is ~20× too small to *certify* a pass at that margin. A practical confirmation run of N=30–50 would tighten the CIs meaningfully but still won't fully lock a 0.02 margin.

**The deeper issue:** the rubric thresholds and the eval's N are mismatched. A 0.50 threshold judged by an LLM with ~0.16 per-fixture spread at N=10 has a noise band wider than several of the margins. Either the thresholds need a deliberate margin (e.g. require 0.55 to "pass" a 0.50 gate), or N must rise, or both. This should be decided before S33 is declared shipped.

## The one sentence

**S33 is not "nearly done": the #76 fix is real and the corpus is genuinely better, but only 2 of 6 dimensions are statistically locked, hallucination is solidly red, and N=10 cannot certify a ship-gate whose margins are thinner than the eval's own noise.**
