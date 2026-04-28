# Pro tier prompts — v4 → v5 changelog

**Ticket:** S2X-11
**Default version:** `v5` (selected via `GECKO_PRO_PROMPTS_VERSION`, default
unset → `v5`). Set `GECKO_PRO_PROMPTS_VERSION=v4` to roll back without a code
change. `GECKO_PROMPTS_PATH` (full file override) still wins over both.

## Why

Wave 2 lands four new V1 sources. v4 only knows about Tavily-shaped sources,
so the agents had no guidance on how to weight them. v5 names each source
explicitly and tells the relevant agent what counts as strong vs weak signal
from it.

| Source            | Ticket | Status                       |
|-------------------|--------|------------------------------|
| `gecko_precedent` | S2X-06 | shipped this PR              |
| `colosseum`       | —      | already exists               |
| `hn` / `reddit`   | S2X-07 | parallel (Wave 2)            |
| `twit_sh`         | S2X-08 | parallel (Wave 2)            |

## Per-agent diff summary

### Analyst
- New "V1 source weighting" section with one-line guidance per source.
- `gecko_precedent`: when ≥2 prior killed similar ideas, weight that signal
  heavily and cite the precedent verdict in the TAM bullet.
- `colosseum`: finalists/winners count as "recent shipped comparable" even
  on pivot.
- `hn` / `reddit`: prefer threads with substantive comments from the named
  ICP over upvote-heavy threads.
- `twit_sh`: a builder publicly asking for X is stronger demand evidence
  than a journalist describing X as a trend.

### Critic
- New "V1 source weighting for demand evidence" section.
- `twit_sh`: builders publicly complaining about lack of X is *stronger*
  than a Tavily article. A complaint with a builder's handle attached IS a
  named user who would pay within 30 days.
- `gecko_precedent`: when prior similar ideas were killed for the same
  reason you're about to raise, say so explicitly — name the precedent.
- `hn` / `reddit`: distinguish hollow upvote threads from substantive
  builder discussion.
- `colosseum`: a finalist that shipped and stalled is a kill signal, not a
  demand signal.

### Architect
- One new paragraph: when `colosseum` surfaces a winning hackathon project
  in the same category, look at their stack before defending the default.
  Don't copy uncritically, but don't pretend it doesn't exist.

### Scoper
- One new paragraph: when `twit_sh` or `hn`/`reddit` names a specific
  builder with a specific complaint, frame V1 as "ship the thing that
  solves THAT builder's complaint." When `gecko_precedent` shows a prior
  KILL with `V1_FEASIBLE_IN_4_DAYS=no`, treat that as the prior unless the
  current V1 is materially smaller.

### Judge
- New top-level section "GECKO PRECEDENT IS GROUND TRUTH" applied BEFORE
  the ship/kill rules. Prior verdicts on similar ideas are treated as
  ground truth — explain disagreement before overriding them. Silent
  disagreement is forbidden; the judge must say "Overriding precedent
  [summary] (verdict=KILL) because [specific difference]."
- ≥2 prior KILL precedents + no named differentiator → KILL regardless of
  what the Critic conceded.
- ≥2 prior SHIP precedents in the same shape → SHIP barring a fresh kill
  criterion.
- Mandatory KILL still wins on collision (precedent does not rescue a
  saturated b2c kill).

## What did NOT change

- The 1-10 scoring axes (TAM / WEDGE / V1_FEASIBILITY).
- The mandatory SHIP rules 1-2 (narrow dev tools, regulated verticals).
- The mandatory KILL rules (saturated b2c, no named ICP, V1 not feasible).
- Output shape for any agent.
- The Scoper's `V1_FEASIBLE_IN_4_DAYS: yes|no` contract line.

## Rollback

```bash
GECKO_PRO_PROMPTS_VERSION=v4
```

`v4` is kept on disk at
`packages/gecko-core/src/gecko_core/orchestration/pro/_default_prompts.json`
exactly as it shipped (verdict_accuracy 0.85 baseline). The bundle map is in
`packages/gecko-core/src/gecko_core/orchestration/pro/prompts.py`.

## Eval impact

The mock-mode eval harness uses canned transcripts (it does not invoke the
prompts), so prompt changes cannot regress the mock baseline. The live-mode
eval gate (S2X-15) is out of scope for this ticket and will be the
authoritative measure of v5 vs v4 verdict accuracy on real LLM calls.
