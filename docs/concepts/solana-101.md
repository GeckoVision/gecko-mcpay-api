# Solana 101 — Reference for Launch-Integrity, MEV, and Gecko's Decision Firewall

> Companion to `jito-101.md`. Jito internals (bundles, tip accounts, ShredStream subscription API, BAM/ACE) are covered there; this doc stops at the interface boundary.
>
> Audience: engineer who needs enough Solana mechanics to understand where block-0 sniping, wash trading, and Gecko's detection signals live on the stack.

---

## 1. Accounts + Programs Model

Solana separates **code** from **state** completely.

| Concept | What it is |
|---|---|
| **Program account** | Executable bytecode. Marked `executable = true`. Owned by the BPF Loader. Has no writable storage of its own. |
| **Data account** | Arbitrary bytes. Owned by a program. Holds all mutable state. |
| **System account** | Owned by the System Program. Holds lamport balances. |

Programs are **stateless**. Every instruction must pass in — as explicit account references — every account it will read or write. The runtime sees the full account set before execution begins.

**Critical constraint for Gecko**: programs have **no network I/O**. A program cannot make an HTTP call, query an API, or reach out during execution. On-chain enforcement must therefore work through pre-published on-chain state — e.g., a denylist stored in a PDA that a Token-2022 transfer hook CPI-reads on every transfer. This is the architectural foundation for any on-chain firewall component.

> **Gecko hook**: The "pre-published state" constraint is what makes an on-chain blocklist PDA viable and what makes a real-time external API call impossible. Off-chain detection (Gecko) fires before the tx is landed; on-chain hooks enforce after detection gates passage.

---

## 2. No Mempool / Gulf Stream

Solana has **no global mempool**. Transactions are forwarded directly to the current and next-scheduled leaders via the Gulf Stream protocol — not gossiped broadly across the network.

Consequences:
- There is no canonical pending-transaction pool that an outside observer can watch.
- Front-running via mempool inspection (the Ethereum model) does not apply to Solana as-is.
- Speed advantage shifts to actors who (a) are close to the leader, (b) have stake-weighted QoS (§5), or (c) use Jito bundles to get direct bundle submission.
- "Mempool sniping" on Solana means intercepting a tx before it lands in a block — possible via RPC node access, Jito ShredStream, or validator co-location, not a public mempool.

> **Gecko hook**: No mempool = no pre-execution public visibility window. Snipe detection must work from on-chain evidence (block-0 tx shape, bundle structure, timing relative to mint) rather than mempool observation. This is why the detection layer reads landed transactions.

---

## 3. Leaders, Slots, PoH, and Block Production

### Proof of History (PoH)
A verifiable delay function that produces a monotonically increasing, timestamped counter. Validators use PoH as a shared clock, enabling them to agree on the ordering of events without synchronous communication.

### Slots and Block Production
- One **slot** = one opportunity for the current leader to produce a block. Target duration: **~400 ms**.
- Not every slot produces a block (leaders can skip); current skip rate is ~5%.
- The **leader schedule** is computed at epoch boundaries (~2 days) from stake-weighted randomness seeded by the PoH tick height. All validators know the schedule in advance.
- Leaders rotate every **4 consecutive slots** within an epoch.
- A validator's probability of being leader in a given slot is proportional to its **delegated stake**.

> **Gecko hook**: The known-in-advance leader schedule is what makes bundle submission to the current leader viable (Jito). It is also what makes pre-scheduled snipe transactions possible — an attacker knows who the leader is and can target packet delivery to them.

---

## 4. Turbine — Block Propagation via Shreds

After a leader produces a block, it must propagate ~MTU-sized fragments called **shreds** to all other validators.

**Turbine mechanics:**
- Block data is split into shreds and broadcast through a **stake-weighted tree** (fanout = 200 per layer, producing a 2-3 hop tree for the ~1,500 active validators).
- Validators with **higher stake** receive shreds earlier in the tree and therefore vote sooner — reinforcing their economic advantage.
- Shred identity is deterministic: each shred is addressed by `(slot, shred_index)` plus a tree assignment seeded by `(leader_id, slot, shred_index, type)`.

**ShredStream (Jito boundary):**
Jito's ShredStream service delivers raw shreds **directly** from producing validators, bypassing slower Turbine hops. This shaves hundreds of milliseconds off time-to-first-shred for subscribers. See `jito-101.md` for the subscription/integration details.

> **Gecko hook**: ShredStream is the earliest possible signal of a new block's content — before the block is fully confirmed. Detector latency vs. attacker latency is a function of position in the shred tree. Gecko's detection latency is benchmarked against ShredStream delivery, not RPC `confirmed` polling.

