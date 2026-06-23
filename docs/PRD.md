# Gecko — Decision Firewall for Solana — PRD

**Version:** 2.0
**Date:** June 2026
**Author:** Ernani Britto
**Status:** Active — detection engine shipped; firewall dark in prod pending real-launch threshold validation

> **Supersedes the Builder-Bootstrap research-tool era (≤ May 2026); current as of June 2026.**
> The pre-pivot "idea → business plan / validation / PRD" product is dead. This document
> describes the current product: a pre-trade decision firewall for Solana.

---

## Positioning / What Gecko Is

> **Gecko is the decision firewall for Solana — it tells AI agents and launchpads whether a token's market is real or manufactured, before any capital moves.**

**Tagline:** *Every tool checks the contract. Gecko checks the market is real.*

**Peer-to-stack line:** *Execution has BAM. Decisions have Gecko.*

This is the one positioning. It appears verbatim in `docs/product-story.md`, the public
`app.geckovision.tech/skill.md` (sister repo `gecko-claude`), and any user-facing copy.
Drift between surfaces is a regression — fix at the source, not by re-paraphrasing.

### The wedge in one paragraph

Contract scanners (RugCheck, GoPlus, Solsniffer) check the **code** — is the mint renounced,
is there a freeze authority, is it a honeypot. That axis is crowded. Gecko checks a different,
empty axis: **is the market real** — or is the demand manufactured by snipers, wash trades,
and a painted price history. Gecko fuses on-chain behavior across **wallets × slots × pools**
into a single pre-trade verdict (`ok` / `caution` / `block` + reasons + surviving dissent) that
an agent or launchpad acts on **before committing capital**. Gecko **verifies; it never deploys,
executes, custodies, or reorders.** That boundary is the product.

---

## The Problem (the narrative spine — two sourced failures)

### 1. The drain — Drift, ~$285M, April 2026

A governance / control-plane compromise, not a contract bug. Drift ran a Squads V4 multisig
(2-of-5, **zero timelock**). A months-long social-engineering campaign compromised two signers'
devices; the attacker pre-signed admin transactions with **durable nonces** (valid indefinitely,
sat on-chain ~1 week), executed an `UpdateAdmin`, created a fake market for their own token (CVT)
with a **controlled oracle** pricing fake collateral at $1, disabled circuit breakers, and drained
~$285M. The contracts stayed intact the whole time.

**Honest framing:** Gecko **scores governance hygiene** (multisig threshold, timelock presence,
authority-holder classification, upgrade/metadata authority) and **detects the manufactured market**
(wash-traded price history, controlled-oracle divergence). Gecko does **not** run anyone's multisig
and does **not** claim it would have stopped the signer compromise. The deck line is *"Gecko flags
the control plane"* — never *"Gecko would have blocked Drift."* (Sources: CoinDesk, Chainalysis,
BlockSec precise figure $285,279,417.69.)

### 2. Launch mortality — the core wedge

- **>50% of pump.fun tokens are sniped in the exact creation block** (Pine Analytics, Apr 2025).
- **~1% ever graduate** (The Block / pump.fun data).
- **~75% are inactive within a day** (CCN).

**The mechanism:** snipers capture supply at block 0 → manufactured volume paints the chart →
real buyers arrive and become exit liquidity → the token dies. This is Gecko's core wedge: detecting
manufactured launch demand at Block Zero, before an agent buys or a launchpad lists.

---

## Buyers / ICP

Two buyers, one product. Critically — **the issuer-as-victim is NOT the primary buyer.** Many
memecoin issuers ARE the snipers, or are complicit/indifferent. "Retain your holders" is downstream
evidence in a launchpad pitch, never the primary sell.

| Buyer | JTBD | Why they pay |
|---|---|---|
| **AI agent runtimes / autonomous traders** (primary, decision-integrity) | "Is this launch clean before I deploy capital?" | Immediate, calculable WTP — a bad fill is a measurable loss. Synchronous per-call veto. |
| **Launchpads** (reputation / integration revenue) | "Score and badge the tokens we list so real liquidity routes to us." | Reputation is at stake; they already pay. The GoPlus SafeToken playbook — **$1.7M revenue via launchpad integrations** (PancakeSwap Springboard, Clanker, etc.), not per-issuer sales. |

