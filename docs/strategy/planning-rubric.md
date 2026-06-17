# Gecko Planning Rubric (standing dev rule)

**Rule (founder, 2026-06-16):** Every new implementation plan, roadmap, or major
feature is scored against the Colosseum judging rubric *before* we commit to it.
The weights force us to spend effort where it's actually rewarded — **Novelty
(30%) and Potential Impact (25%) are 55% of the score**; functionality is table
stakes; UI/UX, business-plan, and open-source are tie-breakers.

Score each new plan with this block (paste into the plan doc):

```
## Rubric score (Colosseum weights)
| Dimension | Weight | Score (0–10) | Why |
|---|---|---|---|
| Novelty | 30% | _ | original vs existing? what's the defensible wedge? |
| Potential Impact | 25% | _ | TAM + Solana-ecosystem impact |
| Functionality | 20% | _ | does it work? network stage (Mainnet/Devnet/Concept) |
| UI/UX (composability) | 10% | _ | integrates with Solana tooling / pluggable? |
| Business Plan | 5% | _ | would someone pay/invest? GTM clear? |
| Open-Source | 5% | _ | is it (or can it be) open-source? |
| **Weighted total** | 100% | **_** | |
```

## Scoring guide (from the rubric image)
- **Novelty (30%, [10..1]):** 10 = groundbreaking/original; 1 = clone of existing.
  *This is our biggest lever — lead every plan with the defensible wedge, not the
  feature list. "Orchestration is table stakes" (Pattern D): name the real moat.*
- **Potential Impact (25%, [10/5/3/0]):** market size ([10] large+strong → [0]
  none) AND Solana-ecosystem impact ([10] major positive → [0] none). Score the
  lower of the two unless noted.
- **Functionality (20%):** works ([10] fully functional → [0] concept-only) AND
  network stage ([10] Mainnet, [7] Devnet/Testnet, [5] concept built, [0] idea).
  *Our wedge being live in prod moves this from 5→10.*
- **UI/UX — composability (10%, [10/7/5/3/0]):** how well it plugs into Solana's
  ecosystem + tools. *BYOA / "plug your agent" / MCP-surface work scores high here.*
- **Business Plan (5%):** would-you-invest ([10/0]) + GTM ([10/5/3/0]).
- **Open-Source (5%, [10/0]):** binary. *The repo is already public; skills/SDK
  open-source = free 10.*

## How to use it
1. When drafting a plan (the `writing-plans` flow) or a roadmap, fill the block.
2. If Novelty < 7 or Impact < 7, **stop and re-scope** — we're building table
   stakes, not a wedge. Find the moat (verdict shape, anti-wash signal,
   settlement layer, contributor reputation) and lead with it.
3. Record the score in the plan doc so future-us sees why we prioritized it.

*Source: Colosseum hackathon judging rubric (founder-supplied 2026-06-16).*
