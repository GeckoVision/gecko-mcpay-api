# Thesis synthesis — positioning + Sprint 11 next steps

**Date:** 2026-04-30
**Inputs:**
- `docs/marketing/thesis/gecko_market_thesis.md` (8-dimension research)
- `docs/marketing/landing-copy-v2.md` (apex copy spec, 2026-04-28)
- `docs/positioning/landing-vs-research-delta.md` (S10-POSITION-02)
- `docs/eval/live-v1-results-2026-04-30.md` (S10-EVAL-01 PASS @ 0.80)

---

## TL;DR positioning recommendation

**The thesis surfaced a sharper hook than the current landing copy.**

Landing v2 hero: *"Plan your next app for ten cents."*
→ Concrete, conversion-focused. Keep as primary CTA.

Thesis-derived positioning thread (currently absent from landing): **Gecko is the intelligence layer above x402 + frames.ag. It approves the spec before the agents spend the budget.**

This is the line the thesis surfaces in three different dimensions:
- **x402 dimension** (line 110): *"GECKO can act as the 'budget approver' for downstream development agents… GECKO's validated specs become the authorization policy."*
- **Spec-driven dimension**: pre-build adversarial validation = the thing the market lacks above existing spec tools (Intent, Kiro, BMAD).
- **Subscription fatigue dimension**: pay-per-run is the *economic* expression of the same idea — only spend when the validation actually fires.

**Net:** the wedge is not "research tool" or "PRD generator" — it's **"validation as authorization policy."** Gecko sits above frames.ag the way a CFO sits above a payments team.

---

## Three positioning moves Sprint 11 should make

### Move 1 — Add the "approve before spend" thread to landing (2nd fold)

Hero stays: "Plan your next app for ten cents." (action / cost / clarity)

Add sub-fold framing that makes the macro claim:

> **The validation layer above frames.ag.**
> Agents will spend your money. Gecko approves the spec first — adversarial debate, six sources, fundable PRD — so the budget you fund actually pays for the right work.

This lands three thesis claims in one block:
- pre-build validation (the wedge)
- frames.ag is a partner, not a competitor (the relationship)
- pay-per-run aligns with the agent economy (the why)

### Move 2 — Drop "agents pay per task" misrepresentation; replace with the truth

Per `landing-vs-research-delta.md` §1c, current landing claims "agents pay per task under the hood" — V1 doesn't do this. The thesis-aligned line is:

> "Pay per validation. Then fund the build budget Gecko approved."

This is honest about V1 (validation is per-run priced) while teasing the V3 routed-execution surface that the thesis-derived "authorization policy" framing depends on.

### Move 3 — Make the verdict shape match the landing word

Per delta §1b: pipeline emits `gap_classification` (Full/Partial:*/False), landing promises "build · narrow · pivot · kill". Pick one — and the thesis says **pick the landing words.**

Reason: the thesis dimension on "Market Validation Tools" emphasizes founders need a **clear go/no-go signal** ("Successful AI startups use a five-stage validation framework aligning MVP build with quantifiable market signals"). `Partial:integration` is precise but doesn't ship the dopamine. KILL ships dopamine.

**Sprint 11 ticket:** ship the renderer mapping `Full/False → KILL`, `Partial:segment|UX|geo → REFINE`, `Partial:pricing|integration + advisor consensus ≥ 4/5 → BUILD`. Print the gap_classification as a sub-line for technical credibility.

---

## What the eval gate confirmed (Sprint 10 → 11 bridge)

`docs/eval/live-v1-results-2026-04-30.md` shows the rubric is conservative — 5/5 kill recall, 3/5 ship recall, 0 false positives. **This is the right shape for an "approve before spend" tool.** A noisier ship recall is acceptable; what matters is the kill signal is reliable.

The ledger is now: the model says KILL → builders should trust it. The model says BUILD → the advisors have agreed. The model says REFINE → the gap is structural and addressable.

