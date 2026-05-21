# Gecko — First-Deliverable Roadmap (M0 → M7, S40 → S44)

**Date:** 2026-05-20 · **Owner:** `business-manager` (with `staff-engineer`
arbitration on lane-crossing items). **Status:** opinionated draft, founder
review pending. **Mode:** source-of-truth for the next 4–6 weeks; supersedes
the S40 plan stub at `docs/superpowers/plans/2026-05-19-s40-plan.md` (`fd082c8`)
for cross-sprint sequencing.

This is the doc the next ten sprint plans answer to. It is not the PRD —
the PRD does not exist yet (`docs/PRD.md` is empty). When the PRD lands, it
inherits the first-deliverable definition from §1 of this doc and nothing
else.

**Companion docs (read in order if you have 30m):**

- `docs/strategy/2026-05-20-contest-fire-rate-retune.md` (`f62a17e`) — what the contest exercise actually measured.
- `docs/strategy/2026-05-20-panel-act-rate-on-momentum-spot.md` (`e70184d`) — the architectural finding the contest surfaced.
- `docs/strategy/2026-05-19-okx-complement-map-s38-plan.md` — the OKX-as-distribution-channel thesis.
- `docs/strategy/2026-05-19-backtesting-scoping-plan.md` — the trust-instrument workstream.
- `memory/project_2026_05_18_session_endstate.md` — the arc S37 → S39 endstate.

---

## 1. The first-deliverable definition

**Recommendation, one paragraph:** the first commercial deliverable is **one
paid skill published on a public marketplace that strangers can install and
pay for, backed by the live `gecko-yield-verdict` oracle endpoint.** Skill
ships first; supporting trust instruments ship alongside. Everything else
this roadmap describes is in service of that ship.

**Operational decomposition:**

- One skill: `gecko-yield-verdict` (built, end-to-end-verified, vertical-bug
  fixed at `796446e`). The "should I deposit?" complement to
  `okx-defi-invest`. Pre-existing artifact at
  `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/gecko-yield-verdict/SKILL.md`.
- One marketplace: `okx/onchainos-skills` Path A merge request (MIT
  SKILL.md, oracle endpoint stays Gecko-owned + off-repo).
- One backing oracle: `api.geckovision.tech/trade_research`, the verified
  S37 6/6 ship-gated endpoint, `X402_MODE=stub` today (`$0` per call to the
  caller; we eat infrastructure cost out of pocket until the flip).
- One trust instrument: the S37 ship-gate scorecard already published
  inline + the Phase 1 backtest's leakage probe (live).
- One pricing decision: **🛑 FOUNDER DECISION** — Stub-mode-paid (free
  for now, advertise the $0.25 USDC settle price as the live price) vs
  flip-to-live before publish.

**Map to the synthesis frame:** this is M1 (the first published skill) +
M2 (the first verified verdict run by a stranger) + M7 (a backing oracle
people can pay for). M3–M6 are the panel-architecture build-out, the
forward-track-record start, and the second skill — each shippable on its
own.

**Target date interval:** publish between **2026-05-26 and 2026-06-09**
(7–21 calendar days from today). The Path A merge timeline is the
load-bearing unknown — Gecko-side work is ~3 dev-days; OKX-side review is
unmeasured. The interval is wide on purpose.

**What "first commercial deliverable" does NOT mean:**

- An app launch. There is no `app.geckovision.tech` consumer flow in this
  roadmap.
- A marketplace of skills. **Gecko is the KaaS oracle, not a marketplace**
  (`memory/project_kaas_positioning_2026_05_08`). The oracle is sold per
  call; the skill is one distribution channel.
- A live x402 settlement layer for the first ship. Stub-mode is
  intentional (`memory/project_x402_stub_then_live`). Flipping live is a
  separate, founder-gated event.
- A polished UI. The skill is markdown + a verdict envelope rendered as
  text.

---

## 2. What we learned from the OKX contest exercise

The honest list. Not the marketing list.

**Headline learning — the panel-architecture gap (`2026-05-20-panel-act-rate-on-momentum-spot.md`):**

- The trade panel **cannot return `act` on a short-horizon momentum spot
  question.** Every entry-action row in the strategist DEFAULT-ACTION
  MATRIX requires `tech=bullish`, and the `technical_analyst` voice was
  reframed at S24 WS-A as a `macro_regime_analyst` that reads cycle
  position, not breakouts. There is no voice in the panel whose job is to
  grade a 2h-breakout setup on its own merits. This was a *correct* design
  decision when made (the original `technical_analyst` confabulated
  support/resistance levels with no canon to ground them) — but it left
  the panel structurally closed against the contest's question class.
- The implication is bigger than the contest. **Any question class that
  needs "chart reads," "smart-money flow," "position memory," or
  "portfolio fit" is currently out of scope for the oracle.** That is the
  ceiling we hit. It's the explanation for the S37 ship-gate's narrow
  question profile and for why `gecko-yield-verdict` works (yield
  decisions are exactly what canon literature grounds densely).

**Sub-learning — the contest fire-rate math (`2026-05-20-contest-fire-rate-retune.md`):**

