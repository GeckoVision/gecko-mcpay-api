# Jito 101 — the Solana execution layer, and where Gecko sits

> Reference doc. Current as of **June 2026**. Companion to [`solana-101.md`](./solana-101.md).
> Every claim is web-grounded; sources + dates at the bottom. Items that move fast or
> are DAO-governed are flagged inline. The point of this doc: understand Jito's
> architecture accurately enough to know **exactly where Gecko is, and is not.**

---

## 0. What "Jito" actually is (one frame)

Jito is **not one product** — it's four businesses under the `$JTO` brand, and they get conflated constantly. For Gecko, two matter:

| # | Arm | What it is | Relevance to Gecko |
|---|---|---|---|
| 1 | **Validator client + Block Engine → BAM** | The MEV **execution** layer. | **The relevant one** — this is the "neutrality" conversation. |
| 2 | **JitoSOL** | Largest liquid-staking token on Solana; MEV tips flow into LST yield (the flywheel). | Context only. |
| 3 | **Restaking + NCNs** | "EigenLayer for Solana" — restake to secure new services. | **The funding/rail path** for Gecko (see §8). |
| 4 | **JTX** | Consumer self-custody trading terminal (perps), launched ~mid-2026. | A proof-case + potential customer, not infra. |

Adoption anchor: the Jito-Solana client runs on **>95% of active stake**. It is effectively the default validator client.

---

## 1. Bundles

A **bundle** is up to **5 transactions** submitted to the Block Engine that execute **sequentially and atomically** — all-or-nothing, in the exact submitted order, within one block.