**Distribution channels** (the long-tail carriers, not the buyer): agent-framework builders
(SendAI / Solana Agent Kit, ElizaOS, OKX OnchainOS), DeFi protocols with collateral-whitelisting
risk (post-Drift, actively shopping), agent marketplaces.

> **Distribution is the binding constraint, not features.** Direct-to-indie-dev per-call is a trap
> (micro-price can't fund discovery). The scalable path is framework-embedding — win 1–3 integrations,
> they carry the long tail (the Snyk / GoPlus playbook). MCP + x402 solve "try it," not "make it default."

---

## Distribution

The primary distribution surface is a **SendAI (Solana Agent Kit) adapter** — *"agents check before
they operate"* — plus the **MCP** server (the Claude Code surface) and **x402** for metered payment.
Launchpad integration is the second channel. Each is a thin transport layer over `gecko-core`.

---

## The Product — two-tier surface

| Surface | Price | What it does | Role |
|---|---|---|---|
| **`/safety` firewall** | **FREE** (sub-second) | Cache-read pre-trade verdict: `ok` / `caution` / `block` + reasons. Static contract read + the launch-integrity (snipe/wash) fusion. | **Acquires users, warms the cache, funds the moat.** Not a business on its own (~$3/agent/mo cost). |
| **`/trade_research` oracle** | **PAID** (~$0.75/verdict) | Deep verdict: 7-voice adversarial debate, surviving dissent, citations, on-chain receipt. | **Earns the users with real money on the line.** 90–96% margin; concrete WTP. |

> *The firewall acquires users; the oracle earns the ones with real money on the line.*

Cache-then-charge is the margin lever: cost scales with **distinct tokens**, revenue with **agents**
— sublinear. A "no" (block) is billed exactly like a "yes" — the verdict is the product, not the answer.

---

## The Moat — the compounding verdict ledger

The moat is **not** the detector (an engine — copyable, table-stakes), **not** the flywheel (the
distribution mechanism that *feeds* the moat), **not** the on-chain hook (a feature / switching cost).

**The moat is the compounding ledger of verdicts Gecko commits BEFORE each launch resolves, then
grades by what the launch actually did** — proprietary `(Block-0 signal → resolved outcome)` label
pairs no competitor can backfill.

> *Distribution buys traffic, not truth.* A competitor with 700M scans/month can match distribution,
> but a contract scan is backfillable; a pre-act verdict with a pre-outcome timestamp is not.

Compounding loop: pay → committed verdict → outcome resolves → label → precision rises + an auditable
track record ("Gecko-verified rugged ~2% vs ~40% baseline") → agents route liquidity to verified
tokens → verification becomes mandatory → more issuers seek it.

---

## Architecture — verify-not-execute, detect → verdict → receipt

### Where Gecko sits (Jito / BAM neutrality)

There are two distinct neutralities. Gecko owns the empty one.

| Axis | Question | Owner |
|---|---|---|
| **Execution neutrality** | Whose tx goes first? Was it ordered honestly? | **BAM** (TEE-encrypted, cryptographically attested ordering) |
| **Decision neutrality** | Is the market the decision rests on *real* — or sniped / wash-inflated / oracle-poisoned? | **Empty seat → Gecko** |

> **BAM makes execution trustworthy; Gecko makes the decision trustworthy.**

Orthogonality proof: BAM would have ordered and attested the Drift drain flawlessly — the money still
leaves. Perfect execution neutrality, zero decision integrity. (Full treatment: `docs/concepts/jito-101.md`.)

### Two enforcement postures (no in-flight intercept)

Solana has **no mempool** — there is no pending-tx stream to intercept. Never claim Gecko "blocks in
the block" or "intercepts in-flight." The two honest postures are:

1. **ADVISE** — after `confirmed` (~0.6–2s), emit a verdict that guides whoever acts NEXT. Cannot undo
   a landed tx; it is a first-mover signal layer. The shipped surface is `/safety` + the MCP
   `gecko_safety` tool; the SendAI Agent-Kit pre-trade adapter is **designed, not built** (the
   in-repo `sendai` modules are execution stubs — the prototype slice wires the firewall consumer).
2. **ENFORCE** — a Token-2022 transfer-hook denylist: a PDA written *before* block 0; the hook reverts
   disallowed transfers at execution time (downstream of Jito placement, never touching the auction).
   Designed, not shipped.

Programs have no network I/O — on-chain enforcement reads pre-published PDA state; it cannot call
Gecko's API. (Full treatment: `docs/concepts/solana-101.md`.)

### Signals the engine fuses (shipped)

A single scored `launch_integrity` verdict, fused across wallets × slots × pools — the axis no one
else occupies (Jito sees one bundle; scanners see one snapshot):

- **Snipe gate** — same-slot co-buy, Jito-bundle snipe (tip-account transfer), fresh-wallet swarm,
  fee/tip outlier (vs live p95 tip floor), unknown-program route, shared-ALT execution-rig identity,
  LP drain (inflate-then-dump), concentrated-capture (the residual that survives every automation tell
  being off — float-capture without crowd diversity).
- **Wash signals** — thin-pool buy-loop, self-trade/ring, common-funder sybil, multi-pool price-bait
  (index-price truth).
- **Program reputation** — bundle → originating-program attribution; first-seen custom program tell.
- **ALT identity** — clustering by shared execution rig, survives wallet re-funding that defeats funder graphs.

Framing terms used internally and in technical copy: **"Information-MEV," "Layer 4," "Plane C ·
Data-Integrity Gate."** Public surfaces show buckets (`ok` / `caution` / `block`), never raw scores.

---

## Roadmap tiers

### Now (shipped / shipping)

| Item | Status |
|---|---|
| Detection engine + all signals above | **Shipped** (in `gecko_core/trade_agent/hotpath/`) |
| Mainnet-fork attack→block demo (surfpool, $0) — attack→block, evasion→caution, organic→clean | **Shipped + PASSES** |
| `/safety` free firewall surface (cache-read) | **Shipped** (cold path on-demand; dark for live pools — see status table) |
| MCP `gecko_safety` tool → `/safety` (free agent surface) | **Shipped** |
| x402 receipt hash + `/v1/receipt/verify` | **Shipped** (on-chain anchor built, 0 callers — wired by the prototype) |
| SendAI Agent-Kit pre-trade adapter (the "agent checks before it acts" consumer) | **Designed — NOT built** (in-repo `sendai` is execution-only; the prototype slice wires it) |
| Verdict ledger (the moat — persisted, graded-by-outcome) | **Designed — NOT wired** (no verdict persisted today; the prototype writes the first row) |

### Next (designed / partial)

| Item | Status |
|---|---|
| Token-2022 transfer-hook enforcement (denylist PDA) | **Designed** |
| Governance-hygiene scoring (multisig threshold, timelock, authority classification, durable-nonce detector) | **Designed / partial** (SafetyBlock has mint/freeze flags; ~70% of the slice exists) |
| Real-launch threshold backtest → flip `GECKO_FIREWALL_ENABLED` on | **The open validation** (see status table) |
| `/trade_research` paid oracle as the revenue surface | Built; gated on the firewall funnel maturing |

### NCN — ~2027 (the "official layer + rail")

A **Gecko Verification NCN** on Jito's **restaking** arm — operators run the panel, stakers back
honesty, slashing if a verdict contradicts its evidence. Mirrors the accepted **Blocksize RPC-NCN**
pattern; **JIP-fundable.** This is **not** a BAM plugin — a plugin governs sequencing, which would force
Gecko into execution and break verify-not-execute. **Honest gap:** no named Jito-ecosystem design
partner yet; the technical seam is real, the commercial seam is unvalidated.

---

## Honest status table (do NOT overclaim)

| Capability | Maturity | Honest claim |
|---|---|---|
| Detection engine + signals | **SHIPPED** | Pure, deterministic, falsifiable against synthetic snapshots. |
| Mainnet-fork attack→block demo (surfpool) | **SHIPPED, PASSES** | "Caught on real mainnet-forked state, $0." Fidelity gaps noted (wallet-age fresh-by-construction; Jito tip footprint-faithful not placement-faithful). |
| `/safety` surface | **SHIPPED** | Cache-read verdict; runs on-demand today. |
| Token-2022 enforcement hook | **DESIGNED** | Spec'd; not built. |
| Governance-hygiene scoring | **PARTIAL** | Mint/freeze flags exist; multisig/timelock/durable-nonce scoring designed. |
| Verification NCN | **DESIGNED, ~2027** | Technical seam real; no design partner; JIP-fundable. |
| **Threshold validation** | **THE OPEN VALIDATION** | Thresholds are fork/synthetic-validated, **NOT yet validated against real-launch distributions.** The firewall stays **DARK in prod** (`GECKO_FIREWALL_ENABLED=false`) until a real-launch threshold backtest. The live-signal path also needs a Helius plan exposing `transactionSubscribe`. |
| Payments | **STUB** | `X402_MODE=stub` — code path validated, no real settlement, pending explicit go-ahead. |

**Standing honesty rules:**
- Solana has no mempool → **never** claim "blocks in-block" or "intercepts in-flight." Detect-and-advise,
  or enforce at transfer-exec.
- **Fail-OPEN:** an `unknown` verdict is not "safe." Unknown ≠ pass.
- **Buckets, not raw scores.** No public leaderboards.

---

## Non-Functional Requirements

| Requirement | Target |
|---|---|
| **Warm-serve latency** (`/safety` cache hit) | Sub-millisecond — serve does zero reasoning; returns a pre-computed verdict from cache. |
| **Detection latency** (ingest → verdict) | 0–2s window; verdict emitted at `confirmed` (~0.6s). ShredStream's ~120ms edge is irrelevant to this budget (we do not build it). |
| **False-positive rate** | Near-zero required — a "no" has invisible/negative immediate value; devs disable a noisy firewall in a week. Every block carries its evidence envelope. |
| **Security** | No user private keys stored; `SUPABASE_SERVICE_ROLE_KEY` server-only; `X402_MODE` passed through every payment-touching path (default `stub`); URLs validated (no SSRF); LLM input tokens capped. |
| **Output discipline** | No model branding, no token counts, no per-operation cost shown to users. Buckets, not raw scores. No raw embeddings in output. LLM JSON responses use `response_format={"type": "json_object"}`. |

---

## Success Metrics

| Metric | Target |
|---|---|
| Mainnet-fork demo | attack→`block`, evasion→`caution`, organic→`clean` — all green (**met**) |
| Real-launch threshold backtest | Precision / FP-rate measured against labeled real-launch distributions before go-live (**[TBD]** — the gating validation) |
| Framework integrations | ≥1 framework partnership (SendAI adapter live + carried) before a competitor copies the wash/oracle axis |
| Verdict ledger | First N pre-committed verdicts graded by resolved outcome — the labeled-attack benchmark begins compounding |
| Revenue (`/trade_research`) | First paid verdicts at ~$0.75 once the firewall funnel matures |

> Numbers that cannot yet be defended against real-launch data are marked `[TBD]` rather than faked.

---

## Explicitly Out of Scope

| Item | Reason |
|---|---|
| **"Deploy into the best yield" / Kamino-as-yield-product** | Milo-shaped. A separate track, NOT the firewall. Kamino enters only as a verify/compare target ("which position is safer, is the APY real"), never a money-deploy product. |
| **The trade-agent (contest_bot)** | A **$0 PROOF artifact** — a public track record that proves the oracle works. Never a separate SKU. |
| **Operating a multisig / custody / signing** | Squads' moat; off-thesis; key-custody liability; produces no pre-act verdict. We GRADE governance, we never PROVIDE it. |
| **BAM plugin** | A plugin governs sequencing → forces Gecko into execution + ordering liability → breaks verify-not-execute. The rail is the restaking NCN, not a plugin. |
| **In-flight / in-block interception** | No Solana mempool; no surface to intercept. Detect-and-advise or enforce at transfer-exec only. |
| **Per-operation pricing, model branding, raw scores/embeddings in output** | Erodes identity / leaks plumbing / enables gaming. |
| **Public leaderboards** | Anti-gaming; buckets only. |

---

*Gecko — Decision Firewall for Solana · Ernani Britto · June 2026 (v2.0 — post-pivot rewrite, supersedes Builder-Bootstrap v1.3)*