- Modal 24h fire-rate on the current spec is **~2.5%, interval [1%, 7%]**.
  The founder's 4% back-of-envelope was at the upper end of the modal
  band on a 12h window.
- No retune option in the available 30h window pushes fire-rate to
  30–50% without burning the wedge. The retune trilemma (loosen entry
  primitive vs loosen gate vs multi-instrument) has no costless corner.
- The recommendation `trading-strategist` made — **accept zero trades,
  ship the pre-registered defer-only ledger as the artifact** — is the
  right call for the contest. The shadow-ledger run on Option B
  (`2026-05-20-panel-act-rate-on-momentum-spot.md` §4.2) is the cleaner
  artifact for the first-deliverable story.

**Sub-learning — what the contest was actually for:**

- Per `memory/feedback_okx_no_funding_pressure` and the EV math
  (`docs/strategy/2026-05-19-okx-contest-ev-analysis.md`), dollar EV at
  $100 capital is **+$3 mean ± $7 CI** under Posture A. **The artifact +
  the Jen receipt are the return, not the dollars.** Contest dollars are
  rounding error.
- The contest is one *cycle of a repeatable measure* — not a one-shot
  proof. A clean defer-only run is a clean data point in the
  forward-track-record trend; a noisy retuned run pollutes that trend's
  first cycle.

**What the contest exercise did NOT validate:**

- The forward immutable track record (zero settled trades in the gated
  arm — we don't have an entry-decision dataset, we have a non-entry
  dataset).
- The live x402 settlement path (stub-mode throughout).
- Multi-protocol generalization (single instrument, single class of
  question).

**What it DID validate:**

- The oracle calls work end-to-end against `api.geckovision.tech` in stub
  mode at scale (the contest bot polled JTO every 30s and got verdicts
  back on demand).
- The 5-min cache and the hourly circuit breaker behave as designed.
- The abstain-not-fabricate wedge is **structurally honest** — the panel
  declined every question it could not ground, and the architectural
  diagnosis we built around that decline is *defensible engineering*,
  not motivated reasoning.

---

## 3. Milestone ladder M0 → M7

Each milestone is a verifiable artifact. Owner = engineering lane that
unblocks the next milestone. Status notation: ✓ done · ◐ in-progress · ☐
unstarted.

