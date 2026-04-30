# Bazaar as composer — Gecko's monetization vectors

**Date:** 2026-04-30
**Trigger:** user observation that CDP Bazaar isn't just a discovery surface — it's a **composability substrate**. Apps can be built that consume N x402 providers (Amadeus, FlightAware, Skyscanner, etc.) and present a single pre-validated answer.

---

## The reframe

Today's mental model: *"Gecko is an MCP that does product validation."*

User's reframe: *"Gecko is an MCP that composes other paid services to do product validation."*

These look the same from outside. They diverge sharply in what Gecko actually owns:

| Old model | Composer model |
|---|---|
| Gecko owns Reddit ingestion | Gecko routes to a Bazaar Reddit provider |
| Gecko owns GitHub search | Gecko routes to a Bazaar GitHub provider |
| Gecko owns twit.sh judge ingestion | Gecko routes to a Bazaar Twitter/X provider |
| Gecko owns the LLM debate | **Gecko owns the LLM debate.** |
| Gecko owns the verdict synthesis | **Gecko owns the verdict synthesis.** |

The composer model says: **Gecko's moat is the adversarial layer + the verdict + the citations**, not the data ingestion. Data ingestion is a commodity. Bazaar makes it a buyable commodity.

This is a much sharper position. Less code to maintain, more leverage on quality.

---

## The five monetization vectors

### Vector 1 — Direct listing revenue (Sprint 12)
Already in the Sprint 12 plan. List `gecko_research` + `gecko_plan` in CDP Bazaar. Every call from a Bazaar-discovering agent pays gecko-api directly. **Margin: 79–88%** on the existing tier table.

### Vector 2 — Pro+ tier with Bazaar source bundling
Ship a `--tier=pro-plus` (or rename Pro to bundle). Same adversarial debate, but the RAG context is pre-loaded from N Bazaar providers chosen by the idea classifier. User pays one price; Gecko marks up each bundled call.

Worked example for a travel-startup idea:
- Bazaar Amadeus call: $0.05 (flights data)
- Bazaar FlightAware call: $0.05 (flight reliability)
- Bazaar Skyscanner-equivalent: $0.05 (consumer pricing)
- Bazaar competitor analyzer: $0.05
- Free sources still on (HN, Reddit, GitHub): $0.00
- LLM debate (existing Pro): ~$0.10
- **Gecko cost of goods: ~$0.30**
- **Sticker: $1.50**
- **Margin: 80%** — same shape as today

### Vector 3 — Vertical validation suites
Idea-classifier picks the right Bazaar services per category. Each vertical becomes a productized offering:

| Vertical | Bundled providers (examples) | Sticker |
|---|---|---|
| Travel startup | Amadeus, FlightAware, Skyscanner, hotel APIs | $2.00 |
| Fintech startup | Plaid-equivalent, regulatory data, KYC providers | $2.50 |
| DeFi protocol | Helius DAS, DefiLlama, on-chain data | $1.00 (already partly built) |
| SaaS startup | G2-equivalent, Producthunt, Crunchbase-equivalent | $1.50 |

Marketing line: *"Don't pick the right APIs. Tell us your idea; we pick them, run them, judge them."*

This is the **"agentic founder workspace"** the thesis hinted at, made concrete via Bazaar.

### Vector 4 — Gecko-as-orchestrator (V3)
Bigger ambition: user describes an idea in plain English. Gecko's idea classifier (already exists) picks N Bazaar services. Gecko routes calls, synthesizes, returns the verdict. **The user never touches the Bazaar.**

This is the thesis macro vision restated: *"validation as authorization policy."* Gecko approves the spec, then provisions the budget for the downstream agents to execute. Bazaar is the menu the agents pick from.

Monetization: Gecko earns the markup per call + a base orchestration fee. Possibly also a referral cut from listed providers if they support that (today's x402 spec doesn't have that primitive — would need to be off-chain settled).

### Vector 5 — "Validated by Gecko" certification (later)
Inverse direction: Bazaar listings get Gecko-stamped quality scores. Apps pay Gecko to run their own service through our adversarial review and earn the stamp. Consumers trust the stamp; agents prefer stamped services. We become the trust layer above Bazaar's automated quality ranking.

This is far-future. Requires brand strength we don't yet have.

---

## What this means for Sprint 12 vs Sprint 13+

**Sprint 12 (already planned):** stay focused on **Vector 1**. List Gecko in Bazaar. Add CDP Facilitator settlement. Get the first paid Bazaar call landed. Don't expand scope.

**Sprint 13 (proposed):** **Vector 2** — ship Pro+ tier that consumes 1-2 high-quality Bazaar sources as RAG context. Pick travel OR fintech as the first vertical (whichever has the best Bazaar coverage). Validate the markup math.

**Sprint 14+:** **Vector 3** — vertical suites. Requires a category-aware idea classifier, per-vertical prompts, per-vertical eval fixtures. Multi-sprint arc.

**Sprint 16+:** **Vector 4** — full orchestrator. Requires per-call routing, budget management, settlement reconciliation across N providers. The thesis macro vision.

---

## Risks

1. **Latency budget.** Each bundled Bazaar call adds 200-2000ms. A vertical suite hitting 5 services serially is 5-10s slower than today. Need parallel calls (asyncio.gather) + per-call timeouts.

2. **Failure modes multiply.** N providers = N possible failures. Need graceful degradation — if Amadeus is down, the verdict still emits, just with a noted gap. The adversarial layer is uniquely good at this because the critic agent can flag missing data as a real critique.

3. **Margin compression with thin markups.** If Bazaar providers race to cheap prices, our markup gets squeezed. Mitigation: lean on the adversarial layer + verdict synthesis as the differentiated value, not the data itself.

4. **Provider reliability isn't ours to fix.** OrbisAPI proxies have <5 calls/30d — they're not battle-tested. Bundling them risks shipping 4xx/5xx cascades. Mitigation: only bundle providers with proven volume + health-checked uptime.

5. **Bazaar route consolidation.** Documented in `cdp-bazaar-2026-04-30.md` — bare-UUID path segments collapse. Affects our **own** listing more than our consumption, but worth checking provider routes too.

---

## Decision summary

- **Vector 1 (list in Bazaar)** — committed in Sprint 12.
- **Vector 2 (Pro+ tier with Bazaar sources)** — propose for Sprint 13. Pick one vertical to start.
- **Vectors 3-5** — strategic option set, document but don't commit.
- **Wallet neutrality** — already in Sprint 12. No change.
- **Don't migrate off frames.ag** — the Solana flow stays. Bazaar is additive.

The composer reframe is the strongest positioning move available. It says: Gecko isn't a tool that competes with Reddit/GitHub/Tavily — it's the **judgment layer** that turns commodity data into signed verdicts. The Bazaar makes that explicit.