---

## 5. Fee Market

### Base Fee
- **5,000 lamports per signature** (fixed; does not scale with demand).
- Split: **50% burned, 50% to validator**.

### Priority Fees (Compute Unit Price)
- Expressed as micro-lamports per compute unit (CU).
- Total priority fee = `ceil(cu_price × cu_limit / 1_000_000)` lamports.
- Post-**SIMD-0096** (live on mainnet, February 2025): **100% of priority fees go to the validator**; no burn. This eliminated the validator incentive for off-chain side-deals.
- **SIMD-0123** (March 2025): automated distribution of validator priority-fee revenue to SOL stakers/delegators.

### Local (Per-Account) Fee Markets
Solana's scheduler does not have one global fee market — it has **per-account markets**. Congestion on one hot account (e.g., a popular AMM pool or a new token's mint) drives fees for transactions touching that account, without affecting unrelated accounts. This means fee spikes on a freshly-launched token do not spill over to SOL transfers.

### Stake-Weighted QoS
Each validator's **TPU (Transaction Processing Unit)** allocates ingress bandwidth proportional to the sender's stake weight. A validator with 0.5% of stake can claim up to 0.5% of leader packet capacity. Senders without stake can use Jito's block engine or high-reputation RPC providers that negotiate QoS on their behalf.

> **Gecko hook**: Priority fees are a **legal, buyable speed edge**. A block-0 snipe works by: (1) pre-preparing the buy transaction, (2) submitting with high priority fee + Jito bundle the moment the token mint transaction hits the mempool / ShredStream feed, (3) landing in the same block as the launch. The local fee market means the sniper's high fee only competes against others touching that specific new token account — not the whole network.

---

## 6. Commitment Levels

| Level | Meaning | Timing | Rollback risk |
|---|---|---|---|
| **processed** | Block received by leader, included in a block the node knows about; may not be on the majority fork | ~0.4s | ~5% (block could be orphaned) |
| **confirmed** | ≥66% of stake-weighted validators have voted on the block (optimistic confirmation) | ~0.6s | Essentially zero in practice; no confirmed block has ever reverted on mainnet |
| **finalized** | ≥66% stake voted AND 31+ subsequent confirmed blocks built on top | ~13s | Cryptographically irreversible |

**Why `confirmed` is the right signal for a detector:**
- `processed` has meaningful rollback risk and should not trigger an irreversible action.
- `finalized` is ~13 seconds too slow to be actionable for block-0 detection.
- `confirmed` gives strong finality (~0.6s) with effectively zero historical revert rate, making it the correct commitment level for Gecko's detection pipeline to act on.

> **Gecko hook**: Gecko emits a verdict at `confirmed`. An on-chain enforcement hook (Token-2022 transfer hook) enforces at execution time — which by definition is within the block, before any confirmation. Off-chain signals use `confirmed` as the earliest trustworthy state.

---

## 7. Validator Clients

| Client | Maintainer | Status (mid-2026) |
|---|---|---|
| **Agave** (formerly solana-labs/solana) | Anza (ex-Solana Labs) | Dominant; ~80% of mainnet validators |
| **Frankendancer** | Jump Crypto | Firedancer networking frontend + Agave execution backend. Live on mainnet since Sep 2024. ~10% of validators. |
| **Firedancer** | Jump Crypto | Full independent implementation. Live on mainnet Dec 2025, ~20% of validators by Q2 2026. Targets 1M+ TPS. |

**Upcoming — Alpenglow** (announced 2026): consensus-layer overhaul targeting ~150ms deterministic finality. Not yet live; would replace the current Tower BFT + Turbine combination.

> **Gecko hook**: Client diversity matters for detection robustness — a signal that relies on Agave-specific RPC behavior may behave differently against Firedancer nodes. Helius and other RPC providers abstract this, but it is a dependency to track as Firedancer market share grows.

---

## 8. Token-2022 / Token Extensions

Token-2022 is the successor SPL token program (`TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb`). Extensions relevant to launch integrity:

| Extension | What it does | Gecko relevance |
|---|---|---|
| **Transfer Hook** | On every transfer, the runtime CPI-calls a custom program you specify. That program can read arbitrary on-chain state and reject (error) or allow the transfer. | The **only** on-chain enforcement primitive that can block a transfer at execution time based on pre-published state (e.g., a denylist PDA). |
| **Mint Authority** | Controls who can mint new supply. Revocation pattern: set to `None` post-launch to cap supply. | Failure to revoke = ongoing inflation risk. A Gecko signal. |
| **Freeze Authority** | Ability to freeze individual token accounts (halt transfers for a specific holder). Distinct from transfer hook. | Presence of non-null freeze authority on a new token = significant rug risk. A Gecko signal. |
| **Permanent Delegate** | Grants one address the ability to transfer or burn any holder's tokens. | Extreme rug risk. A Gecko high-severity signal. |
| **Metadata Pointer** | Points to a metadata account stored on-chain (or off-chain). | Inconsistency between on-chain metadata and off-chain claims = a deception signal. |
| **Transfer Fee** | Enforces a configurable fee on every transfer, captured in the token account. | Used by legitimate projects for revenue; also used by honeypots to drain exit liquidity. |