| # | Milestone | Owner | Unblocks | Status | Note |
|---|---|---|---|---|---|
| **M0** | S37 6/6 ship-gate verified, oracle deployed live | `ai-ml-engineer` + `devops-engineer` | M1, M2, M7 | ✓ | `7c0ebed` calibration fix + S37 6/6 N=57 at `6fe841e`. Deployed via `./infra/deploy.sh`; `api.geckovision.tech/trade_research` live. |
| **M1** | `gecko-yield-verdict` published as a paid skill on a public marketplace | `business-manager` + `ai-ml-engineer` (skill copy) | M2 | ◐ | Skill built + vertical-bug-fixed at `796446e`. Path A MR not yet filed. Needs SKILL.md x402-correction (the demo flow's stub-dance docs) + a security-scan pass via `skill-guard`. |
| **M2** | First verified non-Gecko-employee run of the skill produces a verdict | external user / Jen at OKX | M3 (validates the panel before extending it) | ☐ | Counts a Path A MR review run + a marketplace install + a public X post + a Jen forwarding it internally — any of those four. |
| **M3** | Panel persona expansion #1 — `chart_analyst` ships | `ai-ml-engineer` | M4, future skills outside yield | ☐ | Adds the `tech=bullish/bearish/neutral/no-setup` seed the matrix needs. Reads OHLCV via `okx-dex-market`. **Re-opens the S24 WS-A confabulation risk** — landed only with a falsifiable eval per the AI/ML caution below. |
| **M4** | Forward immutable track record live | `software-engineer` + `data-engineer` | M6 (turns the track record into a buyer-facing trust claim) | ☐ | A public JSONL of every verdict + timestamp + outcome, signed, append-only. The bulletproof trust instrument per the backtest scoping plan §6. The contest's artifact log (`contest_bot/artifact_YYYYMMDD.jsonl`) is the seed for this. |
| **M5** | Panel persona expansion #2–#4 — `smart_money_voice`, `memory_voice`, `portfolio_voice` | `ai-ml-engineer` + `data-engineer` (memory infra) | broader question coverage, second skill | ☐ | Each is a separate ship; the order is in §5. Each one is gated on a falsifiable eval that catches confabulation. |
| **M6** | First paying caller pays a non-stub x402 settlement | `web3-engineer` | the revenue line | ☐ | The X402 flip from `stub` to `live` (`memory/project_x402_stub_then_live`). Founder-gated. Pricing decision precedes the flip. |
| **M7** | Second skill ships (the second distribution channel) | `business-manager` + `ai-ml-engineer` | "the oracle is a product, not a skill" | ☐ | Default candidate: `gecko-pool-due-diligence` (a longer-form sibling to `gecko-yield-verdict`, still in the yield vertical). Bigger jump = `gecko-token-due-diligence` (asks the panel about a token thesis), which requires M3 (`chart_analyst`) shipped first. |

**Reading the ladder:**

- M0 → M1 → M2 is the **revenue-validation spine** — does the wedge get a
  stranger to install + pay (today: stub-pay) for a Gecko verdict? Until
  M2, every milestone after is speculative.
- M3 → M5 is the **panel-architecture build-out**. It is the engineering
  lane the contest exercise told us is the next-largest gap.
- M4 + M6 are the **trust + commerce instruments**. M4 makes the wedge
  durable past skill discovery; M6 makes it a business.
- M7 is the **proof that the oracle is reusable**. One skill is an
  artifact; two skills is a product.

**The shortest path to first deliverable is M0 ✓ → M1 → M2.** Three
milestones; two of them not yet done; first-deliverable date is the day
M2 fires.

---

## 4. Sprint sequence S40 → S44

Five sprints. Each sprint has a goal, a scope, and an *if-we-stop-here*
test. If the sprint cannot answer "if we ship ONLY this sprint and stop,
is it shippable?" with a yes, the sprint is too big.

### S40 — `gecko-yield-verdict` to published, panel untouched

**Goal:** M1 ships. The skill is in `okx/onchainos-skills` (or marketplace
equivalent) under MIT, callable end-to-end against the live oracle by
anyone who installs it.

**Scope:**

1. SKILL.md correction for the x402 stub-dance documentation
   (`memory/project_2026_05_18_session_endstate.md` — the SKILL.md falsely
   claims stub mode means "no 402 handshake"; the real client still does
   the dance and posts a stub-signature payment).
2. `skill-guard` scan + remediation. Installed at
   `~/.claude/skills/skill-guard/` per the session endstate; not yet run
   against this skill.
3. Path A MR prep: frontmatter conformance to the
   `okx/onchainos-skills/REVIEWING.md` checklist, ~500-line cap on the
   SKILL.md, references move to `references/`.
4. Founder-gated submission: MR filed, or marketplace publish flow
   confirmed (the marketplace publisher console is unknown territory —
   see §7).
5. One live demo run by a non-Gecko-employee (Jen counts as the easiest
   first dogfood per `feedback_dogfood_loop`).

**Out of scope this sprint:** panel-persona expansion, backtest Phase 2/3
implementation, x402 live flip, web app changes.

**If we ship ONLY this sprint:** yes — M1 + a partial M2 (the Jen run).
This is the cleanest single-sprint shippable.

**Deferred to S41:** anything that touches the panel itself; backtest
Phase 2 reconstruction code; a second skill.

### S41 — `chart_analyst` voice + the falsifiable eval that gates it

**Goal:** M3 ships. The panel gains a chart-reading voice with a
ship-gate that *catches* confabulation (the failure mode that motivated
S24 WS-A removing the original `technical_analyst`).

**Scope:**

1. `chart_analyst` persona prompt — reads OHLCV via the `okx-dex-market`
   API. Outputs `setup_quality: bullish/bearish/neutral/no-setup` + a
   one-sentence rationale grounded in the actual candles, not invented
   levels.
2. Falsifiable eval — N≥20 candles fixtures with *known* setups (some
   real, some scrambled/random); voice must classify the random ones as
   `no-setup`. Below a threshold = voice does not ship. Pattern E
   reachability probe per CLAUDE.md.
3. Strategist DEFAULT-ACTION MATRIX update — add the row that maps
   `tech=bullish` (from `chart_analyst`) into entry intents.
4. Re-run S37 ship-gate on the expanded panel. Six dimensions, N=50, CI
   thresholds unchanged.
5. Dogfood: pull a fresh `gecko-yield-verdict` verdict on a pool the
   chart now sees, compare pre/post.

**Out of scope:** the other three personas (M5 work), portfolio agent,
mixed-strategy execution.

**If we ship ONLY this sprint:** yes — M3 ships with a single
chart-reading voice and a ship-gate that says "this is now in scope," and
the existing skill quietly gets stronger.

**Deferred to S42:** `smart_money_voice`, `memory_voice`,
`portfolio_voice`.

**AI/ML caution to honor:** per `feedback_prompt_iteration_plateau`,
gpt-4o-mini rounds toward caution on defer-related instruction. The
`chart_analyst` prompt's defer condition needs to be **encoded in code
post-emission, not in prompt language.** The persona emits a structured
field; deterministic code in the panel orchestrator decides what counts
as `no-setup`.

### S42 — Forward immutable track record (M4) + `smart_money_voice` (M5 part 1)

**Goal:** M4 ships. M5 is half-built.

**Scope:**

1. Public JSONL of every verdict the live oracle produces, append-only,
   signed (a per-day Merkle root committed to a public GitHub branch or
   on-chain). The contest's `artifact_YYYYMMDD.jsonl` is the schema seed.
2. Outcome attribution — for verdicts that *can* be resolved (a yield
   pool's APY/TVL N days later), append the outcome row to the same
   ledger.
3. `smart_money_voice` persona — reads `okx-dex-signal`'s smart-money
   buy/sell tags. Output:
   `smart_money_state: accumulating/distributing/neutral`. Same
   falsifiable-eval discipline as `chart_analyst` (the eval is harder:
   smart-money signal noise is high).
4. **🛑 FOUNDER DECISION** — public ledger storage venue (GitHub repo vs
   IPFS vs Arweave vs Walrus). Default: GitHub repo + per-day Merkle root
   to a Solana memo tx. Cheap, dirty, transparent.

**If we ship ONLY this sprint:** yes — M4 ships standalone; the
`smart_money_voice` ships behind a feature flag until S43's eval lands.

**Deferred to S43:** `memory_voice`, `portfolio_voice`, the X402 flip,
the second skill.

### S43 — `memory_voice` + `portfolio_voice` (M5 complete)

**Goal:** M5 complete. The panel has its four-voice expansion.

**Scope:**

1. `memory_voice` — reads `verdict_history` + `outcome_history` +
   derived `lessons_db`. Output:
   `prior_signal: confirms/contradicts/novel`. Mongo-backed; the
   architecture in `memory/project_2026_05_18_session_endstate` synthesis
   block.
2. `portfolio_voice` — reads the caller's open positions (from
   `okx-defi-portfolio` or the caller-supplied position list).
   Output: `position_state: room/saturated`.
3. Eval for both, same shape as S41/S42 evals.
4. Strategist matrix expansion to consume `prior_signal` +
   `position_state` as inputs (lower confidence on a `novel + saturated`
   combo, raise on `confirms + room`).
5. S37 ship-gate re-run on the full seven-voice panel (the original
   four + `chart_analyst` + `smart_money_voice` + `memory_voice` +
   `portfolio_voice` = seven; the `coordinator` is not counted as a
   voice). Six dimensions, N=50 minimum.

**If we ship ONLY this sprint:** yes — M5 ships; the oracle is now
broadly capable; the second skill (M7) is unblocked.

**Deferred to S44:** X402 flip, second skill, partner integrations.

### S44 — X402 flip + second skill in flight

**Goal:** M6 ships. M7 starts.

**Scope:**

1. Pricing decision finalized (single price point or tiered? see §7).
2. X402 flip ceremony: stub → live on `api.geckovision.tech`. Per
   `memory/project_x402_stub_then_live`, this is a discrete event with
   pre-flip + post-flip checklist; `web3-engineer` owns the operation.
3. Funded operator buyer wallet for first-call demos
   (`memory/project_buyer_wallet_blocker_2026_05_08` lays out the 4
   steps).
4. Second skill in flight — `gecko-pool-due-diligence` or
   `gecko-token-due-diligence`, depending on M3 panel readiness.

**If we ship ONLY this sprint:** yes — M6 fires; the oracle has its
first paying call (even if the second skill slips to S45).

**Deferred to S45+:** mixed-strategy portfolio agent v2 (the
`StrategyPortfolio { strategies, allocator, risk_manager, execution }`
shape lives outside the first-deliverable scope, per `memory/project_trade_vertical_v01_decisions_2026_05_11`).
Multi-vertical sweeps. Web app.

---

## 5. Personas to add to the panel

The four-voice expansion. Order, dependencies, why this order.

### 5.1 The order — `chart_analyst → smart_money_voice → memory_voice → portfolio_voice`

| # | Voice | Sprint | Reads | Outputs | Unlocks |
|---|---|---|---|---|---|
| 1 | `chart_analyst` | S41 | OHLCV via `okx-dex-market` | `setup_quality: bullish/bearish/neutral/no-setup` | The matrix's `tech=bullish` rows — any entry action |
| 2 | `smart_money_voice` | S42 | `okx-dex-signal` smart-money tags | `smart_money_state: accumulating/distributing/neutral` | A second independent confirmation channel; counters the `coordinator-only-confirmation` failure mode |
| 3 | `memory_voice` | S43 | `verdict_history` + `outcome_history` + `lessons_db` | `prior_signal: confirms/contradicts/novel` | Cross-call learning; the wedge against Perplexity/ChatGPT (`memory/project_wedge_wire_path_b` Pattern D) |
| 4 | `portfolio_voice` | S43 | caller-supplied positions | `position_state: room/saturated` | Position-aware verdicts; the precondition for an autonomous trade agent |

### 5.2 Why this order — recommendation first, rationale second

**Recommendation:** ship `chart_analyst` first.

**Rationale:**

1. **Highest leverage on the existing question profile.** Yield decisions
   already work; momentum spot (the contest's class) is the explicit gap.
   `chart_analyst` is the *one* persona that, by itself, opens the gap.
   The other three personas enrich existing answers but don't open
   new question classes.
2. **Lowest data-dependency.** OHLCV is a free `okx-dex-market` call.
   `memory_voice` requires a Mongo `verdict_history` collection (new
   infra). `portfolio_voice` requires position data the caller may or
   may not have. `smart_money_voice` requires `okx-dex-signal`'s
   smart-money tagging (live but signal-noise-heavy).
3. **Tightest failure-mode containment.** The S24 WS-A confabulation
   failure has a known eval shape (give the voice scrambled candles,
   assert it returns `no-setup`). We have lower-confidence eval shapes
   for the other three.
4. **Smallest matrix change.** Adding `chart_analyst` is one new voice +
   one new matrix input. Adding `memory_voice` and `portfolio_voice`
   simultaneously is two new voices + matrix changes that interact, and
   we don't have evals for the interactions.

### 5.3 The AI/ML caution

Per `memory/feedback_prompt_iteration_plateau` and the S24 night-shift
diagnosis: **gpt-4o-mini rounds toward caution on any defer-related
instruction in a prompt.** That observation generalizes to *any
classification-with-an-uncertainty-class* prompt — including
`setup_quality: ... no-setup`.

Operationally:

- **The voice prompt emits a structured classification.** It does *not*
  contain "if uncertain, prefer no-setup" instructions in natural
  language.
- **Deterministic post-emission code in the panel orchestrator decides
  what counts as uncertain.** Confidence below threshold, or any field
  set to `null`, or any model output that fails to parse, becomes
  `no-setup` in code. This is the same pattern as `_count_abstains` and
  `_count_dissent` in `trade_panel/__init__.py`.
- **The eval drives the threshold, not vibes.** N≥20 candle fixtures
  per voice, half real + half scrambled; threshold tuned so scrambled
  candles classify as `no-setup` ≥90% of the time and real setups
  classify as their true class ≥80% of the time.

If the eval can't hit those numbers, the voice does not ship. We do not
iterate on the prompt past 4 cycles (per
`feedback_prompt_iteration_plateau`, prompt iteration plateaus).

### 5.4 Standing caution — the canon-grounding problem

`chart_analyst` reads charts, not canon. So does `smart_money_voice`.
Two voices now run *without* canon citations. The wedge story
("grounded adversarial verdict, citation-bound") gets thinner if half
the voices don't cite anything.

**Resolution:** the **citation surface stays anchored to the existing
canon-reading voices** (the macro_regime_analyst, fundamental_analyst,
risk_manager, sentiment_analyst, strategist). `chart_analyst` and
`smart_money_voice` contribute **observation rows**, not citations. The
verdict envelope distinguishes `cite_count` (canon-grounded) from
`observation_count` (chart/smart-money raw reads). Buyers see both. The
wedge holds: *we cite when we have basis, we observe when we have
data, we abstain when we have neither.*

---

## 6. OKX skills inventory — adopt vs learn-from vs ignore

Refined from the synthesis. Source: `okx/onchainos-skills` SKILL.md + the
ones already installed locally; `2026-05-19-okx-complement-map-s38-plan.md`
has the full teardown.

| OKX skill | Verdict | Sprint | Why |
|---|---|---|---|
| `okx-defi-invest` | **Adopt — handoff** | S40 (already wired in `gecko-yield-verdict`) | The first skill's hand-off target. Already in the SKILL.md routing. |
| `okx-dex-market` | **Adopt — data feed for `chart_analyst`** | S41 | OHLCV. Free read. The data the new voice depends on. |
| `okx-dex-signal` | **Adopt — data feed for `smart_money_voice`** | S42 | Smart-money buy/sell. Free read. |
| `okx-dex-ws` | **Adopt — for live streaming when M4 needs it** | S42 | If the immutable track record streams resolutions live, ws is the path. Lower priority — replay is fine first. |
| `okx-defi-portfolio` | **Adopt — data feed for `portfolio_voice`** | S43 | Open positions. Free read. |
| `okx-security` | **Adopt — for safety tag enrichment + skill-guard parity** | S43 | Future skills (token DD) need safety tags. Lower priority for the first deliverable. |
| `okx-agent-payments-protocol` | **Adopt (as buyer) — for the M6 X402 flip** | S44 | The x402 spec OKX runs. The live flip ceremony validates against this. |
| `okx-agentic-wallet` | **Adopt — deeper integration when M6+ lands** | S44+ | Once paying callers exist, the wallet UX matters. |
| `starter-coach` | **Learn-from — DO NOT fork wholesale** | n/a | The 6,875-line precedent. The shape of a successful skill. We fork ideas, not code. |
| `okx-dex-swap` | **Learn-from — the highest-leverage complement** | future skills | The "should I swap?" verdict skill is the natural second skill *after* `chart_analyst` ships. M7 candidate. |
| `okx-dex-strategy` | **Ignore for first deliverable** | n/a | Limit-order placement. Higher-complexity hand-off. |
| `okx-dex-trenches` | **Ignore for first deliverable** | n/a | Meme launches. The corpus's *thinnest* coverage. Wrong place for the second skill. |
| `okx-dex-social` | **Ignore for first deliverable** | n/a | Sentiment is already a panel voice; no separate skill needed. |
| `okx-dex-token`, `okx-dex-bridge`, `okx-onchain-gateway`, `okx-audit-log`, `okx-dapp-discovery`, `okx-growth-competition`, `okx-how-to-play` | **Ignore for first deliverable** | n/a | Infra / meta / one-off. Re-evaluate at M7. |

**Distribution channel posture:** publish to `okx/onchainos-skills` first
(Path A, MIT, OKX co-sign). The marketplace (Path B) is unknown territory
(undocumented publisher onboarding); leave it for later. Per
`memory/project_kaas_positioning_2026_05_08`, **Gecko is not a
marketplace** — we publish *on* marketplaces, we don't build one.

---

## 7. Decision points that need founder calls

The explicit founder-decision queue. Each item blocks at least one
specific sprint.

1. **🛑 FOUNDER DECISION — pricing for the first paid call.** Default:
   $0.25 USDC per call (the existing x402 advertised price). Alternatives:
   $1.00 per call (signals premium), $0.10 per call (signals volume play),
   tiered ($0.25 basic + $5 with the full panel dissent breakdown). **Blocks
   M6 / S44.** Per `business-manager` operating principles, session pricing
   only — no per-feature add-ons. One price for the first call.
2. **🛑 FOUNDER DECISION — Path A vs marketplace for M1.** MR into
   `okx/onchainos-skills` (MIT, OKX co-sign, review gate, slower) vs OKX
   Skills Marketplace (no review, unknown publisher onboarding, faster).
   Default: Path A. **Blocks S40 final ship.**
3. **🛑 FOUNDER DECISION — X402 flip authorization.** The stub →
   live ceremony per `memory/project_x402_stub_then_live`. **Blocks M6 /
   S44.** Cannot proceed without explicit founder go-ahead.
4. **🛑 FOUNDER DECISION — first-deliverable date commitment.** The
   §1 interval is 2026-05-26 to 2026-06-09. The founder picks the target
   date inside that interval. **Blocks S40 sequencing.** If the date is
   2026-05-26 (next Tuesday), S40 is a one-week sprint; if 2026-06-09,
   S40 has room for the SKILL.md polish + a security scan loop.
5. **🛑 FOUNDER DECISION — public track record storage venue.** GitHub
   repo + Solana memo tx Merkle roots vs IPFS vs Arweave vs Walrus.
   **Blocks M4 / S42.** Cost / permanence / read-cost trade-off.
6. **🛑 FOUNDER DECISION — single-skill or multi-skill first deliverable?**
   §1 default = single (`gecko-yield-verdict`). The case for multi-skill:
   the wedge story reads stronger when two skills share a backing oracle
   ("the oracle is reusable"). The case against: M7 is a separate
   milestone for a reason — we don't have two skills' worth of confidence
   in any *one* of them until M2 fires. **Default: single skill first;
   second skill is M7.**
7. **🛑 FOUNDER DECISION — voice order if §5.2 is wrong.** Default:
   `chart_analyst` first. Alternative: `memory_voice` first (the
   cross-call wedge against Perplexity). The founder reads §5.2 and picks.

---

## 8. What's explicitly out of scope for the first deliverable

Pin these. Every "we should also..." goes here until §1 ships.

- **Portfolio agent v2.** The `StrategyPortfolio { strategies, allocator,
  risk_manager, execution }` shape from
  `memory/project_trade_vertical_v01_decisions_2026_05_11` is a v0.2
  product. Not in the M0–M7 ladder.
- **Multi-protocol sweeps.** First deliverable is one skill, one yield
  vertical. The cross-protocol "verdict on every pool I hold" feature is
  M7+.
- **Custom UI / web app.** No `gecko-mcpay-app` changes are on the
  critical path. The web app's install-flow updates (the cross-repo
  uncommitted work from `memory/project_2026_05_18_session_endstate`)
  can land independently; nothing here blocks on them.
- **Backtest as headline trust claim.** Per the backtest scoping plan §6,
  the backtest is the **fast directional companion** to the forward
  track record (M4) — never the standalone headline. The first
  deliverable rides the S37 ship-gate scorecard + the live oracle, not a
  backtest number.
- **In-house backtesting infrastructure beyond Phase 1 of the existing
  workstream.** Per `memory/project_ownership_tier_strategy_2026_05_16`,
  backtesting belongs to partner integrations, not in-house builds. Phase
  2/3 of the existing backtest scoping is *for the trust benchmark*, not
  a product feature.
- **Trading agent v2 / contest bot v2.** The contest bot is the $0 proof
  artifact (`memory/project_ownership_tier_strategy_2026_05_16`). It is
  not on the revenue line.
- **Security audit / formal verification of the panel logic.** Trail of
  Bits-style skill auditing is available (the `trailofbits/` skills are
  installed) and worth doing pre-M6, but it's a partner integration, not
  an in-house deliverable.
- **Live x402 settlement at scale.** M6 fires one paying call. Production
  settlement at scale is V3 (per the standard tiering in
  `business-manager` operating principles).
- **Per-operation cost surfaces, model branding, raw embeddings in
  output.** Hard "OUT" per CLAUDE.md and the operating principles.

---

## 9. Risk register

Top 5 risks to first deliverable, ranked.

| # | Risk | Probability | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| **1** | **The panel-architecture gap eats S40 / M1.** A reviewer or first user asks the skill a question outside the canon's coverage; the skill defers; we look incomplete. | Medium-High | Medium | The skill's Step 0 routing already routes out-of-class questions to other OKX skills. Tighten the routing copy + add a "what Gecko grounds vs doesn't" panel in the SKILL.md so the limitation is *advertised*, not hidden. The wedge is honest abstention; we lean into it. | `ai-ml-engineer` |
| **2** | **Live x402 flip drags / breaks first call.** M6 needs the flip ceremony + funded operator wallet + post-flip smoke. Per `memory/project_buyer_wallet_blocker_2026_05_08`, the buyer-wallet plumbing is unbuilt; per `memory/project_x402_stub_then_live`, the flip is founder-gated and irreversible-ish. | Medium | High (blocks revenue) | Decouple. Ship M1/M2 in stub mode (no revenue, no flip needed). M6 / X402-live is its own sprint (S44), behind a feature flag, with rollback paths documented. | `web3-engineer` |
| **3** | **Skill marketplace gatekeeping slows M1.** Path A MR review is undocumented in cycle time; could take days or weeks. Marketplace publisher onboarding is unknown (§7). | Medium | Medium | Submit Path A MR with full conformance and `skill-guard` clean; if review > 7 days, dual-track via Path B (marketplace) and `gecko-claude` distribution as fallbacks. We control the oracle endpoint — distribution is interchangeable. | `business-manager` |
| **4** | **`chart_analyst` confabulates in S41 and we regress the panel.** The S24 WS-A failure mode (inventing support/resistance) returns when we add chart reading. | Medium | High (re-burns trust) | The eval gate from §5.3 must pass before the voice ships. If the eval can't hit threshold, the voice does not ship and S41 slips. No iteration past 4 prompt cycles (`feedback_prompt_iteration_plateau`). | `ai-ml-engineer` |
| **5** | **Oracle uptime degrades during a judge / first-user run.** A 500 during the M2 first-stranger run brick the publish moment. | Low-Medium | High | M1 SKILL.md has a graceful fallback path ("oracle unavailable → baseline heuristic") so the skill doesn't brick. CloudFormation + ECS monitoring already in place (`memory/reference_deploy_script`). Pre-publish smoke 24h before M2 fires. | `devops-engineer` |

**Risks NOT on this list, with justification:**

- *"Founder runs out of funding."* — Per `memory/feedback_okx_no_funding_pressure`,
  there is no funding pressure. The first deliverable is sized to ship
  on existing infrastructure spend.
- *"Competitor ships first."* — Per `memory/project_real_competitors_2026_05_07`,
  the actual competitor set (frames.ag, Bazaar, Apify-style marketplaces)
  is not racing us to a yield-verdict skill. The neutral verdict layer is
  *the gap none of them touch* per
  `2026-05-19-okx-complement-map-s38-plan.md`.
- *"The S37 ship-gate degrades on real-world traffic."* — Possible, but
  M4 (the forward track record) makes that *observable* rather than
  hidden. The mitigation is the build, not a separate risk line.

---

## 10. Open questions to brainstorm with founder

The list of design choices we owe an answer to. Each one is a 5–15
minute brainstorm; together they shape S40–S44 finalization.

1. **Which voice goes first — `chart_analyst` or `memory_voice`?**
   §5.2 picks `chart_analyst`. The case for `memory_voice` first: the
   cross-call wedge against Perplexity / ChatGPT is the wedge the
   product-thesis docs (`memory/project_wedge_wire_path_b`,
   `memory/project_knowledge_as_commodity_pivot`) call the moat. If the
   moat is *memory*, ship the moat first. The case for `chart_analyst`
   first remains the existing-question-profile leverage argument.
2. **What's the pricing model for the first paid call?** §7 #1. Defaults
   to $0.25 USDC, but the operating principles say session-based pricing,
   not per-call. A single $0.25 call is *less* of a session and *more* of
   a query — does that contradict the session-pricing principle, or is
   $0.25 fine because the "session" here is one verdict-and-render?
3. **Single-skill or multi-skill first deliverable?** §7 #6. Default is
   single. A multi-skill ship (a yield skill + a token skill) signals
   "reusable oracle" but doubles the M1 scope.
4. **First-deliverable date commitment** — pick a date in the
   2026-05-26 to 2026-06-09 interval. §7 #4.
5. **What goes in the public track record beyond verdict + outcome?**
   M4 ledger schema. Voice-level reads? Dissent text? Citation IDs?
   Should buyers see the inputs that produced the verdict, or only the
   output?
6. **Is the contest bot's artifact log part of the public track record
   from day 1, or do we reset the ledger when M4 ships?** The bot has
   been running and emitting `artifact_YYYYMMDD.jsonl` — that data is the
   seed but it's all `gate_block` rows (the gate didn't fire any allows,
   per the contest-fire-rate retune doc). Quality of the seed matters.