This empirical fact is the strongest piece of trust copy on the landing. Lift it:

> **0 false positives in our live-V1 eval. When Gecko says kill, it's a kill.**

Place under "We pointed Gecko at Gecko" as a stat-box reinforcement.

---

## Sprint 11 plan (proposed)

### Track A — Verdict unification renderer (S11-VERDICT-01) **CRITICAL**
Map `gap_classification + advisor consensus → KILL | REFINE | BUILD` in `bb research` output + PRD header + MCP tool response. Print the typed `gap_classification` as an explanatory sub-line for credibility. Update tests. **Owner:** software-engineer.

### Track B — Landing copy v2 deployment + thesis sub-fold (S11-LANDING-01..03) **HIGH**
Cross-repo to `gecko-mcpay-app`. Three tickets:
- **S11-LANDING-01** Ship landing-copy-v2.md as drafted (hero, two-card pricing, 5-agent grid, sources block, "we killed our own pitch" beat).
- **S11-LANDING-02** Add the thesis-derived sub-fold ("validation layer above frames.ag").
- **S11-LANDING-03** Lift the live-V1 eval result as a trust block ("0 false positives").
**Owner:** product-designer + frontend-engineer (cross-repo via stub).

### Track C — F18 investigation: live-V1 v1_sources_cost = $0 (S11-F18-01) **MED**
`docs/eval/live-v1-results-2026-04-30.md` flagged $0 V1 spend across all 10 holdout-live ideas despite TWITSH being enabled. Either confirm cache short-circuit is intended (and document) or fix dispatcher flag propagation. Add `idea_id` to live_runs JSON output for post-hoc debug. **Owner:** software-engineer.

### Track D — PRD ICP update (S11-PRD-01) **MED**
Per delta §3 last row + thesis "Non-developer founders" dimension: PRD says "solo developer on Solana", landing says "Claude Code / Cursor power users", thesis says "non-technical founders are 18% success rate". Update PRD V1 persona to **"Claude Code / Cursor power users with founder ambition — technical or technical-adjacent"** so all three docs converge. **Owner:** business-manager.

### Track E — Mainnet smoke (carry-over from S10-LIVE Track B) **BLOCKED on user funding**
Solana mainnet wallet still unfunded. Runbook is committed and ready (`docs/runbooks/live-mainnet-smoke.md`). Standing on user.

### Track F — Holdout-live re-baseline (S11-EVAL-01) **MED**
Once Track A's verdict mapping ships, the rubric needs a re-fit (the eval suite grades "build/narrow/pivot/kill"-shaped expected verdicts; today they're being mapped from `gap_classification` heuristically). Run the live-V1 gate twice more under the new renderer to validate the 0.80 threshold holds, then tighten to 0.85 if both pass. **Owner:** staff-engineer (review) + software-engineer (run).

---

## Out of scope (Sprint 12+)

- The "agents pay per task" V3 surface (routed-execution micropayments) — needs `gecko_route` per-call billing first.
- Auto-labeling of precedents (still in S11 backlog from Sprint 9).
- Colosseum Copilot as a live source (interesting per thesis spec-driven dimension; not high-leverage right now).
- The "validation = authorization policy" full implementation (i.e. Gecko literally provisioning the downstream agent's frames.ag budget). This is the V3 vision the landing sub-fold *promises*; building it is its own multi-sprint arc.

---

## Why this plan and not more thesis-mining

The 8-dimension thesis is rich, but Sprint 11 only needs three things:
1. Make the landing match what the pipeline actually does (Track A + B + D).
2. Stop the live-V1 anomaly from rotting under us (Track C).
3. Validate the new renderer doesn't regress the eval gate (Track F).

The thesis's bigger ideas (validation-as-authorization-policy, downstream agent budgeting, the V3 routed-execution surface) are *positioning fuel* — they belong on the landing as the macro claim, not as Sprint 11 implementation. We earn them by shipping V1 honestly first.
