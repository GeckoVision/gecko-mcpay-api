# Gecko — Decision Firewall for Solana — Product Story
**For:** Co-founder (Design)
**Date:** June 2026
**From:** Ernani

> **Supersedes the Builder-Bootstrap research-tool era (≤ May 2026); current as of June 2026.**
> Everything before this — the "describe your idea, get a business plan + validation + PRD"
> product — is dead. This is the narrative for what Gecko actually is now.

---

> **Gecko is the decision firewall for Solana — it tells AI agents and launchpads whether a
> token's market is real or manufactured, before any capital moves.**
>
> *Every tool checks the contract. Gecko checks the market is real.*
> *Execution has BAM. Decisions have Gecko.*

---

This document is the story: the two failures that define the problem, the one insight that
separates us from every other safety tool, where we sit next to Jito's execution layer, what the
moat actually is, who pays and why, and how we get distributed. It is written to be argued with —
push back on anything that feels like a stretch, because the honest version is the only one worth
telling.

---

## Part I — Two failures that define the problem

Gecko exists because of a gap that two very different on-chain disasters expose from opposite ends.

### Failure 1 — The drain: Drift, ~$285M, April 2026

In April 2026 an attacker drained roughly $285M from Drift Protocol. There was no contract bug.

Drift's admin control was a Squads V4 multisig — 2-of-5, with **no timelock**. Over months, a
social-engineering campaign compromised two signers' laptops (a malicious VS Code repo that
auto-ran on open, plus TestFlight malware). The attacker pre-signed admin transactions using
**durable nonces** — transactions that never expire and can sit on-chain for weeks. When the
threshold was finally met, they fired an `UpdateAdmin`, spun up a **fake market** for their own
token with a **controlled oracle** valuing fake collateral at $1, switched off the circuit
breakers, and emptied the protocol. The code was never broken. The control plane and the market
data were.

**What this proves:** the thing that failed wasn't the contract — it was the *integrity of the
configuration and the market the protocol trusted.* A contract scanner reads the code and sees
nothing wrong. That's exactly the blind spot.

**The honest version (and we hold this line hard):** Gecko **scores the control plane** — multisig
threshold, missing timelock, who actually holds the upgrade authority — and **detects the
manufactured market** — the wash-traded price history, the controlled-oracle divergence. Gecko does
**not** run anyone's multisig and would **not** have stopped two compromised laptops. So the deck
says *"Gecko flags the control plane,"* never *"Gecko would have blocked Drift."* The difference
matters: we GRADE governance hygiene, we never PROVIDE governance.

### Failure 2 — Launch mortality (the core wedge)

The everyday version of the same gap, at massive scale:

- **More than half of pump.fun tokens are sniped in the exact block they're created** (Pine Analytics).
- **About 1% ever graduate** (The Block).
- **Around 75% are dead within a day** (CCN).

Here's the mechanism, because the design has to make it legible: a new token launches. Bots capture
the supply *in block zero*, before any human can react. They then trade it back and forth among
themselves — **manufactured volume that paints a healthy-looking chart.** Real buyers see the chart,
buy in, and become the snipers' exit liquidity. The price collapses. The token dies.

This is Gecko's core wedge: catching manufactured launch demand at Block Zero — before an agent
buys, before a launchpad lists.

---

## Part II — The insight: contract vs. market

Every safety tool on Solana checks the same thing: **the contract.** Is the mint renounced? Is there
a freeze authority? Is it a honeypot? RugCheck, GoPlus, Solsniffer — all excellent, all crowded, all
on the *code* axis.

Both failures above sail straight through a contract check. Drift's contracts were fine. A sniped
pump.fun token's contract is often fine. The damage lives somewhere a code scan can't see:

> **The contract can be perfect and the market can still be a lie.**

Gecko checks the empty axis: **is the market real?** Is the demand manufactured by snipers, inflated
by wash trades, propped up by a controlled oracle? We answer that by fusing on-chain behavior across
**many wallets, across slots, across pools** — not a single-transaction rule, not a static snapshot —
into one verdict: `ok`, `caution`, or `block`, with the reasons attached and any surviving dissent
preserved. An agent or a launchpad acts on it **before committing capital.**