7. **Do we want a small set of *named beta users* between M1 and M6?**
   E.g., Jen at OKX + a few `gecko-claude` users + a friend with a real
   OKX DeFi position. Costs ~$0 to invite, provides M2-quality
   dogfooding, drives M3 prioritization.

---

## Appendix A — Dogfood discipline after each sprint

Per `memory/feedback_dogfood_loop`: after each sprint, run
`gecko_review` + a 5-idea stress matrix to drive the next sprint's plan.
Encoded into S40–S44 as the **last day of each sprint is a dogfood
day**, not extra scope. The 5-idea matrix on `gecko-yield-verdict` for
S40's dogfood day:

| Idea | Question class | Expected verdict shape | Why on the list |
|---|---|---|---|
| 1 | "Should I deposit USDC into Kamino pool 227050?" | act/pass with confidence + citations | The canonical Class-D question; already verified |
| 2 | "Should I deposit SOL into Marinade?" | depends; pool-quality verdict | Different protocol, same vertical |
| 3 | "Should I deposit USDC into Aave v3?" | act with high confidence (mature protocol) | Sanity check on canon coverage of established protocols |
| 4 | "Is the 25% APY on [random new farm] real?" | pass / out_of_scope | Out-of-corpus pool, abstain wedge in action |
| 5 | "Should I deposit my entire portfolio into [protocol]?" | pass / risk_manager dissent | Risk-management edge case |

