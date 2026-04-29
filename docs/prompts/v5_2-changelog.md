# Pro Judge prompt v5.2 — structural pipeline fix

## Motivation

v5.1 (`2026-04-27`) fixed the blunt "no named ICP → KILL" line that caused the
2026-04-28 verdict_accuracy regression, but it under-ships ideas that are
**explicitly named by example** in MANDATORY SHIP rule 1(a)-(d) / rule 2.

Live evidence: `tests/eval/live_runs/2026-04-28-general-2.json` (v5.1,
accuracy = 0.65). Five ideas listed by name in the v5.1 SHIP rules were
false-killed:

| Idea | v5.1 rule that should have shipped it | v5.1 verdict |
|---|---|---|
| `good-cap-table-diff` | rule 1(c) — narrow workflow-replacement, named example | KILL |
| `good-cli-stripe-replay` | rule 1(a) — narrow dev tool, named example | KILL |
| `good-grant-budget-rewriter` | rule 1(c) — narrow workflow-replacement, named example | KILL |
| `good-faa-part107-checklist` | rule 2 — regulated vertical, regulation-as-moat | KILL |
| `good-mcp-postgres-explainer` | rule 1(b) — narrow agentic-infra MCP, named example | KILL |

## Root cause

v5.1 presents MANDATORY SHIP and MANDATORY KILL as parallel sections, with
conflict resolution rules at the bottom. LLMs read sections sequentially and
over-weight whichever section appears later. The current structure causes the
"no named ICP" KILL to dominate even when the idea is in the SHIP-by-name list
two paragraphs above.

## Fix

Restructure the Judge's decision section as a **strict numbered execution
pipeline** with hard EXIT semantics (parallel rules → ordered pipeline):

```
STEP 1 — Precedent ground truth (≥2 SHIP/KILL precedents → EXIT)
STEP 2 — Named-example SHIP check (HARD EXIT for the curated list)
STEP 3 — Pattern-class SHIP check (narrow dev/infra/workflow/research tools)
STEP 4 — KILL check (only reachable if STEPS 1-3 didn't fire)
STEP 5 — Default SHIP to Analyst's named segment
```

The critical change: SHIP-by-name is a **hard exit at STEP 2**. The Critic's
"no named ICP" line cannot kill a STEP 2 idea because the prompt instructs the
Judge to EXIT before reaching STEP 4.

Analyst, Critic, Architect, Scoper prompts are inherited verbatim from v5.1.
Scoring rubric (TAM / WEDGE / V1_FEASIBILITY) and output format are unchanged.

## Expected eval delta

The five false-killed ideas above should flip to SHIP because they are now
named explicitly in STEP 2's curated list, which exits before STEP 4's KILL
check is even reachable. Eval gate (S2X-15) thresholds remain
`general 0.55 / crypto 0.53 / overall 0.60`; user re-runs the live gate.

## Rollback

```bash
GECKO_PRO_PROMPTS_VERSION=v5.1   # parallel SHIP/KILL sections
GECKO_PRO_PROMPTS_VERSION=v5     # pre-2026-04-28 baseline
GECKO_PRO_PROMPTS_VERSION=v4     # original
```
