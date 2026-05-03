# ICP — Gecko Builder Bootstrap

- **Owner:** product-manager
- **Status:** DRAFT (`hypothesis`) — pending three in-person watch sessions ernani is running
- **Date:** 2026-05-02
- **Cross-ref:** [`docs/strategy/program-judges-wedge.md`](strategy/program-judges-wedge.md) — supply-side wedge that maps to this demand-side ICP. Judge-program coverage = ICP coverage.

## Positioning sentence

> Gecko gives crypto builders a deep, multi-voice verdict on their idea — with the dissent and falsifiers attached — so they know what to do next. Complementary to frames.ag (settlement) and Bazaar (marketplace).

solana.new is **community infrastructure** (like Colosseum tools) — neither competitor nor positioning peer. It's just one of the things builders also use; we don't frame against it or alongside it. The factual mention here stands because Caio uses it; it isn't part of our positioning frame.

## 1. Primary ICP — "Caio" (`hypothesis`)

A named persona, not a segment.

- **Who:** 28, full-stack dev, São Paulo. Two prior Solana side projects (one shipped, one abandoned). Registered for an active Superteam Brasil hackathon.
- **Current tools:** ChatGPT free, Perplexity, solana.new skills, Superteam Discord, crypto Twitter/X.
- **Decision he's stuck on:** has TWO candidate ideas, 9 days before submission. Needs to *kill one and commit*. Not "validate" — *commit*. The cost of indecision is 80 hours split badly across two half-built submissions.
- **Falsifiable trigger to try Gecko (free tier):** hears about it via Superteam Discord or a solana.new skill cross-link, and runs it once on the idea he secretly wants killed. The free run gives him permission to confirm what he already suspects.
- **Falsifiable trigger to pay $2.50:** the basic verdict shows REFINE with surviving dissent he can't resolve from the teaser, and he's about to allocate 8 days to one path. $2.50 against an 80-hour bet is rounding error — but only if the dissent is real, dated, and falsifiable.

Every claim above is `hypothesis` until ernani's in-person watch sessions land. After three sessions consistent with the brief, statuses move to `validated`. One disconfirming session forces a rewrite.

## 2. Anti-persona — "Pre-seed founder with 14 months runway"

- Wants dissent. *Has the wrong clock.*
- Should be running 6-week customer discovery sprints, not buying a $2.50 verdict.
- Sending them a Gecko link is a category error: our surface area is built for someone with *less* time, not more. They'll read the verdict, nod, and not change behavior — because their constraint isn't decision pressure, it's discovery throughput.
- This is sharper than the obvious "cheerful validation seeker — use solana.new" anti-persona, because the funded founder *does* want depth. Just the wrong shape of depth. Long-cycle discovery, not short-cycle commit-or-kill pressure.

If you can't write a sharper anti-persona than this, the ICP isn't narrow enough yet.

## 3. The "deep analysis + guided direction" moat

Two structural claims, not adjectives.

- **Deep is more shape, not more tokens.** The verdict is structured: voices disagree on dimensions a single-model summary collapses. A longer Perplexity answer is not a deeper one — depth is the *shape* of the disagreement, not the wordcount of the consensus.
- **Direction is `(action, surfaced_by_voice, falsifier{what, by_when})`.** Each next step traces back to a specific voice in the debate and forward to a dated check that disproves it. "Sign LOI with Transfero by 2026-05-23" is direction. "Consider partnerships" is content.
- **The non-obvious part: direction without dissent is brittle.** Anyone can hand a builder five next steps. The reason ours hold up under stress is that they survived adversarial debate before reaching the user — they carry the dissent with them, in the surviving-dissent block. Strip the dissent and you're back to a confidently wrong consultant.

Orchestration is table stakes. The wedge is the verdict shape + the falsifier-bound direction + the surviving dissent. (Pattern D from CLAUDE.md.)

## 4. Willingness-to-pay trigger

The prior commitment Caio has *already made* is the **hackathon submission slot itself** — calendar-locked, publicly signaled in a Discord, with a deadline he can't move. That commitment is what makes $2.50 trivial. It's not the price of a coffee; it's a 0.003% line item against an 80-hour bet on a public deadline.

> If we can't name a Caio with a calendar-locked external commitment, the paywall layer is wrong and we're upselling tourists.

This is the disqualifying test for any "we should also target X" expansion: does X have a calendar-locked external commitment? If not, defer.

## 5. Direction-quality audit (PM-owned, manual, ~5 min/run)

Run periodically against recent verdicts. Threshold: ≥80% pass.

- **(a) Stranger test.** Can a stranger tell on the falsifier date whether the step is true or false **without asking the founder**? If no → vague falsifier. Drop or rewrite.
- **(b) Voice-engagement test.** Does each `surfaced_by_voice` actually appear `engaged` in `per_voice`? If a step claims a voice that didn't engage, the attribution is theatre.
- **(c) Imperative-verb test.** Read all 5 actions aloud. Any contain "iterate / explore / consider / gather"? → content, not direction. Strip.

**Below 80% pass:** escalate to ai-ml-engineer first (prompt issue), product-designer second (rendering issue). Do not escalate to product-designer on a prompt problem.

## 6. Channel — where Caio actually is

All channel claims `hypothesis` until ernani's in-person validation.

- **Superteam Brasil Discord** — specifically `#pt-br` and `#hackathons`. (`hypothesis`)
- **Superteam Brasil X account followers** — re-share velocity is the read; raw follower count isn't. (`hypothesis`)
- **Solana Foundation Brazil Telegram** — if one exists in active use; confirm with ernani. (`unanswered`)
- **solana.new skill cross-links** — if/when a skill recommends Gecko as the kill-or-commit step before scaffold-project. (`hypothesis`, depends on community-infra coordination)

"Twitter" without a named handle/list/channel doesn't count. If you can't name the surface, you don't know the channel.

## 7. What we are NOT building this week / sprint

Explicit guardrails. Each is a "no" we will defend in standup.

- **Not** for global hackathon participants. BR-first per the S21 plan. Geographic narrowing is a feature, not a limitation.
- **Not** for funded founders. They are the anti-persona; sending them links is a category error.
- **Not** for non-technical founders. CLI-first product surface. Web app is V2 and lives in `gecko-mcpay-app`.
- **Not** generic "idea validation." We are building "kill or commit" pressure-cooker support. The deadline is the product mechanic.

If a feature request lands and matches one of the above, the answer is no until the named-ICP-named-decision bar is cleared.

## 8. Open questions (each `unanswered` until evidence)

- Does Caio actually pay $2.50 unprompted, or does he hesitate at the paywall? (validates with watch sessions — observe the click, don't ask)
- Does Caio read the surviving-dissent block, or skip past it to the action list? (validates with screen-share — eye-track if possible, scroll behavior otherwise)
- Is the **9-days-before-deadline** window the right urgency, or is the trigger earlier (registration moment) or later (3 days before)? (validates with structured interview across the 3 sessions)
- Does the program-judges S21 wedge actually unlock pull from Caio — because he's *applying* to the program he's being judged against — or is it just supply-side branding? (validates after first judge-config ships and we can measure attribution from `judge:` runs)

## 9. Status

DRAFT — `hypothesis`. Will be updated to `validated` or `falsified` per claim after ernani's three in-person watch sessions land. If any single claim above survives all three sessions unchallenged, that's a flag for confirmation bias in the script — push back on the interview design, not the ICP.