If any one of these fails to produce a defensible verdict envelope, the
sprint ships with the gap documented and the gap becomes a P0 for the
next sprint.

---

## Appendix B — What the contest bot data becomes

The contest artifact log (`contest_bot/artifact_YYYYMMDD.jsonl`) is the
**seed** for M4. Specifically:

- Each `gate_block` row is a counterfactual baseline trade Gecko declined.
- Each `gate_allow` row (none observed yet, but the schema supports it)
  is a Gecko-cleared trade.
- Each `position_open` / `position_close` row is the realized outcome.

For M4, we add a per-day **Merkle root + signature + outcome-attribution
job** that runs against this log. The contest bot becomes the prototype
for the `gecko-trace` ledger service (working name).

This is the closest the trading agent gets to a revenue product: it's
not one, but the *data it emits* is the trust instrument the oracle
sells against. Per `memory/project_ownership_tier_strategy_2026_05_16`:
**trading agent = $0 proof artifact**. The artifact log is the artifact.

---

## Appendix C — What changes if the panel-architecture diagnosis is wrong

The §2 headline learning ("panel cannot return `act` on momentum spot
because no voice reads charts") is the load-bearing diagnosis. If
`ai-ml-engineer`'s read is wrong:

- If the panel *can* in fact return `act` and the contest just got
  unlucky on N=3 polls → S41 becomes lower-priority; the
  `gecko-yield-verdict` skill is already complete enough, and the
  panel expansion delays to S43+ in favor of M4 (track record).
- If the panel can return `act` but only under question-shape conditions
  we haven't isolated → S41 splits into a question-shape diagnostic
  sprint first, then `chart_analyst` lands in S42.

How we'd know: a clean N=20 momentum-spot poll set with varied
question shapes (different horizons, different framing) on the current
panel, paired with a contamination check (was each voice's emission
parseable / structured / non-empty). If the act-rate over N=20 is
materially above the 0–5% interval from §1.2 of
`2026-05-20-panel-act-rate-on-momentum-spot.md`, the diagnosis is wrong
and the roadmap re-orders.

That diagnostic sprint is itself ~2 days of `ai-ml-engineer` work and is
**not currently planned**. It is option-value, not roadmap. If the
founder thinks the diagnosis deserves a falsifiability check before
committing S41 to `chart_analyst`, that's a legitimate open question.

---

## Cross-references

- `docs/strategy/2026-05-20-contest-fire-rate-retune.md` (`f62a17e`) — contest fire-rate math.
- `docs/strategy/2026-05-20-panel-act-rate-on-momentum-spot.md` (`e70184d`) — the panel-architecture diagnosis.
- `docs/strategy/2026-05-19-okx-complement-map-s38-plan.md` — distribution thesis + the complement map.
- `docs/strategy/2026-05-19-backtesting-scoping-plan.md` — trust-instrument workstream.
- `docs/strategy/2026-05-19-okx-contest-ev-analysis.md` (`7c652c0`) — dollar EV math.
- `docs/strategy/2026-05-19-gecko-verdict-demo-comparison-design.md` — BPAR design.
- `docs/superpowers/plans/2026-05-19-s40-plan.md` (`fd082c8`) — superseded by §4 above for cross-sprint sequencing.
- `memory/project_2026_05_18_session_endstate.md` — arc + state.
- `memory/project_kaas_positioning_2026_05_08.md` — Gecko = KaaS oracle, not a marketplace.
- `memory/project_ownership_tier_strategy_2026_05_16.md` — oracle = product, trading agent = $0 proof artifact, security/privacy/backtesting = partner integrations.
- `memory/feedback_okx_no_funding_pressure.md` — no funding pressure; artifact > dollars.
- `memory/feedback_dogfood_loop.md` — sprint discipline.
- `memory/feedback_prompt_iteration_plateau.md` — coordinator verdict logic in code, not prompt.
- `memory/project_x402_stub_then_live.md` — flip is founder-gated and irreversible-ish.

---

**This roadmap is opinionated. Push back where it's wrong. The next
session's first action is reading this doc and arguing with §1, §5.2,
and §7 #1.**