- **Ordering is guaranteed inside the bundle.** This is what makes coordinated multi-tx strategies possible: a sandwich is literally a bundle `[frontrun, victim, backrun]`; a coordinated snipe is N buys ordered ahead of the crowd.
- **Atomicity / revert protection:** if any tx fails, the whole bundle reverts and lands nothing. A searcher never half-executes. This is *the* feature that makes MEV economically safe to attempt.
- **Minimum tip:** 1000 lamports/bundle (no/low tip won't win the auction).

**Gecko relevance:** bundles are the vehicle for the snipe/sandwich attacks we detect. We don't see bundle *internals* (that needs ShredStream — see §4), but we see their **footprint** at the account-key level after they land.

---

## 2. Tip accounts (the 8) + tip economics

A bundle must pay one of **8 fixed tip accounts** via a SystemProgram transfer.

- The canonical live list is the **`getTipAccounts`** RPC method. We also hard-code the 8 as an offline baseline in `gecko_core/trade_agent/hotpath/jito.py` — **reconcile against `getTipAccounts` before trusting in prod**; the set can drift.
- **The highest-precision automation tell:** a transaction that transfers to one of these 8 is, *by construction*, a bundle submission → automated. Humans don't hand-build Jito bundles. This is the cleanest "bot, not human" signal Gecko has (`is_jito_bundle_tx`).
- **Ordering on Solana is bought, not earned.** The tip is the bid: higher tip → higher auction placement → wins the slot. This is the structural reason block-0 snipers win — see [`solana-101.md` §5](./solana-101.md).
- **MEV → staker flywheel:** tips are distributed (via the Tip Router) to validators and, through JitoSOL, to stakers — why ~every validator runs Jito.

> **Currency flag (DAO-governed):** historically a **6% fee** on tips split Jito Labs / DAO. A Jito Improvement Proposal would route **100% of Block Engine + BAM fees to the DAO Treasury** (pending DAO vote). Cite "6% historically; proposal to route 100% to DAO," not a fixed split.

---

## 3. Block Engine + the auction

The **Block Engine** runs an **off-chain, per-slot, sealed-bid auction** over bundles:

1. Searchers submit bundles + tips.
2. The Engine **simulates** each bundle, **scores** it (tip-per-compute-unit), and selects the highest-paying *combination* that fits the block's compute budget.
3. Winners are forwarded to the leader validator running Jito-Solana.

Bundles touching intersecting account locks compete in the *same* auction; non-intersecting bundles run in parallel auctions. The **Relayer** historically delayed ordinary txs (~200ms) to create the MEV window.

**What was centralized about it:** the legacy Block Engine is **closed-source and run by a single trusted party (Jito Labs)**. You could not verify *how* it ordered transactions, or *that* it ordered them honestly. **This opacity is exactly what BAM is built to fix (§6)** — and it's the crux of the "neutrality = BAM" thesis (§7).

---

## 4. Relayer, ShredStream, jitodontfront

- **Relayer** — receives txs and forwards them to the Block Engine / leader; source of the MEV-window delay on ordinary traffic.
- **ShredStream** — a low-latency feed of **shreds** (block fragments) delivered ~milliseconds before confirmation. It's the searcher's earliest-data edge and a *candidate* earliest-ingest for Gecko. **Gecko's standing decision: do NOT build ShredStream** — the ~120ms edge is useless for our 0-2s detect-and-advise budget, it's a multi-week Rust build, and it only pays off for a counter-trading product we don't sell.
- **jitodontfront** — a *send-side* anti-front-run marker. Add an instruction referencing any pubkey starting with `jitodontfront`, and **the Block Engine rejects any bundle containing that tx unless the tx is at index 0** (it does *not* reorder you to the front — the bundle is simply invalid otherwise). Effect: nothing can be placed ahead of it → no front-run/sandwich on the Jito path.

**Gecko relevance:** we **detect** whether a swap carries dontfront (`has_dontfront_guard`) and **recommend** it as a mitigation — framed honestly as "reduces Jito-routed front-run exposure," never "prevents sandwiches" (it only defends the Jito path; a meaningful share of MEV is non-Jito).

---

## 5. There is no Solana mempool (the March-2024 shutdown)

Solana never had an L1 mempool like Ethereum. Jito briefly ran a **pseudo-mempool** (a permissioned API exposing pending txs). On **March 8, 2024**, Jito Labs **shut it down** because searchers used it for near-constant sandwich attacks (on Mar 7, MEV tips exceeded 10,000 SOL).

**Why this is load-bearing for Gecko's honesty:**
- **There is no canonical pending-tx stream to intercept.** Txs forward straight to the upcoming leader and expire after ~150 blocks. Order flow went **private** (permissioned relays, off-chain auctions).
- **Therefore Gecko must never claim "we block the tx in-block" or "intercept in-flight."** There is no surface to intercept. Gecko reads **settled / pre-confirmation on-chain state** and **advises the next actor**, or enforces *downstream of placement* via a Token-2022 transfer hook. Any doc implying Gecko reads or sits in a "mempool" is wrong.

---

## 6. BAM — Block Assembly Marketplace (the headline)

**What it is:** Proposer-Builder Separation (PBS) for Solana — it **separates transaction sequencing from execution** and replaces the opaque Block Engine with a verifiable, programmable one.

**Timeline (currency-critical):**
- **Jul 21, 2025** — announced.
- **Sep 25, 2025** — **full mainnet GA**; transition from the closed Block Engine begins.
- **Jun 5, 2026** — **>50% of validators run BAM**; Jito clients secure ~89% of stake (Jito-Agave + Jito-Firedancer).
- Code is being open-sourced toward a target of 50+ distributed node operators (permissionless end-state — not fully there yet).

**The three components:**

| Component | What it does |
|---|---|
| **BAM Nodes** | Scheduler nodes running **inside AMD SEV-SNP TEEs**. They source, filter, and **sequence** txs in an encrypted mempool, then emit **cryptographic attestations** of the ordering. One node serves many validators. |
| **BAM Validators** | Run the updated Jito-(Agave/Firedancer) client; **execute in strict FIFO** exactly as the node delivered — they *cannot* insert or reorder. |
| **Plugins (ACE)** | Programmable interfaces to the scheduler — apps define **custom sequencing logic** ("Application-Controlled Execution"). |

**The genuinely new part — TEE privacy + verifiability:**
- **Privacy:** txs are encrypted inside the enclave **until the moment of execution** — no pre-execution window for anyone (even the node operator) to read and front-run. AMD SEV-SNP, ~2-5% overhead.
- **Verifiability:** clients receive a TLS cert bound to an **AMD SEV-SNP attestation report**, chained to AMD's hardware root of trust — unforgeable without AMD's keys.
- **Attestations:** BAM Nodes emit signed, timestamped proofs of *exactly which code ordered which txs in what sequence* → a public, immutable audit trail.

**ACE & plugins (real but young):** maker cancel-before-take (tighter order-book spreads), just-in-time Pyth oracle updates, time-in-force orders, pre-confirmations, feeless SPL txs. Named partners: **Drift, Pyth, DFlow**. Plugins launched permissioned; "permissionless" is the stated end-state.

**Ecosystem:** Anza is shipping its own modular scheduler bindings; BAM currently bypasses them (expected to integrate *eventually* — Chorus One flags fragmentation risk). **Raiku** is an emerging competing block-builder ($13.5M raised) — BAM is the leader, not a monopoly.

---

## 7. How BAM changes neutrality — and the "neutrality = BAM" thesis

**The shift is real and directional:** legacy Block Engine = closed-source, single-operator, unverifiable. BAM = open-sourcing + TEE-encrypted (no front-running window) + cryptographically attested (verifiable fair ordering). On the **opacity → verifiability** axis, BAM is a genuine neutrality improvement.

**But "BAM = neutrality" is an overstatement** — three honest caveats:
1. **New trust assumptions, not zero:** you now trust AMD's hardware root + TEE integrity (SEV-SNP has CVE history; TEE monoculture risk; operators retain some censorship capability via timing analysis).
2. **MEV is relocated, not eliminated:** plugin authors / early node operators can accrue outsized value; attestations are post-execution with community (not yet programmatic-slashing) enforcement.
3. **Centralization pressure:** Ethereum PBS lesson — a handful of builders make most blocks. BAM's permissioned→permissionless rollout is a mitigation, not a guarantee.

**Net: BAM brings *verifiable execution-ordering* neutrality to the block. It does not touch *decision* neutrality** — whether the information a trade rests on is real. That gap is precisely Gecko's lane (§8).

---

## 8. Where Gecko sits — execution neutrality vs decision neutrality

The founder's framing was *"Gecko brings neutrality to Jito; neutrality is BAM."* The accurate version corrects two things:

**There are two distinct neutralities:**

| Axis | Question | Owner |
|---|---|---|
| **Execution neutrality** | Whose tx goes first? Was it ordered honestly? | **BAM** (TEE-encrypted, attested) |
| **Decision neutrality** | Is the market the decision rests on *real* — or bot-manufactured / wash-inflated / sniped / oracle-poisoned? | **Empty seat → Gecko's lane** |

**The one true sentence:**
> **BAM makes execution trustworthy; Gecko makes the decision trustworthy.**

**The proof they're orthogonal — Drift, April 2026, ~$285M.** A fake CVT token + a controlled oracle + a wash-traded price history fed the liquidation engine. **BAM would have ordered and attested that drain flawlessly.** The money still leaves. Perfect execution neutrality, zero decision integrity — the exact gap Gecko fills, just proven by a nine-figure exploit. (See [`solana-101.md`](./solana-101.md) on durable nonces / oracles.)

### Is the artifact a BAM plugin? No.

A BAM plugin governs **sequencing**, not decisions — forcing Gecko into a plugin would drag it *into execution and ordering liability*, breaking the standing line (**we verify; we do not execute, reorder, or custody**). It also mismatches latency (a plugin runs inside the ~400ms sub-slot auction; Gecko's behavioral fusion needs a 0-2s window of events) and has no issuer/decision entry point. Where Gecko actually sits:

| Tier | Artifact | Status | Relation to BAM |
|---|---|---|---|
| **Now** | **Off-chain pre-trade check** — `gecko.verify(token) → Receipt` (MCP + x402 + `/safety`), before the tx is built | **Shipping** | **Upstream** of BAM: `decision → Gecko Receipt → tx built → BAM orders + attests`. Additive, zero Jito dependency. |
| **Now (enforcement)** | **Token-2022 transfer-hook denylist** (issuer/launchpad side) — a PDA written before block 0; the hook reverts disallowed transfers *at execution* | Spec'd | **Downstream** of placement; the *program* enforces its own rule at exec — Gecko never sits in the auction. |
| **2027 (the rail)** | **Gecko Verification NCN** (restaking) — operators run the panel, stakers back honesty, slashing if a verdict contradicts its evidence | Not built | Rides Jito's **restaking** arm, **not** BAM plugins. The credible "official layer + rail" path. |

### The "official layer + rail" path (the founder's goal)

Real, but it's the **NCN / restaking** arm — not a BAM plugin. It mirrors the accepted **Blocksize RPC-NCN** pattern (verifiable RPC as an NCN) and is **JIP-fundable**. Build order: distribute now (MCP/x402, SendAI Agent Kit action, OKX Plugin Store) to create the demand → stand up the Verification NCN (~2027) to make Gecko a slashing-backed, economically-secured layer.

**Honest gap:** the technical seam is real; the **commercial seam is unvalidated** — there is **no named Jito-ecosystem design partner yet**. JTX is the cleanest proof-case but an uncertain channel (Jito's vertical-integration stance). Lead commercially with the off-chain Receipt + x402 now; build toward the NCN as the durability play.

---

## Sources (dated)

**Jito / BAM**
- [docs.jito.wtf — Low Latency Txn Send](https://docs.jito.wtf/lowlatencytxnsend/) — bundles, 8 tip accounts, `getTipAccounts`, `jitodontfront`. *Jun 2026, canonical.*
- [BAM — Introducing BAM](https://bam.dev/blog/introducing-bam/) — nodes/validators/plugins, TEE attestations, rollout. *Jul 21, 2025.*
- [Helius — Block Assembly Marketplace (BAM)](https://www.helius.dev/blog/block-assembly-marketplace-bam) — SEV-SNP, intra-block auction, ACE, fee model, critiques. *Jul 2025, best technical source.*
- [SolanaFloor — BAM live on mainnet, more builders coming](https://solanafloor.com/news/jito-s-bam-live-on-mainnet-but-more-block-builders-are-coming) — **Sep 25 2025 GA; >50% validators by Jun 5 2026; Raiku.** *2026.*
- [Chorus One — Thoughts on BAM](https://chorus.one/reports-research/thoughts-on-bam-the-new-block-building-architecture-introduced-by-jito) — neutrality/centralization analysis. *2025.*
- [Chainstack — Jito Explained](https://chainstack.com/jito-explained-bundles-tips-mev-solana/) — >95% stake, auction mechanics. *2026.*

**Removed mempool**
- [CoinDesk — Jito ends mempool function](https://www.coindesk.com/business/2024/03/08/solana-client-developer-jito-announces-end-of-mempool-function) — **Mar 8 2024 shutdown.**

**Drift (the orthogonality anchor)**
- [CoinDesk — How a Solana feature let an attacker drain Drift](https://www.coindesk.com/tech/2026/04/02/how-a-solana-feature-designed-for-convenience-let-an-attacker-drain-usd270-million-from-drift) — *Apr 2 2026* (press ~$270M; on-chain accounting ~$285M — cite the range).
- [Chainalysis — Lessons from the Drift Hack](https://www.chainalysis.com/blog/lessons-from-the-drift-hack/) — fake CVT + controlled oracle, not a code bug.

**Verify before any external pitch (DAO-governed / moves):** exact BAM fee split (JIP pending), Drift figure ($270M press vs $285M on-chain), per-plugin live-vs-planned status, BAM node-operator count, NCN-grant specifics.
