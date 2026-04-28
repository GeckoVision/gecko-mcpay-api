# Eval Gate Runbook (S2X-15)

**Audience:** Ernani (founder, on-call). Run this once V1 sources have landed
and you're ready to authorize ~$42 of real spend to validate prompts v5 +
V1 sources before mainnet cutover.

**Decision context:** [`docs/decisions/0001-mainnet-after-v1-sources.md`](../decisions/0001-mainnet-after-v1-sources.md)
— mainnet cutover is gated on this gate passing.

**One-liner:**

```bash
./scripts/run_eval_gate.sh
```

---

## 1. Prereqs

Set in your shell **before** running:

```bash
export OPENAI_API_KEY=sk-...                    # 5 AG2 agents (gpt-4o-mini)
export ANTHROPIC_API_KEY=sk-ant-...             # Sonnet 4.6 rubric judge
                                                # CLAUDE_API_KEY also accepted
export GECKO_API_BASE=https://api.geckovision.tech   # default if unset
```

Repo state:

- On branch `main`.
- Working tree clean (`git status` shows nothing).
- Latest `main` deployed on devnet (the API base above must respond on `/healthz`).
- Prompts v5 active (the default; do **not** set `GECKO_PRO_PROMPTS_VERSION=v4`).

Sanity-check the non-paid scaffolding first:

```bash
uv run pytest tests/eval/test_gate.py -q
uv run ruff check
```

Both must be green before you spend a dollar.

---

## 2. What the gate does

1. Asserts env + repo preconditions; aborts on any miss.
2. Prints expected spend and prompts `y/N` to proceed.
3. Runs the three sub-suites sequentially in `--live` mode:
   - `general` (20 ideas) → `tests/eval/live_runs/<date>-general.json`
   - `crypto`  (15 ideas) → `tests/eval/live_runs/<date>-crypto.json`
   - `saas`    (15 ideas) → `tests/eval/live_runs/<date>-saas.json`
4. Reads `aggregate.verdict_accuracy` from each saved JSON.
5. Prints a pass/fail table. Exits 0 only if **all three ≥ 0.85**.

The runs are sequential by design — the API rate-limits aggressively under
parallel `/research` calls.

---

## 3. Expected runtime + spend

| Item | Estimate |
|---|---|
| Runtime (50 ideas, sequential, no reruns) | **30-45 min** |
| x402 devnet spend (50 × $0.75) | **$37.50** |
| AG2 agent tokens (gpt-4o-mini) | ~$3 |
| Rubric judge tokens (Sonnet 4.6) | ~$2 |
| **Total** | **~$42.50** |

Devnet x402 spend goes back to your devnet recipient wallet. The OpenAI +
Anthropic spend is real cash.

---

## 4. On failure (any sub-suite < 0.85)

The script exits non-zero and prints the failing sub-suites. **Do not
proceed to mainnet.** Recovery sequence:

1. **Roll prompts back to v4** for the live API while you investigate:

   ```bash
   aws ssm put-parameter --name /gecko-api/GECKO_PRO_PROMPTS_VERSION \
     --value v4 --type String --overwrite --region us-east-2
   aws ecs update-service --cluster gecko-api --service gecko-api \
     --force-new-deployment --region us-east-2
   ```

2. **Inspect the failing run JSON** under `tests/eval/live_runs/`:

   ```bash
   jq '.ideas[] | select(.actual_verdict != .expected_verdict) | {id, expected_verdict, actual_verdict, scores}' \
     tests/eval/live_runs/<date>-<suite>.json
   ```

   Look for patterns: which expected-`ship` cases are getting killed (false
   negatives) vs. which expected-`kill` cases are getting shipped (false
   positives). Cluster by `expected_categories`.

3. **File a prompt-rework follow-up ticket** (`S2X-15-followup-prompts-vN`)
   tagging the failing sub-suite and 2-3 representative idea IDs.

4. **Loop:** edit prompts in `packages/gecko-core/src/gecko_core/orchestration/pro/prompts/`,
   bump `GECKO_PRO_PROMPTS_VERSION` to `v6`, run mock-mode regression
   (`uv run python -m tests.eval.runner --suite all`), then re-run
   `./scripts/run_eval_gate.sh` once the mock baseline holds.

The mainnet cutover stays blocked until the gate clears.

---

## 5. On full pass (all three ≥ 0.85)

The script exits 0 and prints `S2X-15 GATE: PASS`.

1. Commit the new live-run JSONs:

   ```bash
   git add tests/eval/live_runs/<date>-*.json
   git commit -m "S2X-15: eval gate pass — verdict_accuracy >= 0.85 across all sub-suites"
   git push origin main
   ```

2. **Notify `web3-engineer`** to begin mainnet cutover per
   [`docs/runbooks/mainnet-cutover.md`](mainnet-cutover.md). Include the
   three live-run filenames + per-suite `verdict_accuracy` from the gate
   table.

3. The runbook's §1.7 ("Eval baseline exists") should be updated to point
   at the `<date>-general.json` run as the new canonical baseline.

---

## 6. FAQ

**Can I re-run a single sub-suite?**
Yes:

```bash
uv run python -m tests.eval.runner --suite crypto --live
```

But the gate decision (≥ 0.85 on **each** of the three) requires fresh runs
of all three on the same `main` SHA — don't mix and match across commits.

**What if a single idea blows up mid-run?**
The runner currently propagates exceptions. If a 402 fails or the API
times out on idea 23 of `crypto`, the suite aborts and you've burned the
spend on ideas 1-22 of crypto. Re-run that suite from scratch:
`uv run python -m tests.eval.runner --suite crypto --live`.

**Where do live runs go?**
`tests/eval/live_runs/YYYY-MM-DD-<suite>.json`. Same-day re-runs append
`-2`, `-3`, ... to avoid clobbering. The gate script auto-picks the newest
matching file via `ls -1t`.

**Do mock baselines need updating after a pass?**
No. Mock baselines (`tests/eval/baselines/<suite>_baseline.json`) are
deterministic and decoupled from prompt content; they exist to catch
rubric-itself bugs. The live-run JSON is the new artifact of record for
mainnet eligibility.
