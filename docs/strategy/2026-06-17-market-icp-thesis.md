# Gecko — Market, ICP & Thesis (2026-06-17)

Synthesis of two research lenses — `solana-researcher` (market structure, problem, ICPs, why-unsolved, distribution) + `business-manager` (TAM/SAM/SOM, unit economics, WTP, distribution economics). Every number tagged sourced / derived / guess in the source reports; the defensible ranges are below.

---

## 1. The problem (crisp)
**Autonomous trading agents commit capital on price/volume/liquidity/oracle data they cannot verify wasn't manufactured. There is no agent-native, pre-trade layer that answers: "is the data this trade rests on real?"** This is "Plane C — data integrity," distinct from Plane A (static contract risk: RugCheck/GoPlus) and Plane B (execution safety: Blockaid/AgentGuard — "will this drain my wallet?").

## 2. The solution
Gecko = the **pre-trade data-integrity gate an agent calls before it acts (BYOA)** — wash-trade / bot-inflated-price / fake-mcap / oracle-deviation detection → a graded `clean | suspicious | manipulated` verdict with **grounded evidence + surviving dissent**. Two tiers: fast deterministic `/safety` (sub-second) + considered `/trade_research` verdict. The "decision firewall."

## 3. Why it matters / why now
- **Drift Protocol — $285M (Apr 1 2026).** Attacker minted CVT, seeded ~$3K Raydium liquidity, **wash-traded a ~12-day fake price history** into a controlled oracle, got CVT whitelisted as collateral, drained $285M in 12 min. No tool flagged "this oracle's price history is 12 days old, sourced from a $3K pool, 99% circular volume." That is exactly Gecko's signal. *The canonical proof case.*
- **Prevalence:** 67% of a 30K-DEX-pool sample manipulated (Solidus); Solana = most-manipulated chain — **14.2% of Solana revenue from wash trading** (vs 2% ETH), 183 manipulated tokens; 82.8% of high-return tokens show artificial growth (arXiv 2507.01963).
- **Timing:** 20K+ active on-chain agents (+300% YoY); 65% of agentic payments on Solana; agents ≈30% of top-pool DeFi TVL (Chainlink/Ark, May 2026); 15M+ agent-initiated Solana payments. **GENIUS Act (2026) = strict liability on agent deployers** for trades made on manipulated data → "nice-to-have" becomes "legally defensible." The buyer (autonomous agent at scale) **didn't exist before 2025**.

## 4. The market (honest sizing)
- **Snapshot TAM today: $0.1–12M/yr** (≈10K Solana trading agents × sub-cent calls). Small — say so.
- **Growth case (24mo): $26–130M.** SAM **$8–50M**. SOM (24mo, B2B-led): **$80K–2.5M**.
- Comparable: GoPlus does **$4.7M revenue / 717M monthly calls** on *static* token checks alone → the category spend is real; we carve the data-integrity sub-slice.
- **Do NOT put $100M+ TAM in the PRD.** The bet is the growth slope (x402 went 0→165M tx in ~3 quarters), not the snapshot.

## 5. ICPs (priority order)
1. **Agent-framework builders** (SendAI/Solana Agent Kit, ElizaOS, OKX OnchainOS, Griffain) — **highest leverage, the forcing function.** One embed = thousands of downstream agents; a high-profile data-exploit through their SDK kills their dev reputation, so they're incentivized to bundle a data-integrity primitive. Conversion: co-branded SDK plugin + x402 rev-share.
2. **Autonomous bot devs** (~1–3K active on SAK/ElizaOS/OKX Skills) — direct payer, moderate WTP; forced by a loss or a framework mandate. Free tier (100/day) → x402 per-call.
3. **DeFi protocols with collateral-whitelisting / new-listing risk** (Kamino, Marginfi, perps, Raydium/Meteora listings) — **highest ACV ($10–100K/yr)**, long cycle; post-Drift they are *actively shopping* for TWAP-validation + new-asset screening (the Drift post-mortem names exactly this). Reachable via audit firms + Solana security WG.
4. **Agent marketplaces / skill stores** (OKX Skill Store, frames.ag, Bazaar) — partnership/platform deals, not self-serve.

## 6. Why nobody's fixed it
1. **The buyer didn't exist at scale until 2025–26** — agents committing capital at machine speed.
2. **Security builders defaulted to the obvious execution layer** (Blockaid/AgentGuard: "will this kill my wallet?"). The data-layer attack is subtler — the agent made a *rationally defensible* decision; the *data itself* was the attack. Requires market-microstructure + agent-architecture expertise simultaneously.
3. **Data feeds (Helius/Bitquery/Birdeye trade graphs + oracle provenance) AND distribution rails (MCP + x402) only became viable mid-2025, together.** Institutional surveillance (Solidus/Chainalysis/Kaiko) has the *method* but built it retrospective / enterprise / human-operated — never a <100ms per-call agent API. It was an *attention gap*, not a capability gap — and Drift converted attention.

## 7. The distribution problem (yes — the binding constraint)
Both lenses converge: **direct-to-indie-dev per-call is a trap.** Micro-price can't fund discovery; $3/mo accounts can't bear any CAC; x402 micropayment demand is *industry-wide unproven today* (CoinDesk "demand isn't there yet"). Five hard parts:
1. Devs don't shop for safety pre-deployment → reach them **through the framework**, not directly.
2. **The "no" problem** — a block has negative immediate value; it'll be disabled within a week unless the false-positive rate is near-zero from day one.
3. **Cold-start detection quality** — no calibration data on day 1; heuristics catch the obvious cases, miss novel ones.
4. **Chicken-egg** — frameworks won't embed until quality is proven; quality needs deployment.
5. **Free alternatives commoditize the obvious cases** → negative selection (early payers are those who already got burned).

**The wedge = framework-level embedding (the Snyk / GoPlus playbook).** Win **1–3 framework integrations** (SAK / ElizaOS / OKX OnchainOS) so Gecko is the default pre-trade call → they carry the long tail. **Partnership sales (a handful), not customer sales (thousands).** MCP + x402 solve "try it," not "make it default."

**Biggest single risk: GoPlus.** 80+ enterprise subs, 717M calls/mo, already x402 + AgentGuard — one product decision from adding wash/oracle analysis and displacing us with *their* distribution. **Mitigation:** go deep on detection (behavioral wash-graph + circular-wallet tracing + oracle-provenance — a genuinely different engineering problem than static checks) **and close a framework partnership before they copy the feature set.**

## 8. Bottom line — what to do
- **Revenue = `/trade_research`** (90–96% margin, concrete in-the-moment WTP). **`/safety` free = funnel + moat + cache-warmer**, not a business (~$3/agent/mo).
- **First revenue (manual):** the 2 warm leads + one **protocol risk-team** deal (ICP 3 — high ACV, post-Drift demand).
- **Scale:** ONE framework embed (SAK or ElizaOS).
- **Moat:** detection depth (wash-graph + oracle provenance) + adversarial-debate verdict + decision receipts — *fused*, hard to bolt onto a scanner.
- **Name the risk in the PRD:** micropayment demand unproven; GoPlus pivot. Model works only if cache-then-charge holds margins + revenue concentrates in `/trade_research` + distribution is platform-embedded.

*Pairs with [`2026-06-16-architecture-and-evolution.md`](2026-06-16-architecture-and-evolution.md). Sources in the two agent reports (Drift post-mortems, Solidus, arXiv 2507.01963, Chainalysis x402, GoPlus H2-2025, SAK/ElizaOS/OKX metrics).*
