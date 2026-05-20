# Panel Act-Rate on Momentum Spot — Diagnosis + Contest-Window Options (S39-#143)

**Mode:** read-only research brief. No code, no panel runs, no prompt edits,
no eval-suite spend. Time budget: ~30m. Companion to:
- `2026-05-19-skill-side-trading-improvements.md` (#139, the calibration-fix diagnosis at `6da037a`)
- `7c0ebed` — software-engineer's narrowing of `_ABSTAIN_TOKENS` (the deployed fix)
- `2026-05-19-trading-canon-one-source-feasibility.md` (#138, NO-GO on canon ingest)
- `2026-05-19-okx-contest-execution-brief.md` (#137, the contest plan)

**Scope question:** the OKX contest bot has Gecko gating every entry on
`act AND conf ≥ 0.6`. With the `7c0ebed` calibration fix deployed, the
JTO/JUP polls would emit `pass × 2` (not `defer × 2`) — but the gate still
fires zero trades because **`pass ≠ act`**. The brief asks whether **`act`
is structurally reachable** on a momentum spot question, and if not, what
the contest-window move is.

**TL;DR:** the panel is **structurally limited**, not tunable. The
`technical_analyst` voice has been intentionally reframed (S24 WS-A) as a
*macro_regime_analyst* — it reads cycle position from canon, not the
breakout. With no chart-reading voice, a momentum spot question on JTO
cannot ground `tech=bullish`, and the strategist's DEFAULT-ACTION MATRIX
in `_default_prompts.json` line 9 has **no row that produces an entry
action without `tech=bullish`**. The contest-window move is **option B —
drop Gecko from the gate path, keep it as a shadow ledger.** Intervention
#3 from `6da037a` (Class E routing) is the longer-arc fix.

---

## 1. Diagnosis: is the panel structurally unable to grade momentum spot?

### 1.1 What `act` requires

Tracing the act/pass/defer assembly in
`packages/gecko-core/src/gecko_core/orchestration/trade_panel/__init__.py`:

- The coordinator's verdict is a free emission, but `_count_dissent` at
  `:311` and `_count_abstains` at `:355` (post-`7c0ebed`) recount against
  the four primary analysts' closing-line tokens.
- An `act` survives the deterministic rewrites only when `dissent_count <
  3` (`:606`) and `abstains < 3` (`:618`) — the two override rules at
  `:638` and `:660` are gated on `pass` / `unacceptable` / rotation
  framing and do not affect an emitted `act`.
- For the coordinator itself to *emit* `act`, the panel's prior turns
  have to give it grounds. The coordinator prompt
  (`_default_prompts.json` line 11) defines `act = "the panel supports
  executing the strategist's intent now."` Translation: the strategist
  has to propose a concrete entry, and the panel has to back it.

### 1.2 What the strategist actually emits on momentum spot

The strategist's **DEFAULT-ACTION MATRIX** in `_default_prompts.json`
line 9 is the load-bearing table. The relevant rows for the JTO/JUP/PYTH
question class:

| technical | sentiment | fundamental | risk | default action |
|---|---|---|---|---|
| bullish | greed/neu | growing | acceptable | **open_long, normal size, weeks** |
| bullish | greed/neu | stable | acceptable | **scale_in, small size, weeks** |
| bullish | neutral | growing | elevated | **open_long, small size, tight stop, days** |
| bullish | fear | growing | acceptable | **scale_in, small size, weeks (contrarian)** |
| bearish | fear/neu | degraded | any | open_short OR observe |
| bearish | fear/neu | stable | acceptable | observe; close existing longs if any |
| bearish | greed | growing | acceptable | hold |
| **mixed** | any | any | any | **observe** |
| any | any | any | unacceptable | observe OR hold |

**Every row that produces an entry action requires `technical=bullish`.**
There is no row where `technical=bearish` or `technical=mixed` leads to
`open_long` / `scale_in`. The matrix is, by design, a tech-led framework.

So the question collapses to: **can the `technical_analyst` voice return
`bullish` on a JTO breakout question today?**

### 1.3 What the `technical_analyst` voice actually does

`_default_prompts.json` line 5 (the load-bearing persona prompt, also
visible verbatim in the JTO turn parsed-verdict at
`/tmp/gecko_demo_poll.json` line 19):

> *"You are the `macro_regime_analyst` on a trading research panel.
> (Voice name 'technical_analyst' is retained for envelope-shape
> stability; your job has been reframed.) … You characterize the
> prevailing MACRO REGIME for crypto risk assets — risk-on vs risk-off,
> volatility regime, credit-cycle phase, and where current conditions
> sit relative to historical analogues described in the canon corpus
> (Marks on cycle position, Damodaran on equity risk premium, Berkshire
> letters on credit conditions). **You do NOT read price charts, you do
> NOT call support/resistance levels, you do NOT name targets.**"*

The voice is structurally a cycle-position lens. The JTO turn at
`/tmp/gecko_demo_poll.json:19` shows the model doing exactly what the
prompt asks — it cites Marks on cycle-position and reads 2026 macro as
risk-off, returning `Trend verdict: bearish`. **There is no path from
"price broke 2h high with 1% confirmation" to a `bullish` regime call,
because the voice does not look at 2h highs.**

The matrix is therefore **closed against this question class**: there is
no voice in the panel whose job is to grade a breakout setup on its own
merits, and the matrix that would translate such a grade into an entry
intent does not exist either.

### 1.4 Is this a **canon limitation** or a **prompt limitation**?

It is *both*, but the proximate limitation is the **prompt**. The
`technical_analyst` reframe at S24 WS-A removed chart-reading on purpose
— the panel was, at that point, fabricating support/resistance levels
the canon could not ground (the S24 night-shift handoff doc covers this
in detail). The canon is value-investing literature; without chart
discipline, the model had been confabulating chart reads from prior
training. **Removing the voice was the right move at the time** — but
it left the panel with no organ for short-horizon directional grading.

Adding the voice back is a **canon limitation** in disguise: a
`chart_reader` persona without canon to ground against is
indistinguishable from prior-knowledge confabulation. That is the
S24 failure mode reified — and it would re-open the entire S24 WS-A
diagnosis (see §3 of `2026-05-19-skill-side-trading-improvements.md`).

### 1.5 The honest answer

**The panel cannot return `act` on a momentum spot question.** Not
"rarely returns" — *cannot*. Every path to `act` in the matrix requires
`tech=bullish`, and no voice in the panel grades a breakout setup on
its own merits. The expected `act`-rate on the contest's question
universe is **~0–5%** (interval), and the ~5% upper bound is
hallucination noise (a `technical_analyst` turn that breaks its own
prompt) — **not** signal we want.

---

## 2. One legitimate prompt/skill-side change — does it exist?

### 2.1 The answer is **no — none in the contest window.**

The change that would unlock `act` is *re-adding a chart-reading voice
to the panel*, and per §1.4 that re-opens the S24 WS-A reframe — the
voice would confabulate chart reads against canon that cannot ground
them. That is not a contest-window change; it is a v0.2 architectural
question (chart-reading persona + market_data corpus discipline + a
falsifiable eval that catches confabulation, none of which exist).

### 2.2 What about a horizon-anchored question (intervention #2 from `6da037a`)?

`6da037a` §2 proposed anchoring the idea string with explicit horizon
("Given a 7-day horizon and 1% sizing, does the panel see a thesis to
scale into JTO, or is this a no-trade?"). On further read, **this
intervention moves the verdict from `defer` to `pass`, not from `pass`
to `act`.** A horizon-anchored question still doesn't change what the
`macro_regime_analyst` reads (it reads cycle position regardless of
horizon), and so doesn't unlock the matrix's `tech=bullish` row. The
expected behavior shift is "stops defaulting to defer; emits a clean
decline" — which is what `7c0ebed` already accomplishes in code.
Intervention #2 is **not contest-window-feasible for `act`-rate**, only
for `defer`-rate, which `7c0ebed` already addressed.

### 2.3 What about tuning the strategist matrix?

A new matrix row like *"bearish | neutral | stable | elevated | scale_in,
small size, tight stop, days (counter-trend bounce)"* would technically
unlock `act` on JTO. **This is rejected as a wedge violation.** The
panel does not have a falsifiable counter-trend signal — adding a matrix
row that fires on no voice's positive grading is fabricating an `act`
out of mixed-to-negative reads, which is the exact behavior the abstain-
not-fabricate wedge exists to prevent. Per
`feedback_prompt_iteration_plateau.md`, gpt-4o-mini will not bind to
"counter-trend only" disciplines reliably; it will fire counter-trend
calls on noise. Cost: indeterminate prompt-tuning loop with no eval
suite that detects the failure mode.

### 2.4 Summary

**No legitimate prompt/skill-side change exists in the contest window
that moves the panel's `act`-rate on momentum spot from ~0–5% to ~30–40%
without burning the abstain-not-fabricate wedge.** This is the honest
"no" the brief flagged as the strongest answer. Skipping to §3.

---

## 3. Class E routing — is it the right answer?

### 3.1 Yes, structurally. But not as a contest-window unblock for trading.

Intervention #3 from `6da037a` proposed adding a Class E *out-of-scope*
route to the (future) `gecko-trade-verdict` skill: detect short-horizon
directional questions in the idea string and return a *decline*
envelope rather than running the panel and emitting `defer`. The
brief asks whether this is the right answer for `gecko_trade_research`
itself — i.e. the oracle MCP tool — not just the skill.

**It is.** Both:
- Class E is the structurally correct behavior because §1.5 says the
  panel *cannot* grade this question class. Running the panel + paying
  ~$0.10/call to emit `defer` is wasted spend on a verdict that does
  not move with corpus changes.
- Class E preserves the wedge — it is a *grounded decline* ("here's
  what Gecko's corpus does ground; here's what it does not") rather
  than the current behavior of running a value-investing panel against
  a momentum question and getting an indecisive answer.

### 3.2 Detection rule (spec, not code)

A momentum-spot question carries one or more of these markers in the
idea string, parseable cheaply at the skill or oracle entry:

| Marker class | Tokens |
|---|---|
| **Horizon tokens** | `1h`, `2h`, `4h`, `12h`, `24h`, `today`, `tomorrow`, `this week`, `next-N-hours`, `intraday`, `scalp`, `day trade` |
| **Setup tokens** | `breakout`, `breakdown`, `bounce`, `dip`, `pump`, `momentum`, `2h high`, `1h low`, `support`, `resistance`, `RSI`, `MACD` |
| **Question shape** | `should I open a long`, `should I buy now`, `entry now`, `is now a good time to enter` |

Rule: if **any horizon token OR ≥2 setup tokens** is present, route to
Class E. The rule should live in the **skill driver** (the future
`gecko-trade-verdict` SKILL.md), not in `gecko_trade_research` itself —
the oracle stays question-agnostic; the skill curates which questions
reach it. That keeps the oracle a primitive and Class E a product
shape.

### 3.3 Alternate output envelope

Rather than `verdict=defer`, Class E returns a distinct
`verdict=out_of_scope` envelope (or `decline`, lexically TBD) carrying:

```json
{
  "verdict": "out_of_scope",
  "scope_class": "short_horizon_directional_spot",
  "rationale": "Gecko's corpus is investor-canon literature (Marks/Damodaran/Berkshire/Mauboussin) — it grounds cycle-position reads on weeks-to-months horizons. Short-horizon breakout setups are outside its evidence base.",
  "in_scope_questions": [
    "weeks-to-months thesis on <token>",
    "deposit/yield decision on <protocol>",
    "regime context (risk-on vs risk-off) for crypto right now"
  ],
  "handoff_skills": ["kline-indicator", "okx-dex-market"]
}
```

The envelope shape is **load-bearing for the wedge story** — "the
oracle declines this class of question" is a product feature, not a
failure. It maps onto how `gecko-yield-verdict` already hands off to
`okx-defi-invest` when the user has decided. Per
`memory/project_kaas_positioning_2026_05_08`, declining out-of-scope
questions and pointing at the right tool is consistent with the KaaS
positioning, not against it.

### 3.4 What Class E does *not* do for the OKX contest

Class E is the right shape for `gecko-trade-verdict` as a product. **It
does not produce more `act` verdicts.** The contest bot's gate
(`act AND conf ≥ 0.6`) sees `out_of_scope` and treats it as not-`act`,
identical to a `defer` or `pass`. **Class E is the structurally correct
v0.2 fix; it is not a contest-window `act`-rate unblock.**

If the contest bot still wants to fire trades, the gate path itself has
to change — not the oracle's output.

---

## 4. Contest-window decision recommendation

### 4.1 Three options, evaluated

#### Option A — Run the current Gecko-gated bot, accept ~0 trades, lean into the abstain artifact

- **What ships:** the contest bot at `contest_bot/onchainos.py` with the
  Gecko wrap layer from `4803ac5`. Gecko gates every entry on
  `act AND conf ≥ 0.6`. Expected outcome on 30h of momentum-spot
  questions: ~0–1 entries, near-zero realized PnL, no Participation
  Reward gate cleared ($1,000 cumulative volume required).
- **Contest payout expectation:** $0. The contest's mechanic is realized
  PnL on closed trades; zero trades = zero PnL.
- **Story:** "the abstain is the wedge. Gecko correctly declined to
  trade on N momentum-spot questions where the value canon had nothing
  to say." This is the artifact `2026-05-19-trading-canon-one-source-feasibility.md`
  §4 contemplated (Path B shadow ledger), but here Gecko is in the
  *trade path*, not the shadow ledger. That makes the abstain story
  weaker — "we ran a bot that didn't trade" is harder to defend than
  "we ran a bot and Gecko commented on every entry."
- **Risk:** the Skill Quality rubric (per
  `2026-05-19-okx-skill-quality-feasibility.md`) rewards *demonstrated*
  use of Gecko's wedge. A bot with zero trades does not demonstrate
  anything — it demonstrates that the gate fires negative on every
  question, which is also achievable with `verdict_gate = lambda x:
  False`. The narrative is too thin.

#### Option B — Drop Gecko from the gate path, keep it as a shadow ledger

- **What ships:** the same bot, but `verdict_gate` becomes a no-op
  (always allow entry). Gecko's verdict runs in parallel via the
  artifact logger and writes a `verdicts/` JSON per attempted entry —
  **never blocks the trade**. The bot fires whatever the baseline
  signal says (the JTO breakout heuristic in `contest_bot/onchainos.py`).
- **Contest payout expectation:** baseline. The bot trades on its
  breakout signal, eats the OKX fees+slippage, and either does or
  doesn't clear $1,000 cumulative volume (Participation Reward gate)
  in 7 days. EV math is in `2026-05-19-okx-contest-ev-analysis.md`;
  the founder priced this as the most realistic path.
- **Story:** "Gecko's value-investing canon correctly identifies that
  it cannot ground short-horizon momentum spot — so we ran the bot
  on a separate baseline signal AND logged what Gecko *would have*
  said. The shadow ledger shows Gecko abstained on M of N entries; on
  the N entries the bot took, Gecko's defer rate was X%, its pass rate
  was Y%, its act rate was Z%. This is the principled call to *not*
  put Gecko in the trade path for spot momentum questions — and the
  abstain shape itself is the wedge artifact."
- **Risk:** the contest's Skill Quality rubric values *Gecko's role* in
  the trading agent. A shadow ledger is still a role — it is
  observational, not gating — but the founder needs to write the
  submission narrative honestly: "Gecko's role here is to ground
  decline; it correctly did not gate trades on a question class outside
  its corpus."

#### Option C — Apply a prompt/skill change from §2 if one exists, then re-poll

- **What ships:** the §2 conclusion was that **no legitimate change
  exists** that moves `act`-rate from ~5% to ~30-40% without burning
  the wedge. Option C is **not available.**
- If the founder overrides and ships intervention #2 (horizon-anchored
  questions) anyway, the expected behavior shift is `defer → pass`,
  not `pass → act`. The gate still fires zero trades.
- **Reject.**

### 4.2 Recommendation: **Option B — drop Gecko from the gate, keep it as a shadow ledger.**

The case, four lines:

1. **Honest.** Per §1.5, the panel cannot grade this question class.
   The shadow ledger is the job it *was* built for.
2. **Preserves the wedge.** Each shadow-ledger entry carries per-voice
   reads + verdict + abstain/dissent recount — exactly what the OKX
   Skill Quality rubric scores on.
3. **Funds the contest.** Without Gecko in the gate, the bot has a
   non-zero shot at Participation Reward; with Gecko in the gate, the
   expected shot is ~0.
4. **Compounds into v0.2.** The shadow-ledger data is the empirical
   input for Class E's detection rule (§3.2) — going in *without*
   Class E preset is the right move; tuning it on n=3 polls is the
   small-N variance failure mode.

The single contest-window code change is a one-line flip in
`contest_bot/onchainos.py` — verdict gate → observe-only — while the
artifact logger from `4803ac5` keeps writing per-entry verdicts. **No
oracle change. No prompt change. No ship-gate re-run.** Cost: ~10 min.
Risk to wedge: zero; the wedge is *strengthened* by the principled-
decline framing.

### 4.3 What about Class E (intervention #3) for the contest?

**Intervention #3 is the v0.2 fix, not the contest-window fix.** Class E
is a multi-file skill change (skill driver + envelope shape + handoff
catalog) that wants empirical detection-rule tuning against the
contest's actual question distribution — which we only have *after*
the contest, not before. Shipping Class E pre-contest means tuning the
detection rule on the JTO/JUP/PYTH polls (n=3, no statistical power)
which is exactly the small-N variance failure mode AI/ML owns
diagnosing.

Ship Class E in S40 after the contest, with the shadow-ledger data as
the detection-rule input. The contest itself runs on Option B.

---

## 5. Report-back summary

- **Diagnosis:** the panel is **structurally limited**, not tunable.
  The strategist DEFAULT-ACTION MATRIX has no entry-action row without
  `tech=bullish`, and the `technical_analyst` voice has been
  intentionally reframed (S24 WS-A) as a `macro_regime_analyst` that
  reads cycle position, not breakouts. Every path to `act` requires a
  voice we deliberately removed.
- **Contest-window recommendation:** **Option B** — drop Gecko from the
  contest bot's gate path, keep it running as a shadow ledger via the
  artifact logger from `4803ac5`. Cost: ~10 min code change. Risk to
  the wedge: zero (strengthens it via principled-decline framing).
- **Interventions from `6da037a`:** **#2 is not contest-window-feasible
  for `act`-rate** (it moves `defer → pass`, not `pass → act`). **#3
  (Class E) is the right v0.2 fix** but should ship in S40 with the
  contest's shadow-ledger data as the empirical detection-rule input,
  not pre-contest on n=3 polls.
- **Biggest blocker not on your radar:** the `7c0ebed` calibration fix
  is **already deployed** and the JTO/JUP polls (captured ~30 min
  *before* the commit at `/tmp/gecko_demo_poll.json`) will read
  differently on re-run. The current polls are stale. A clean re-run
  on the same three tickers would land at `pass × 2 + defer × 1` (JTO
  pass, JUP pass, PYTH defer-via-Rule-1). **The bot's gate still fires
  zero entries** — because the structural issue isn't `defer` vs `pass`;
  it's that **`act` is unreachable** regardless of which non-`act`
  verdict the panel emits. This is the framing shift the brief is
  asking for: the question is not *"how do we reduce defer-rate"*,
  it is *"is `act` reachable at all"*, and the answer is no on this
  question class with this corpus.
