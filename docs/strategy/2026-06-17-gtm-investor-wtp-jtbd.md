# Gecko — GTM Playbook: Investor Narrative + WTP Validation + JTBD + First Users (2026-06-17)

Consolidates three lenses (business-manager + product-manager) into one fundraise-and-first-users playbook. Pairs with `2026-06-17-market-icp-thesis.md` (market/ICP) + `2026-06-16-architecture-and-evolution.md` (tech).

---

## 1. Investor narrative — price the integrity-tax on capital, not the call
**Headline:** *Gecko is the decision firewall for autonomous capital — the independent verdict layer an AI trading agent calls before it moves money.* Picks-and-shovels for the agent economy.

**Frame TAM as integrity-tax on protected AUM, NOT per-call volume.** Per-call math gives a misleadingly tiny number (~$0.1–12M = infra cost, not a market). The right unit is the bps-of-AUM a firewall earns the way custody / audit / insurance price risk on capital. *You insure the capital, not the API call.* Drift wasn't a $285M transaction-fee problem; it was a $285M capital-at-risk problem.

**It's a timing bet, not a science bet — three curves converging in 18 months:**
- Autonomous capital going vertical (agents **+300% YoY**, ~**30% of top-pool DeFi TVL**).
- Liability regime flipped (**GENIUS Act** → the *deployer* owns duty-of-care → integrity becomes a compliance surface someone must own).
- It already broke publicly (**Drift $285M** — the existence proof; every framework shipping agents is one bad decision from its own Drift).

**Wedge (why incumbents can't take it):** rug-checkers answer "is the asset malicious"; we answer "should this agent take this action with this capital now" (adversarial debate + canon citations + surviving dissent + an audit record the deployer shows a regulator). Frameworks ship agents and want the alpha — an *independent* gate they don't author is the credible one → **they're customers, not competitors.** Neutrality is the moat.

**Risks (named honestly, each with a mitigation):**
- *Early-vs-niche:* category may be 12–18mo ahead of mandatory demand; per-call SAM genuinely small today → *don't raise on per-call SAM; raise on the WTP milestone below.*
- *Unvalidated WTP:* 2 warm leads, $0 signed revenue → *the next milestone IS the strict WTP experiment.*

**Open founder inputs (deliberately TBD — won't fake):** the **ask amount** + the **target integrity-tax bps band** (the WTP pilots produce the real bps).

---

## 2. WTP validation — the milestone that gates the raise
**The strict "yes" ladder** (don't fool yourself):

| Signal | Counts as |
|---|---|
| "interesting, send docs" | nothing |
| signed LOI / MOU | **weak** (milestone, not validation) |
| design partner commits budget + eng | real (soft) |
| **paid pilot priced as % of protected AUM** | **real (hard) — round gate** |

**Three experiments, in sequence (hardest-to-fake last):**
1. **Framework (SAK/ElizaOS/OKX)** — weeks 0–3. Proves *distribution*: they commit eng + a slot to expose Gecko to deployers. Cheap, fast, unlocks deployer access. Proves the channel, not that anyone pays.
2. **Warm-lead paid pilot** — weeks 2–6. *The round gate.* Convert one warm lead → paid pilot on real/budgeted capital, priced as a function of AUM-at-risk. Money changes hands.
3. **Post-Drift protocol risk team (ICP3)** — weeks 4–12. Highest ACV; bps-of-TVL paid pilot sets the integrity-tax comparable that re-prices the whole TAM. Long cycle (security/compliance buyer) → in motion during the raise, closes after.

> **Single round-gating metric: ≥1 paid pilot priced as a % of protected AUM (target low-single-bps to low-single-%), with a second in committed pipeline.** LOIs don't count. If you can't get past LOIs to one AUM-priced pilot, that's the honest kill-signal — better known before the round.

---

## 3. JTBD + first-user test
**JTBD (builder's words):** *"Before my agent commits capital, tell me in one call whether the price is real or manufactured — so it doesn't get Drift'd or buy a wash-pumped top while I'm asleep."* Trigger = post-incident. Current alternative = free rug-checkers (answer "is the contract a scam," NOT "is this price manufactured"). Success = one sub-second `block|caution|ok` that **at least once stops a trade the agent would've made** (a token that's `ok` on a free checker, `block` on Gecko).

**The falsifier (the honest kill-test):** if Gecko's verdict *never diverges* from a free rug-checker on testers' real tokens, the job isn't real. The wedge lives on the **manipulation read being a signal the free tier lacks.**

**Smallest real test (days, $0 in stub):**
- **3–5 named testers**, biased to people who've *been burned* (SendAI / ElizaOS / Colosseum trading-agent devs). Not Ernani re-running it.
- Flow: `curl POST https://api.geckovision.tech/safety {mint}` on (a) a seeded known-manipulated case (BrCA → must `block`), (b) tokens their agent traded last week; then run the same tokens through their free checker and **log every disagreement**; optionally wire a `gate=="block"` veto into their pre-trade hook.
- Instrument via the existing `/events` endpoint (~1 day): per-tester call count, mint, gate, repeat-flag, and the **divergence log** (the key instrument).
- **Validated only if all three fire:** (1) repeat unprompted calls on new mints across ≥2 days; (2) **≥1 divergence event that changed an action**; (3) ≥2 say they'd pay + name a ceiling.

---

## 4. First-ICP attraction — lead every touch with the divergence proof
*(the one token `ok` on a free checker, `block` on Gecko — the only thing that survives "I already have a rug-checker")*

- **ICP1 — framework builders** (SendAI/Eliza/OKX maintainers, #plugin-dev). Smallest yes = one PR / docs example wiring `/safety` as the default pre-trade veto. Reference impl = the SendAI demo agent (declines BrCA). `/safety` is built + free → ready.
- **ICP2 — autonomous bot devs** (Colosseum/OKX-Skills). Pitch = "one free MCP tool: before your bot buys, ask Gecko if the price is manufactured." **⚠️ BUILD GAP: no standalone `gecko_safety` MCP tool today** (safety only reaches MCP via `gecko_trade_research(mint=…)`, which runs a costly full panel). **Build the thin `gecko_safety` wrapper over `POST /safety` before ICP2 outreach** (~half a day, transport-only).
- **ICP3 — protocol risk teams** (post-Drift, highest ACV; direct, not Discord). Smallest yes = a 20-min call running `/safety` live on tokens *in their own market* → one returns `caution`/`block` they hadn't flagged. Defer the batch/audit-output build until ≥2 ask.

**ICP discipline:** primary persona = *the agent-builder who buys tokens autonomously and has been (or fears being) Drift'd* (one decision, one trigger, one channel). **Anti-persona = the alpha/PnL-seeking discretionary trader** — Gecko is a "is this data manufactured" veto, never a "should I buy for gains" tool. All ICP status = `hypothesis` until real strangers fire the test signals.

---

## Immediate next builds (engineering)
1. **Thin `gecko_safety` MCP tool** over `POST /safety` (unblocks ICP2). ~half a day.
2. **Per-tester `/events` instrumentation + divergence log** (the test's measurement). ~1 day.
3. (Already in PRs) config-parity hardening #150/#151; news slug-map #146; paper agent #144.