**How transfer hooks work:**
1. Caller submits a token transfer.
2. Token-2022 program sees `transfer_hook` extension on the mint.
3. Runtime **pauses** the transfer and CPIs to the hook program.
4. Hook program reads on-chain accounts (e.g., a denylist PDA, a verification registry).
5. Returns `Ok` or `Err` — the original transfer succeeds or fails accordingly.
6. Hook program **cannot** make external calls (see §1 constraint).

> **Gecko hook**: Transfer hooks are the on-chain enforcement surface. A Gecko-integrated mint would have a transfer hook that reads a `SnipeProtection` PDA written by an authorized oracle (Gecko). Off-chain detection fires; on-chain hook blocks. The hook cannot call Gecko's API — it reads a pre-written PDA.

---

## 9. Address Lookup Tables (ALTs) and Durable Nonces

### Address Lookup Tables (ALTs)
ALTs allow a transaction to reference up to 256 frequently-used addresses by index (1 byte) rather than full 32-byte pubkey. This extends the practical transaction account limit from ~35 to ~64 unique accounts per transaction.

**Detection relevance:**
- A sophisticated snipe rig often pre-creates ALTs containing all the accounts needed for a rapid buy (DEX pool, token accounts, slippage configs). Observing that an ALT was created hours before a launch by the same wallet funding the snipe is an **identity tell** — a signal Gecko's B1 gate uses.
- ALT creation requires a separate `create_lookup_table` + `extend_lookup_table` transaction sequence, which is on-chain and observable.

### Durable Nonces
A durable nonce replaces the normally-expiring blockhash in a transaction with a fixed value stored in a special nonce account. The transaction remains valid indefinitely until the nonce account is advanced.

Legitimate use cases: hardware wallets, offline signing, multisig workflows requiring async approval.

**Security risk (the Drift exploit, April 2026):**
- An attacker obtained signatures from two of five Drift Security Council members on what appeared to be routine admin transactions.
- Those transactions were actually durable-nonce signed, allowing the attacker to hold them for weeks.
- When a new council member was swapped in and separately approved what they thought was an unrelated transaction, the attacker now had a fresh 2-of-5 threshold.
- All pre-signed transactions were submitted within minutes, draining ~$270M from Drift.

**Why this matters for Gecko:** Durable nonces are also used to pre-sign admin/upgrade transactions for a new token project before the launch. If the nonce account is controlled by a party other than the visible team, it is a pre-signed "exit" mechanism. Presence of durable-nonce accounts associated with a launch wallet is a high-severity Gecko detection signal.

> **Gecko hook**: ALT pre-creation = shared snipe rig infrastructure (B1 signal). Durable nonce accounts associated with token admin wallets = pre-authorized drain mechanism (I2 / admin-risk signal).

---

## 10. Oracles — Pyth Pull Model

Pyth Network is the dominant oracle on Solana. The **pull model** (live on Solana mainnet, 500+ price feeds):

- Price data is produced by ~100 institutional publishers on the Pythnet appchain.
- Aggregation uses a confidence-weighted median, published every ~400ms.
- Programs that need a price **pull** the latest signed price update (from a Wormhole cross-chain message) into the target chain and verify the Wormhole guardian signatures on-chain before reading.
- Oracle Integrity Staking (OIS): publishers stake PYTH tokens; inaccurate data triggers slashing.

**Oracle manipulation vectors relevant to launch risk:**
1. **Thin-book manipulation**: a new token's oracle price can be manipulated if the price feed is based on a single DEX pool with shallow liquidity (attacker provides the liquidity, sets the price).
2. **Oracle lag at launch**: in the first seconds after a token launches on a DEX, the oracle may lag actual market price, creating a window for arbitrage and price-impact attacks.
3. **Missing oracle coverage**: most new meme/launch tokens have no Pyth feed at launch. Price-dependent protocols that accept them as collateral are blind to actual value.

> **Gecko hook**: Gecko's oracle_voice surfaces oracle price versus on-chain DEX price divergence as a launch-risk signal. A new token with no Pyth coverage and concentrated liquidity is a category-1 price-manipulation risk.

