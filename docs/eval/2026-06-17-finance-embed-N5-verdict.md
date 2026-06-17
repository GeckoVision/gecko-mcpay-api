# Finance-embed A/B — N=5 verdict: DO NOT re-embed

**Decision (2026-06-17): keep `voyage-3-large`. The voyage-finance-2 signal collapsed at N=5 — it was best-of-noise at N=3.**

## Context
The N=3 sampled A/B (`docs/eval/2026-06-15-finance-embed-ab.md`) leaned RE-EMBED at +0.07–0.09 recall@10 / nDCG@10 and explicitly recommended an N≥5 confirmation before committing prod retrieval. Per our rigor discipline (we are the "is this number real" company), we do not flip the production embedding model on N=3. This is that confirmation.

## Result (N=5, sample=120/run, judge = voyage/rerank-2 cross-encoder, spend $0.44)
**Every metric `win_signal: false`.**

| Metric | @3 | @5 | @10 |
|---|---|---|---|
| recall | +0.016 | +0.016 | +0.036 |
| nDCG | +0.043 | +0.031 | +0.041 |
| pk_coverage | +0.030 | **−0.007** | **−0.050** |

- Per-run **spread is 0.10–0.17** — larger than every mean delta. Variance swamps signal.
- nDCG@10 per-run: `[0.034, 0.008, 0.076, 0.093, −0.007]` — the two big positives that drove the N=3 lean are not reproducible; run 5 is negative.
- **`pk_coverage` (private-knowledge / wedge-relevant axis) trends NEGATIVE** at k=5 and k=10. Re-embedding would, if anything, slightly *hurt* the metric we care most about.

## Why this is the right call
The N=3 "+0.07–0.09" was the best draw of a noisy distribution. At N=5 with honest variance, no metric clears its win threshold, and the wedge-relevant axis goes negative. Re-embedding would mean: spend the (founder-gated) cutover + a parallel-index build + ongoing model-divergence risk, for **no measurable retrieval gain** and a possible pk_coverage regression. Classic backtest-overfitting trap — caught by re-running with more samples.

## Action
- **No re-embed. No EMBED_MODEL flip. No cutover.** Prod stays on `voyage-3-large`.
- The Path-A parallel-index plan is shelved (not needed).
- If revisited later: would need a *materially* larger, lower-variance eval (more queries + ground-truth, not just sample=120) showing a stable, reproducible win on pk_coverage specifically — not a marginal recall/nDCG bump.

Raw report: `tests/eval/live_runs/2026-06-17-finance-embed-ab.json`.
