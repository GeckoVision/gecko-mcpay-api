# Profile Thesis — Web3/Identity Lens

**Date:** 2026-05-01
**Author:** web3-engineer
**Verdict:** Thesis holds. Identity is the load-bearing primitive — get it wrong and the whole reputation graph is sybil-farmed within a sprint of launch.

---

## 1. Smallest workable on-chain identity primitive for V1

**Pick: EAS on Base, with self-attested + observed counter as the V0 fallback.**

Comparison:

- **SBT per profile type** — clean semantics ("you hold a JUDGE token"), but minting is a governance problem we don't want in V1. Who mints? Who revokes? Token-per-type forces premature taxonomy.
- **EAS** — schema-flexible. We define a `gecko.profile.v1` schema (`{wallet, profile_type, issuer, evidence_uri}`) and a `gecko.citation.v1` schema (`{cited_wallet, verdict_id, profile_type, weight}`). Attestations are cheap on Base, revocable, composable. Self-attestations and third-party attestations use the same schema with different `issuer` semantics.
- **Lens / Farcaster** — strong social graph but Lens is Polygon-native and Farcaster identity (FID) is off-chain Hub-resolved. Useful as *signal feeders into* our EAS schema, not as the primitive itself. Farcaster FID linkage via verified-address proofs is the cheapest "this human exists" check we'll get.
- **Self-attested + observed (no chain)** — the right V0. Ship the cited-precedent counter in Postgres with a `wallet -> citation_count` table *now*; the EAS attestations become the cryptographic shadow of that table later. Same data model, deferred settlement.

The "cited 47 times in DeFi BUILD verdicts that later shipped" claim is **an aggregation over EAS citation attestations issued by Gecko's verdict-publisher wallet.** Gecko itself becomes the issuer-of-record. The wallet that signs verdicts is the trust root.

## 2. Multi-chain scope

**Single-chain on Base for V1. Don't bridge.**

publish.new is Base. Coinbase x402 facilitator targets Base + Solana, but contributor identity should anchor where contributors already live (Base, via publish.new wallets). Solana stays the payments rail; Base stays the identity rail. These don't need to be the same chain.

If a Solana-native creator (Superteam, solana-claude orbit) wants reputation, we issue an EAS attestation on Base referencing their Solana pubkey as a string field. No bridge, no wrapped tokens, no LayerZero. Cross-chain is a V3 problem when reputation has economic value worth bridging.

## 3. Verification semantics

A Gecko-issued citation attestation proves exactly one thing: **"Gecko's verdict pipeline cited this wallet as a `<profile_type>` source in verdict `<verdict_id>` at block `<n>`."** Nothing more. It does *not* prove the wallet was a real Colosseum judge.

Profile-type claims are layered:
- **Tier 0 (self-claimed):** wallet posts a `gecko.profile.v1` attestation with `issuer == self`. Free, noisy, no weight in routing.
- **Tier 1 (observed):** Gecko issues citation attestations as the verdict pipeline runs. Reputation = sum of Tier-1 attestations weighted by downstream verdict outcomes.
- **Tier 2 (peer-quorum):** N existing Tier-1 contributors of the same profile type co-sign a peer attestation. V2.
- **Tier 3 (institutional):** Colosseum, a16z, Paradigm wallet signs. V3, may never happen.

Routing only trusts Tier-1+ for ranking. Tier-0 self-claims are visible but unweighted.

## 4. Sybil resistance

Stake-weighted attestations + Farcaster FID linkage. Specifically: to publish a Tier-0 profile claim that's eligible to *accrue* Tier-1 reputation, the wallet must (a) have a verified Farcaster FID, OR (b) post a refundable USDC bond (10 USDC) slashable on detected sybil behavior. **Worldcoin / PoH** is overkill and chills contributor signup. **KYC** kills the permissionless pitch. FID-gating + bond is the right floor — it costs ~$0 to a real contributor (they already have a Farcaster account) and ~$1000 to spin up 100 fake PMs.

Reputation decay (half-life ~180 days) further deflates dormant farmed wallets.

## 5. Sprint 15+ ticket

**S15-IDENTITY-01: Postgres-backed contributor reputation ledger (EAS-shaped schema, no chain writes yet).**

- Add `contributor_profiles` and `contributor_citations` tables matching the planned EAS `gecko.profile.v1` / `gecko.citation.v1` schemas field-for-field.
- On verdict publish, the pipeline writes one row per cited wallet to `contributor_citations` with profile_type, verdict_id, weight.
- Read API: `get_reputation(wallet, profile_type) -> {citation_count, recency_weighted_score, tier}`.
- Acceptance: backfill from last 30 verdicts produces non-empty reputation for ≥10 wallets; schema field names match a draft EAS schema doc; `gecko-mcp doctor` reports `identity: postgres-shadow`.
- Estimate: 4 days. No chain calls, no mainnet, stub-compatible.

This is the migration path: ship the ledger, validate the data model on real verdicts, then in Sprint 17+ flip a switch that mirrors writes to EAS on Base. Same shape, deferred settlement.
