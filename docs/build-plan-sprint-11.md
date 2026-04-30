# Sprint 11 — Verdict unification + thesis-aligned landing + live-V1 hardening

**Status:** ready to fire
**Predecessor:** Sprint 10 closed Tracks A/C/D/E. Track B (mainnet smoke) blocked on Solana mainnet funding.
**Driver:** thesis synthesis (`docs/positioning/2026-04-30-thesis-synthesis.md`) surfaced a sharper macro positioning ("validation layer above frames.ag — approves the spec before agents spend the budget") + the S10 positioning delta documented three concrete landing/research mismatches that need to ship-or-cut before the demo.

**Done = `bb research` prints a single-token verdict (KILL/REFINE/BUILD) backed by the typed gap_classification, the landing copy ships matching that verdict, the F18 V1-sources anomaly is closed, and the eval gate re-passes under the new renderer.**

---

## Tracks

### Track A — Verdict unification renderer (S11-VERDICT-01) **CRITICAL**

The pipeline emits structured `gap_classification` (`Full | Partial:* | False`) + 5 advisor closing lines. The landing word is "verdict: build · narrow · pivot · kill". One of them has to give.

Per thesis (Market Validation Tools dimension): founders need a clear go/no-go signal. Ship the landing word; keep gap_classification as evidence, not as the headline.

**S11-VERDICT-01 — Map gap_classification + advisor consensus → KILL | REFINE | BUILD.**

In `packages/gecko-core/src/gecko_core/orchestration/synthesizer.py` (or wherever the final ValidationReport assembles), add:

```python
def derive_verdict(gap: GapClassification, advisor_consensus: float) -> Verdict:
    if gap in (GapClassification.FULL, GapClassification.FALSE):
        return Verdict.KILL
    if gap in (GapClassification.PARTIAL_PRICING, GapClassification.PARTIAL_INTEGRATION):
        return Verdict.BUILD if advisor_consensus >= 0.8 else Verdict.REFINE
    return Verdict.REFINE  # segment, UX, geo
```

Surface in:
- `bb research` final block: `VERDICT ─────── KILL` + `Gap: Full — competitor X covers all segments.`
- PRD header line 1
- MCP `gecko_research` tool response (add `verdict: "KILL"` field)
- Pro-tier judge prompt (so the judge emits the verdict directly when consensus is clean)

Add tests:
- `tests/orchestration/test_verdict_mapping.py` — all 7 gap_classification values × 3 consensus tiers (low/mid/high)
- E2E: `bb research --idea "test" --tier basic` produces a verdict line

**Owner:** software-engineer
**Acceptance:** every research output has a single-token verdict + the typed gap as a sub-line.

### Track B — Landing copy v2 deployment + thesis sub-fold (S11-LANDING-01..03) **HIGH**

Cross-repo to `gecko-mcpay-app`. Coordination ticket here surfaces the work; full implementation lives in that repo's `frontend-engineer` agent.

- **S11-LANDING-01** — Ship the existing `docs/marketing/landing-copy-v2.md` as drafted. Hero ("Plan your next app for ten cents"), two-card pricing (Basic $0.10 / Pro $0.75), 5-agent grid, six-sources block, "we killed our own pitch" beat with real terminal transcript, three-tier table (Free/Basic/Pro — no Max-tier on V1 apex).

- **S11-LANDING-02** — Add the thesis-derived sub-fold immediately below the hero:
  > **The validation layer above frames.ag.**
  > Agents will spend your money. Gecko approves the spec first — adversarial debate, six sources, fundable PRD — so the budget you fund actually pays for the right work.

  This lands the macro claim from the thesis x402 dimension (Gecko as "budget approver") without overpromising on V1's actual surface.

- **S11-LANDING-03** — Lift the live-V1 eval result as a trust block:
  > **0 false positives in our live-V1 eval. When Gecko says kill, it's a kill.**

  Placement: under "We pointed Gecko at Gecko" as a stat-box reinforcement. Cite `docs/eval/live-v1-results-2026-04-30.md` as the source.

**Owner:** product-designer (copy QA in this repo) + frontend-engineer stub (routes to `gecko-mcpay-app` engineer)
**Acceptance:** apex landing reflects v2 spec + thesis sub-fold + eval trust block; deltas in `landing-vs-research-delta.md` §1a/1b/1c resolved.

### Track C — F18: live-V1 v1_sources_cost anomaly (S11-F18-01) **MED**

`docs/eval/live-v1-results-2026-04-30.md` flagged $0 V1 spend across all 10 holdout-live ideas despite TWITSH_ENABLED + funded wallet.

**S11-F18-01 — Investigate and fix or document.**

Hypotheses to check (in order):
1. **Cache short-circuit** — prior runs of same holdout ideas populated the source cache; `dispatch_sources()` returned cached results without paying. Inspect `packages/gecko-core/src/gecko_core/sources/` cache layer; check if cache key incorporates `--live-rag` flag.
2. **`--live-rag` flag drop** — `tests/eval/runner.py` may pass the flag to the agents but not to the dispatcher. Trace the flag from CLI → orchestrator → source dispatcher.
3. **Silent circuit breaker** — twit.sh client may have a per-suite cap that hit on call 1 and silently skipped 2-10. Read `packages/gecko-core/src/gecko_core/sources/twitsh.py`.