And the boundary that makes this safe to build: **Gecko verifies; it never deploys, executes,
custodies, or reorders.** We are the empty seat at the table that has an opinion and no stake in the
outcome. The moment we'd "deploy your money into the best yield," we've stopped being a firewall and
become a fund. We don't cross that line.

---

## Part III — Where we sit: BAM vs. Gecko

The cleanest way to explain Gecko to anyone who knows Solana is by contrast with Jito's BAM.

There are **two different kinds of neutrality** on a trade:

| Axis | The question it answers | Who owns it |
|---|---|---|
| **Execution neutrality** | Whose transaction goes first? Was the ordering honest? | **BAM** — TEE-encrypted, cryptographically attested ordering |
| **Decision neutrality** | Is the market this trade rests on *real*, or manufactured? | **Empty seat → Gecko** |

> **BAM makes execution trustworthy; Gecko makes the decision trustworthy.**

The proof that these don't overlap is Drift again: **BAM would have ordered and attested that $285M
drain flawlessly.** Perfect execution neutrality, zero decision integrity — the money still leaves.
Different layer, different problem, empty seat.

A subtlety the design shouldn't fudge: **Solana has no mempool.** There's no stream of pending
transactions to intercept. So Gecko never "blocks the transaction in the block." It either **advises**
the next actor right after a transaction confirms (a first-mover signal — it can't undo what landed),
or, in the enforcement posture, a token can wire in a **Token-2022 transfer hook** that reverts
disallowed transfers at execution time from a list Gecko publishes ahead of block zero. Detect and
advise, or enforce at the transfer — never intercept in-flight.

The long-term "official layer" path is a **Verification NCN on Jito's restaking arm** (~2027) — where
operators run Gecko's panel, stakers back its honesty, and a verdict that contradicts its own evidence
gets slashed. That mirrors the accepted Blocksize RPC-NCN pattern and is grant-fundable. It is **not** a
BAM plugin — a plugin would drag Gecko into sequencing and break the verify-not-execute boundary.
Honest gap: we have no named Jito-ecosystem design partner yet. The technical seam is real; the
commercial one isn't proven. (`docs/concepts/jito-101.md` has the full treatment.)

---

## Part IV — The moat: the verdict ledger

The natural assumption is that the moat is the detector — the clever fusion of snipe and wash signals.
It isn't. A detector is an engine; engines get copied; detection is table stakes the moment someone
with money decides to compete. The bigger threat is a player like GoPlus with hundreds of millions of
scans a month who could extend into our axis tomorrow.

So the moat has to be something distribution can't buy. It is:

> **The compounding ledger of verdicts Gecko commits BEFORE each launch resolves, then grades by what
> the launch actually did.**

Every paid verdict is a timestamped prediction — `(Block-0 signal → resolved outcome)` — that becomes a
labeled data pair the instant the launch plays out. **No competitor can backfill that**, because a
contract scan can be re-run after the fact, but a *pre-act verdict with a pre-outcome timestamp* can
only be created by being there first. The line:

> *Distribution buys traffic, not truth.*

The loop compounds: someone pays → we commit a verdict → the launch resolves → we get a labeled
outcome → precision climbs and an auditable track record accrues ("Gecko-verified tokens rugged ~2% vs
a ~40% baseline") → agents route liquidity to verified tokens → verification becomes the default → more
issuers seek it. Detection depth feeds this ledger; the ledger is the moat depth feeds.

---

## Part V — Who pays, and why

This is the part that's easy to get wrong, so it's stated bluntly: **the issuer is usually the wrong
buyer.** "Protect your token, keep your holders" sounds like the pitch — but for most memecoin
launches, the issuer *is* the sniper, or is fine with it. The genuinely-harmed serious project is the
minority. Selling protection to the victim assumes a victim who wants it.

The two real buyers:

| Buyer | What they're buying | Why the WTP is real |
|---|---|---|
| **AI agent runtimes / autonomous traders** (primary) | Decision integrity — "is this launch clean before I deploy capital?" | A bad fill is a measurable, immediate loss. They'll pay per call to avoid it. |
| **Launchpads** | Reputation and integration revenue — score and badge what they list so real liquidity routes to them | They already pay for this. The proof: GoPlus's SafeToken earns **$1.7M via launchpad integrations**, not per-issuer sales. |

"Retain holders" stays in the deck — but as **downstream evidence in a launchpad pitch**, never the
headline to an issuer who might be the problem.

The free `/safety` firewall and the paid `/trade_research` oracle map onto this:

> **The firewall acquires users; the oracle earns the ones with real money on the line.**

The firewall is free, sub-second, and exists to bring agents in and warm the cache. The oracle is the
paid, deep verdict — a multi-voice debate with surviving dissent, citations, and an on-chain receipt —
for the moments where someone has real capital committed. Cost scales with distinct tokens; revenue
scales with agents. That gap is the margin.

---

## Part VI — Distribution

Features aren't the constraint; **distribution is.** Selling one indie developer at a time on a
micro-priced call doesn't fund the company. The path that works is the one Snyk and GoPlus took: win a
small number of **framework integrations**, and let them carry the long tail.

So the primary surface is a **SendAI (Solana Agent Kit) adapter** — *agents check before they operate* —
backed by the **MCP** server (so it drops natively into Claude Code) and **x402** for metered payment,
with **launchpad integration** as the second channel. MCP and x402 make it trivial to *try*; the
framework embed is what makes it the *default*.

---

## Part VII — Honest status (so the design tells the truth)

The design has to reflect maturity, not aspiration. Where things actually stand:

- **Shipped:** the detection engine and all its signals (snipe gate, wash signals, program reputation,
  ALT identity); a **mainnet-fork attack→block demo on surfpool that passes** (a real attack →
  `block`, an evasion attempt → `caution` via concentrated-capture, an organic launch → `clean`), run
  on real mainnet-forked state for $0; the `/safety` surface.
- **Designed / partial:** the Token-2022 enforcement hook, the governance-hygiene scoring, the
  Verification NCN.
- **The open validation:** our thresholds are validated against fork and synthetic data — **not yet
  against real-launch distributions.** Until a real-launch threshold backtest, the firewall stays
  **dark in production** (`GECKO_FIREWALL_ENABLED=false`), and payments run in stub mode
  (`X402_MODE=stub`).

A few phrasings we never use, because they'd be lies: we never say "blocks in-block" or "intercepts
in-flight" (no mempool exists to intercept), and an `unknown` verdict is never "safe" — we **fail open**,
and unknown means unknown. Verdicts are shown as **buckets** (`ok` / `caution` / `block`), never raw
scores, and there are **no public leaderboards.**

---

## Part VIII — Design implications

This section is for you.

### What the interface must make legible

The whole product is one judgment rendered for someone about to risk money. Three things have to land
instantly:

- **The verdict** — `ok` / `caution` / `block`. One glance. This is the moment.
- **The reasons** — why. Which signals fired (a sniped block-0, a wash loop, a thin-pool price bait, a
  shaky control plane). A block with no reason gets disabled in a week.
- **The dissent** — on the paid oracle, the surviving counter-argument. Honesty is the product; a verdict
  that hides its own doubt erodes the thing we sell.

### What to never show

- Raw scores or confidence floats (we show buckets — anti-gaming).
- Model names, token counts, per-operation cost (plumbing, and it erodes identity).
- Anything that implies we *acted* — placed, blocked, reordered, or moved money. We **advise** and
  **enforce-at-transfer**; we never execute.
- A "safe" stamp on an `unknown`. Unknown is its own state; design it as caution-adjacent, not green.

### What to always show

- The verdict bucket, prominent and immediate.
- The evidence behind it — the firewall earns trust by showing its work.
- The boundary, implicitly: this is a *check*, not a *trade*. The user is still the one who acts.

---

*Gecko — Decision Firewall for Solana · Ernani Britto · June 2026 (post-pivot rewrite, supersedes the Builder-Bootstrap product story)*
