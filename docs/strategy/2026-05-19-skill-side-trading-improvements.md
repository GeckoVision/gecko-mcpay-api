# Skill-Side Trading-Verdict Improvements (S39-#139)

**Mode:** read-only research brief. No code edits, no eval-suite runs, no
prompt-library changes shipped in this pass. Time budget: ~30m. Companion
to `2026-05-19-okx-contest-execution-brief.md` (#137) and
`2026-05-19-gecko-verdict-demo-comparison-design.md` (#128).

**Scope question:** at the skill / agent-prompt / verdict-synthesis level —
independent of any canon ingestion work — what tightens make Gecko's
trading verdicts more *actionable* on spot-trading questions without
burning the abstain-not-fabricate wedge?

**Evidence in front of us:** today's 3-poll live run (JTO / JUP / PYTH) at
`/tmp/gecko_demo_poll.json`. All three returned `defer @ 0.65–0.70`. All
three coordinators emitted `pass`. Post-coordinator CODE rewrote `pass →
defer` in all three. The full per-persona parse:

| ticker | tech | sent | fund | risk | strat-intent | coord (raw) | final (post-code) | escalation |
|---|---|---|---|---|---|---|---|---|
| JTO | bearish | neutral | stable | elevated | observe | pass | **defer** | abstain-floor (3/4) |
| JUP | bearish | neutral | stable | elevated | observe | pass | **defer** | abstain-floor (3/4) |
| PYTH | bearish | neutral | stable | **unacceptable** | observe | pass | **defer** | S37-WS2 Rule 1 (risk-veto) |

That table is the load-bearing diagnosis. Two of the three defers are
**not** coordinator caution — they are
`_count_abstains() >= 3` in
`packages/gecko-core/src/gecko_core/orchestration/trade_panel/__init__.py:601`
rewriting a coordinator `pass` into `defer`. The third is `risk =
unacceptable + strategist = observe` triggering S37-WS2 Rule 1
(`:620–630`). The panel and the coordinator agreed: *decline these
trades.* CODE turned that decline into "we couldn't decide."

---

## Bottom line — top 3 interventions, ordered by impact ÷ hours

### 1. Stop counting `sentiment=neutral` + `fundamental=stable` as abstains for trade-vertical questions. (≈1.5h, **needs ship-gate re-run**)

`_ABSTAIN_TOKENS` at `__init__.py:330` treats every non-extreme band as
an abstain. That mapping is correct for *yield* questions (where "neutral
sentiment" really does mean "no signal"); it is structurally wrong for
*spot-momentum* questions where the personas' own prompts (esp.
`sentiment_analyst`, `_default_prompts.json` line 6) explicitly say
*"'neutral' is the honest default when the corpus is muted or mixed. It
is NOT an abstain signal."* The prompt declares neutral as a real read.
The CODE treats it as a non-read. The CODE wins, and you get
`defer @ 0.70` instead of `pass @ 0.65`.

**Change:** narrow the `_ABSTAIN_TOKENS` set on a per-vertical basis:
either (a) tighten to `{technical: mixed, fundamental: stable-with-cited-gap-only}`
which requires inspecting prose, or (b) the cheaper version — drop
`sentiment: neutral` and `risk: elevated` out of the abstain set entirely
(elevated risk is already its own dissent signal via `_count_dissent`,
and `_CONF_PENALTY_PER_ABSTAIN` is already separately applied — counting
it twice is double-jeopardy). Keep `technical: mixed` (true abstain) and
`fundamental: stable` (true abstain).

**Expected behavior shift:** on today's three polls, JTO and JUP would
exit the panel as `pass @ ~0.60` (the coordinator's own call). PYTH still
defers via S37-WS2 Rule 1 (correctly — `risk=unacceptable + strategist
declined`). The agent gets two clean *declines* instead of three "I
couldn't decide" outputs. That is the contest-actionable shape.

**Falsifier:** re-run #115's N=50 verdict-accuracy fixture set (the
S37-WS2 ship-gate input). The ship-gate target is 6/6 verdict_accuracy on
the gate set. If this change drops any of those rows below their
fixtures' `expected_verdict`, revert. Cost: ~$5 fixture rerun.

**Ship-gate re-run required:** yes. This is the load-bearing rule that
recovered #115 misses; the test set is exactly the way to know if the
narrowing regresses.

**Cross-reference:** `feedback_prompt_iteration_plateau.md` — coordinator
verdict logic belongs in CODE, not PROMPT. This change *stays in code*
(the right home) and only narrows the existing rule. Does not touch the
coordinator prompt.

### 2. Skill-side question framing: anchor spot-trade questions with an explicit decision frame. (≈1h, **no ship-gate re-run**)

The skill (a future `gecko-trade-verdict` mirror of `gecko-yield-verdict`)
controls the `idea` string passed to `gecko_trade_research`. The 3-poll
inputs (verifiable from the panel turns) were of the shape *"should I
open a long position in JTO on Solana"*. The panel responded by reaching
for cycle-position framing (Marks, Damodaran) which is the canon corpus
we have — and which is structurally a *value-investing* lens, not a
12-hour spot lens. The technical_analyst persona (`_default_prompts.json`
line 5, marked as "macro_regime_analyst" internally) is by-design *not*
a chart reader. With no actual chart-reading voice, the panel cannot
ground a short-horizon directional call, so it defers to regime, and
regime in May 2026 reads as risk-off → bearish → no entry.

**Change at the skill layer** (no panel-side code or prompt edits):

- **Anchor horizon explicitly in the idea string.** Rather than *"should
  I long JTO?"*, emit *"Given a 7-day horizon and 1% sizing, does the
  panel see a thesis to scale into JTO, or is this a no-trade?"* The
  panel's strategist matrix (`_default_prompts.json` line 9) keys off
  `horizon ∈ {intraday, days, weeks, months}` and the DEFAULT-ACTION
  MATRIX. An explicit horizon collapses one degree of freedom and pulls
  the strategist toward `scale_in / observe` rather than the indecisive
  "observe for clearer signals."

- **Anchor the decision class explicitly.** Add to the idea string: *"A
  'pass' verdict is a useful answer; we are deciding whether to skip this
  candidate, not whether the protocol is doomed."* This neutralizes the
  bias toward `defer` that the coordinator picks up from "I am giving
  trading advice" framing.

- **Pre-filter the candidate universe BEFORE calling the oracle.** Do
  not ask about tokens for which the corpus has < N protocol-native
  chunks. The skill can probe `evidence_citations` cheaply via a `tier=
  basic` precall or a corpus-coverage heuristic kept in the skill. If a
  ticker has zero protocol-native chunks (e.g. nothing in `paysh_live`
  or `protocol_native` provider_kind), route to the honest-no path
  (intervention #3) without burning a Pro tier call.

**Expected behavior shift:** the strategist closing-line changes from
*"observe for clearer signals before entering a long position"* (which
S37-WS2 Rule 1 reads as `_strategist_says_nonaction = True`) to a
horizon-bounded direction. That doesn't necessarily flip to `act` — the
right answer on JTO today probably *is* `pass` — but it stops the
default-to-defer collapse.

**Falsifier:** spend $0 by running the same 3 tickers through the
modified skill against the existing oracle. If at least 2 of 3 return a
non-defer verdict and the verdicts read as "we considered this and
declined" rather than "we couldn't decide," it shipped.

**Ship-gate re-run required:** no. Skill-only change. The oracle's
behavior is unchanged.

### 3. Build the honest-no path explicitly into the skill. (≈2h, **no ship-gate re-run**)

For questions Gecko's corpus is structurally ill-fit to (*"what's the
12h directional move on JTO"*), the right product behavior is to *say
that*, not to run the panel and emit `defer`. `gecko-yield-verdict` does
this implicitly via Step 0 routing; `gecko-trade-verdict` should do it
explicitly.

**Add to the skill SKILL.md a `Class E — out-of-scope` route:**

```
| User intent | Route |
|---|---|
| "what will <token> do in the next 1–24h", short-horizon directional | **DECLINE** — return "Gecko declines short-horizon directional calls; its corpus is investor-canon literature (Marks/Damodaran/Berkshire) which grounds cycle-position reads on weeks-to-months horizons. For 12h directional, use kline-indicator or okx-dex-market." |
| "weeks-to-months thesis on <token>" | This skill — continue |
```

Codify a simple rule in the skill driver: if the user's question contains
a horizon token in `{1h, 4h, 12h, 24h, today, tomorrow, this week,
next-N-hours}`, route to DECLINE before calling the oracle. The decline
message names what Gecko *can* answer well (weeks-to-months thesis,
deposit/yield decisions, regime context) — turning a refusal into a
hand-off, the way `gecko-yield-verdict` hands off to `okx-defi-invest`
when the user already decided.

**This is a feature, not a limitation.** The OKX rubric rewards skills
that have a clean scope; an honest "this isn't my call" is more
defensible than a `defer` on a question the panel cannot ground. It also
saves ~$0.10/oracle call on questions the oracle would defer anyway.

**Expected behavior shift:** the contest-window agent never burns an
oracle call on a short-horizon directional. The agent's narrative to the
contest judges shifts from *"the oracle declined to decide"* to *"the
oracle declines this question class — here is the class it does answer
and the answers it gave."*

**Falsifier:** before-shipping, sample 20 of the contest's likely
candidate questions, route through the new Class E filter, and confirm
the remaining (Class A–D) set still returns useful verdicts on
`gecko-yield-verdict`'s existing fixtures. Time: ~30m.

**Ship-gate re-run required:** no. Skill-only.

---

## Question 4 from the brief — the honest no answer

A partial yes. The panel **can** be tuned for short-horizon spot trading,
but the canon corpus *cannot* — that's the structural fact. The
interventions above split into:

- **#1 (CODE)** removes a calibration bug that is harming us *regardless*
  of corpus. The abstain-floor is over-triggering on trading verdicts.
- **#2 (SKILL)** improves the questions we *do* ask, so the canon corpus
  is used where it has an answer (weeks-to-months cycle position) rather
  than where it doesn't (12h direction).
- **#3 (SKILL)** scope-limits the product to questions Gecko can answer
  defensibly. The product's wedge is *grounded decline*, not coverage.

If forced to ship only one, ship **#1** before the contest. It is the
only one of the three where today's outputs would *measurably change*
inside the contest window without skill rewrites.

---

## What is explicitly out of scope

- **Anything > 4h of work.** Persona-prompt edits to the
  `technical_analyst` voice to re-add chart-reading would re-open the
  whole S24 WS-A redesign (the voice was intentionally reframed
  *away* from chart-reading in `_default_prompts.json` line 5). Out
  of contest-window scope.
- **Anything that touches `api.geckovision.tech`.** All three
  interventions above land on the skill side or in
  `packages/gecko-core/.../trade_panel/__init__.py` and are deployed
  through the normal release path. Intervention #1 is the only one
  that touches the production oracle's behavior, and it does so
  through the existing ship-gate.
- **Anything that needs an eval-suite run to validate beyond #115's
  existing N=50 fixture set.** That ship-gate exists; we reuse it.
- **Coordinator-prompt edits.** Per
  `feedback_prompt_iteration_plateau.md` — gpt-4o-mini rounds toward
  caution on any defer-related instruction. Every intervention here
  is either code-side or skill-side. Zero coordinator-prompt diffs.

---

## Honest contest-window-feasibility call

**Intervention #1 ships in the contest window.** ~1.5h to write +
~$5 to re-run the #115 ship-gate. If it passes 6/6, merge.

**Interventions #2 and #3 ship as part of the `gecko-trade-verdict`
skill** that the OKX contest plan (`#137`) is going to want anyway.
~3h combined. Not a panel change. Cannot regress the ship-gate
because it does not touch the panel.

**The honest answer on canon:** the canon corpus is doing exactly what
it was built to do (cycle-position framework). The wedge is intact. The
problem is that ~half of today's trade verdicts are being rewritten
`pass → defer` by a calibration rule designed for the yield vertical.
Fixing the calibration recovers ~half of the polls without touching the
corpus, the personas, or the wedge.