Fix path depends on root cause. Either way:
- Add `idea_id` to the `live_runs` JSON output (currently `null` for all rows) — purely a debug-quality fix.
- Add a WARN log when V1 source dispatch returns 0 spend in a `--live-rag` run.

**Owner:** software-engineer
**Acceptance:** root cause identified + either fixed or documented in `docs/runbooks/eval-gate.md`.

### Track D — PRD ICP update (S11-PRD-01) **MED**

Three docs disagree on the V1 ICP:
- PRD: "solo developer building on Solana or adjacent stacks"
- Landing: "Claude Code / Cursor power users — technical founders, senior engineers, AI-native builders"
- Thesis (Non-developer founders dimension): "non-technical founders, 18% success rate, lacking technical co-founder"

The thesis surfaces a real third audience. Pick one for V1 and document the others as future expansion.

**S11-PRD-01 — Update `docs/PRD.md` V1 persona.**

Recommendation: **converge on landing's framing** ("Claude Code / Cursor power users with founder ambition — technical or technical-adjacent"). Reasons:
- It's where the distribution actually lands (Claude Code skills).
- It includes both the PRD's "solo developer" and a slice of the thesis's "non-technical founder" (the technical-adjacent ones).
- The fully non-technical founder is a Sprint 12+ expansion when the web app at `app.geckovision.tech` ships (CLI is the wrong surface for them).

Update PRD V1 persona section + product-story.md. Note the non-technical founder as V2 expansion target.

**Owner:** business-manager
**Acceptance:** PRD, product-story, and landing all describe the same V1 ICP.

### Track E — Mainnet smoke (CARRY-OVER from S10-LIVE Track B) **BLOCKED**

Solana mainnet wallet still unfunded. Runbook + preflight ready. Standing on user funding.

### Track F — Holdout-live re-baseline under new renderer (S11-EVAL-01) **MED**

Track A changes the verdict shape the eval rubric grades against. Need to confirm the threshold still holds before Sprint 11 merges.

**S11-EVAL-01 — Re-run live-V1 gate twice under new renderer.**

After Track A ships:
1. `bash scripts/run_eval_gate.sh` — confirms general/crypto/saas baselines stay at 1.0 under verdict mapping.
2. `bash scripts/run_eval_gate_live.sh` — twice (separate days if possible to vary live signal).
3. If both runs ≥ 0.85, propose tightening `PASS_THRESHOLD` from 0.80 → 0.85 in S12.
4. If either run < 0.80, treat as a verdict-mapping regression and fix in Track A.

Update `docs/test-plan.md` threshold table after the runs.

**Owner:** staff-engineer (review) + software-engineer (run)
**Acceptance:** two clean live-V1 runs at ≥ 0.80 under the new renderer; results doc appended.

---

## Out of scope

- V3 routed-execution per-task billing (the actual "agents pay per task" surface)
- Auto-labeling of precedents (Sprint 9 backlog item, still deferred)
- Colosseum Copilot as a live source
- Implementing Gecko literally provisioning downstream frames.ag budgets — that's the V3 vision the landing sub-fold *promises*; we earn it by shipping V1 honestly first
- The non-technical founder web-app surface (Sprint 12+ once `app.geckovision.tech` web app exists)

## Acceptance (sprint-level)

- [ ] `bb research` final output prints `VERDICT: KILL | REFINE | BUILD` + typed gap as sub-line
- [ ] All 3 deltas from `landing-vs-research-delta.md` §1 resolved (1a softened, 1b shipped, 1c rewritten)
- [ ] F18 root cause identified + V1 spend either fires correctly OR cache behavior documented
- [ ] PRD, product-story, and landing converge on a single V1 ICP
- [ ] Live-V1 eval gate re-passes under new renderer (≥ 0.80 across 2 runs)
- [ ] Landing v2 + thesis sub-fold + eval trust block deployed to apex

## Test plan

After all tracks land, dogfood once more:
1. `bb research --idea "Gecko: validation layer above frames.ag for Claude Code builders"` → expects `BUILD` or `REFINE` (we believe in our own thesis)
2. `bb research --idea "yet another GPT wrapper"` → expects `KILL`
3. View landing on apex; cross-check verdict word matches output
4. Run `bash scripts/run_eval_gate_live.sh` to confirm threshold

## Reference

- `docs/positioning/2026-04-30-thesis-synthesis.md` — the synthesis driving Sprint 11's positioning moves
- `docs/marketing/thesis/gecko_market_thesis.md` — 8-dimension research package
- `docs/marketing/landing-copy-v2.md` — apex copy spec to deploy
- `docs/positioning/landing-vs-research-delta.md` — Sprint 10 deltas this sprint resolves
- `docs/eval/live-v1-results-2026-04-30.md` — the trust block source
- Sprint 10 commits: `5b92e76`, `fe9d29a`, `1b5acfd`, `c0969d2`, `ed7fc24`, `d322034`, `245fb96`