---

## Quick Reference: Stack Layer → Gecko Signal

| Layer | Mechanism | Gecko Touchpoint |
|---|---|---|
| Block production | 400ms slots, known leader | Pre-land detection must beat leader |
| No mempool | Gulf Stream direct | Detection from landed txs + ShredStream |
| Fee market | Local per-account + priority | High CU price on new token = snipe tell |
| Turbine / ShredStream | Shred propagation | Earliest signal source for block-0 detection |
| Commitment | `confirmed` @ ~0.6s | Verdict emission level |
| Token-2022 hooks | CPI on transfer, reads PDA | On-chain enforcement surface |
| ALTs | Pre-created account bundles | Shared-rig identity fingerprint |
| Durable nonces | Indefinitely-held admin sigs | Pre-signed drain mechanism |
| Pyth oracles | Pull model, 400ms cadence | Price divergence / missing coverage risk |

---

## Sources

- [Solana Accounts Documentation](https://solana.com/docs/core/accounts) — official, accessed June 2026
- [Solana Programs Documentation](https://solana.com/docs/core/programs) — official, accessed June 2026
- [Solana Transaction Fees](https://solana.com/docs/core/fees) — official, accessed June 2026
- [The Solana Programming Model — Helius](https://www.helius.dev/blog/the-solana-programming-model-an-introduction-to-developing-on-solana) — 2024
- [Solana's Gulf Stream — Helius](https://www.helius.dev/blog/solana-gulf-stream) — 2024
- [Solana Fees in Theory and Practice — Helius](https://www.helius.dev/blog/solana-fees-in-theory-and-practice) — 2024/2025
- [Solana Commitment Levels — Helius](https://www.helius.dev/blog/solana-commitment-levels) — 2024
- [Turbine Block Propagation — Helius](https://www.helius.dev/blog/turbine-block-propagation-on-solana) — 2024
- [Solana Shreds — Helius](https://www.helius.dev/blog/solana-shreds) — 2024
- [Turbine Block Propagation — Agave Docs](https://docs.anza.xyz/consensus/turbine-block-propagation) — official, accessed June 2026
- [Token Extensions: Transfer Hook — Solana Developers](https://solana.com/developers/guides/token-extensions/transfer-hook) — official, accessed June 2026
- [SIMD-0096: Validators Receive 100% Priority Fees — blocmates](https://www.blocmates.com/news-posts/simd-0096-passes-solana-validators-to-receive-100-priority-fees) — May 2024
- [SIMD-0096 Deep Dive — Medium](https://medium.com/@moonsimran/simd-0096-a-deep-dive-into-solanas-fee-structure-overhaul-8e51f3549042) — 2024
- [Mastering Solana Scaling: Priority Fees, Local Fee Markets — Bitmorpho](https://bitmorpho.com/en/article/mastering-solana-scaling-priority-fees-local-fee-markets-and-cu-optimizations) — 2025
- [Address Lookup Tables — Solana Developers](https://solana.com/developers/guides/advanced/lookup-tables) — official, accessed June 2026
- [Durable Nonces — Solana Developers](https://solana.com/developers/courses/offline-transactions/durable-nonces) — official, accessed June 2026
- [How Drift Attackers Drained $270M Using Durable Nonces — CoinDesk](https://www.coindesk.com/tech/2026/04/02/how-a-solana-feature-designed-for-convenience-let-an-attacker-drain-usd270-million-from-drift) — April 2026
- [Pyth Pull Oracle Launches on Solana — Pyth Network Blog](https://www.pyth.network/blog/pyth-network-pull-oracle-on-solana) — 2024
- [Firedancer Live on Solana Mainnet — Unchained](https://unchainedcrypto.com/jump-cryptos-firedancer-goes-live-on-solana-mainnet/) — December 2025
- [Solana Slot Time Explained — RPC Fast](https://rpcfast.com/blog/solana-slot-time-explained) — 2025
- [Solana ShredStream — Jito Labs Docs](https://docs.jito.wtf/lowlatencytxnfeed/) — official, accessed June 2026

---

**Low-confidence / watch flags (June 2026):**
- Alpenglow consensus finality target (~150ms) is announced but not yet live; timeline subject to change.
- Firedancer's 20%+ validator share figure is from Q2 2026 operator data; changes rapidly.
- SIMD-0096 burn ratio (100% priority fees to validators, no burn) is confirmed live; SIMD-0123 (staker distribution) passed March 2025 but the exact distribution mechanics are validator-implementation-dependent.
- The Drift $270M figure is from initial reporting (April 2026 CoinDesk); total may differ in final post-mortems.
