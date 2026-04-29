# Pro Judge prompt v5.3 — keyword-trigger fix

## Motivation

v5.2 (`2026-04-28`) restructured Judge decisions into a numbered pipeline so
SHIP-by-name exited at STEP 2 before the KILL check could fire. It partially
worked — but two failure modes remain in
`tests/eval/live_runs/2026-04-28-general-3.json` (accuracy = 0.65).

### Failure mode 1 — STEP 2 matched only by exact dash-cased name

The v5.2 STEP 2 list spells out examples like `cap-table-diff`,
`mcp-postgres-explainer`, `faa-part107-checklist`. The Judge wouldn't match
ideas whose text described that pattern in normal English:

| Idea text | v5.2 STEP 2 entry that should match | v5.2 verdict |
|---|---|---|
| "Carta-aware cap table diff tool: paste two SAFE term sheets, get a side-by-side dilution model" | `cap-table-diff` | KILL |
| "MCP server for Postgres ..." | `mcp-postgres-explainer` | KILL |
| "Airtable typed MCP" | `airtable-typed-MCP` | KILL |
| "FAA Part 107 checklist" | `faa-part107-checklist` | KILL |
| "NIH grant budget rewriter ..." | `grant-budget-rewriter` | KILL |

### Failure mode 2 — STEP 4 saturation list softened vs v5.1

| Idea | v5.1 verdict | v5.2 verdict |
|---|---|---|
| `bad-uber-for-dogwalkers` | KILL | SHIP (regression) |
| `bad-meeting-summarizer` | KILL | SHIP (regression) |

v5.2 STEP 4 was a single prose paragraph listing patterns. The Judge needs
hard-exit keyword triggers mirroring STEP 2.

## Fix

Judge-only changes; Analyst, Critic, Architect, Scoper inherited verbatim
from v5.2 / v5.1.

### STEP 2 — explicit keyword Triggers per named entry

Every STEP 2 entry now carries a `Trigger: idea text contains ...` line with
concrete keyword combos. The matching instruction is changed to:

> Match an idea to the list when the idea text satisfies that entry's Trigger
> condition. Do NOT require the dash-cased example name to literally appear.
> The Trigger keywords are the source of truth.

### STEP 4 — keyword Trigger pipeline mirroring STEP 2

The prose saturation paragraph is replaced with one bullet per kill class,
each carrying a `Trigger: idea text contains ...` keyword line. First match
wins, exit immediately. This restores the v5.1 hard-kill behavior on
`bad-uber-for-dogwalkers` and `bad-meeting-summarizer` while keeping v5.2's
named-SHIP exits intact.

### STEP 5 (default) — unchanged

> If you reach this step, SHIP V1 to <Analyst's named segment>. Reaching here
> means none of STEPS 2-4 fired; default to builder-pilled.

## Expected eval delta

The five false-killed STEP 2 ideas should flip to SHIP because their idea
text now satisfies the Trigger keyword condition. The two false-shipped
saturation kills should flip back to KILL because STEP 4 now fires on
keywords (Uber, meeting + summarizer) instead of pattern-class assertions.
Eval gate (S2X-15) thresholds remain `general 0.55 / crypto 0.53 /
overall 0.60`; user re-runs the live gate.

## Rollback

```bash
GECKO_PRO_PROMPTS_VERSION=v5.2   # pipeline without keyword triggers
GECKO_PRO_PROMPTS_VERSION=v5.1   # parallel SHIP/KILL sections
GECKO_PRO_PROMPTS_VERSION=v5     # pre-2026-04-28 baseline
GECKO_PRO_PROMPTS_VERSION=v4     # original
```
