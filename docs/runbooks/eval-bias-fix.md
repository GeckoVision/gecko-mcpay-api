# Eval bias fix — runbook

## What was wrong

The Pro-tier eval gate reads `verdict_accuracy >= 0.85` per sub-suite as
the trigger for the mainnet cutover (ADR-0001). In late April 2026,
staff-engineer reviewed the suite fixtures and found two structural
leaks that made `verdict_accuracy` measure fixture quality, not Judge
quality.

### Leak #1 — `mock_precedents` are the answer key

Every idea in `tests/eval/suites/general_suite.json` had at least one
`mock_precedents[].verdict` at similarity 0.81–0.94 matching the
idea's `expected_verdict`. Spot checks across crypto/saas suites
showed the same pattern.

Sample evidence (pre-fix `general_suite.json`, six ideas spot-checked
by staff-engineer):

| idea id                       | precedent similarities | precedent verdicts | expected |
|-------------------------------|-----------------------:|--------------------|----------|
| bad-tax-ai-no-lawyer          | 0.91, 0.84             | kill, kill         | kill     |
| bad-gpt-wrapper-marketing     | 0.93, 0.86             | kill, kill         | kill     |
| bad-gpt-therapy               | 0.94, 0.87             | kill, kill         | kill     |
| good-mcp-postgres-explainer   | 0.91, 0.84             | ship, ship         | ship     |
| good-cap-table-diff           | 0.91, 0.84             | ship, ship         | ship     |
| good-vet-tele-rx              | 0.90, 0.85             | ship, ship         | ship     |

A trivial baseline ("majority vote of `mock_precedents`") would score
1.0 on the pre-fix suites without invoking the debate at all. The
v5.4 prompt's `verdict_accuracy=1.0` reading on the general suite was
indistinguishable from that baseline.

### Leak #2 — `rag_context` literally stated the verdict

Across all three suites, the 4th `rag_context` bullet for almost every
idea was a string of the form:

```
- gecko_precedent: '<idea summary>' KILLED 2026-MM-DD ...
- gecko_precedent: '<idea summary>' SHIPPED 2026-MM-DD ...
```

The verdict label appears verbatim in the context the Judge reads.
Even with precedents removed, this alone would let any moderately
capable LLM hit ~1.0.

## What was changed

### `tests/eval/suites/{general,crypto,saas}_suite.json`

For every idea:

- **rag_context** — any bullet matching `gecko_precedent:\s*[^.\n]*?\b(KILLED|SHIPPED|SHIP|KILL|PIVOT|PIVOTED)\b` was replaced with a neutral evidence bullet citing real domain comparables (e.g. `"Comparable: <named product> reached <revenue/fact>"` or `"Industry signal: <named report> noted ..."`). Total bullet count remained 4 per idea so token count stays comparable across ideas.
- **mock_precedents** — capped at similarity ≤ 0.75 (was 0.80–0.94). At least 30% of ideas across each suite have one `mock_precedents[]` entry whose `verdict` differs from `expected_verdict`. For ideas where the original pair was tightly aligned (e.g. 0.91 + 0.84 same-verdict for a clear kill), one of the two precedents is now a closer-but-opposite-verdict precedent so the Judge has to override it via Critic-found differentiation.

The 50 `expected_verdict` ground-truth labels were not touched.

### `tests/eval/suites/general_holdout_suite.json` (new)

Ten archetypal twins of the `general_suite` ideas using disjoint
proper nouns and verticals. 5 ship + 5 kill. Same fixture rules as
above (similarity caps, no `gecko_precedent: ... <VERDICT>` strings,
verdict-diversity ≥ 30%).

The holdout is **not** part of the `--suite all` aggregate. It runs
opt-in via `--suite holdout` and is meant to verify that v5.4 (or any
future prompts version) generalizes to surface forms it wasn't tuned
against.

### `tests/eval/runner.py`

- `SUITE_NAMES` extended to include `"holdout"`.
- New `_GATE_SUITES = ("general", "crypto", "saas")`. `--suite all`
  iterates this list, not `SUITE_NAMES`. Holdout never contributes to
  the gate aggregate.
- `_suite_path("holdout")` resolves to `general_holdout_suite.json`.

### `tests/eval/test_suite_no_leakage.py` (new)

Four parametrized assertions across all four suite files:

1. No `rag_context` bullet contains `gecko_precedent: ... <VERDICT>`.
2. No `mock_precedents[].similarity > 0.75`.
3. ≥ 30% of ideas have at least one `mock_precedents[].verdict !=
   expected_verdict`.
4. The holdout suite shares no proper nouns from a curated list of
   distinctive names in the gate suites (Carta, Stripe, NIH, Postgres,
   Vet-tele-Rx, etc.).

These tests run under `uv run pytest` and gate every PR. If the
fixtures regress, the tests fail before the eval ever runs.

## How to run the ablation

```bash
./scripts/run_eval_ablation.sh
```

Three sequential live runs against the general suite:

| Run | Prompts | Judge model  | Fixtures               | Purpose                       |
|-----|---------|--------------|------------------------|-------------------------------|
| A   | v5.4    | gpt-4o-mini  | leaky (pre-fix, git)   | Reproduce the original 1.0    |
| B   | v5.4    | gpt-4o       | stripped (post-fix)    | Real gate number              |
| C   | v5.3    | gpt-4o       | stripped (post-fix)    | Isolate prompt-diff lift      |

### How to read the output

The script prints two deltas:

- **Leakage lift = A − B.** If A ≈ 1.0 and B is materially lower,
  the pre-fix gate was measuring fixture leakage rather than Judge
  quality. This is the headline finding the runbook exists to confirm.
- **Prompt-diff lift = B − C.** If B − C > 0, the v5.4 prompt is a
  real lift over v5.3 on stripped fixtures. If B − C ≈ 0, the v5.4
  lift was leakage-driven and the prompt work needs to reopen.

Run A's leaky-fixtures swap depends on the prior fixture revision
being reachable from the current git history. If it can't be located
(detached checkouts, shallow clones), the script falls back to using
the on-disk stripped fixtures for Run A and emits a `WARN`. In that
fallback mode, A and B differ only in judge model — that's still a
useful reading but it does not isolate leakage.

## Acceptance signals

A healthy post-fix gate looks like:

- `uv run pytest tests/eval/test_suite_no_leakage.py` is green.
- `bash -n scripts/run_eval_ablation.sh` is clean.
- Run B verdict_accuracy clears the 0.85 bar per sub-suite under
  `scripts/run_eval_gate.sh`. If it doesn't, the fix surfaced a real
  Judge-quality issue that prompt or routing work needs to address —
  do not re-tune fixtures to recover the number.

## What not to do

- Do not re-tune the prompts against ablation failures. The whole
  point is to measure honestly.
- Do not relax the assertion thresholds in
  `test_suite_no_leakage.py` to make a future fixture pass; fix the
  fixture instead.
- Do not collapse the holdout into `--suite all`. It's a generalization
  check, not part of the cutover gate.
