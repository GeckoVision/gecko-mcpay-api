# Theme 2 expansion — Paragraph + publish.new + verdict-as-artifact

**Date:** 2026-04-30
**Trigger:** user surfaced major Paragraph platform updates: hosted MCP server (`mcp.paragraph.com`, 18 tools), `publish.new` marketplace (digital artifacts at $price unlocked via x402), and the framing post `paragraph.com/@blog/your-work-paid-for-by-agents`.

---

## What changed since the original Theme 2 plan

Original Theme 2 plan (Sprint 14 in our roadmap synthesis): **build a custom Paragraph extractor that pays creators when ingesting their posts.** Days of work to integrate the API, handle creator-wallet attribution, plumb payments.

What's actually available now:

### 1. Paragraph hosted MCP server

`https://mcp.paragraph.com/mcp` — 18 tools (posts, publications, subscribers, coins, search, feed, users). No installation, browser-auth via Paragraph account.

**Implication:** Gecko's pipeline can consume Paragraph posts via MCP-to-MCP, not custom extractor. Drop the extractor scope; replace with thin MCP client wrapper. **Sprint 14 effort drops from ~5 days to ~1 day for the inbound side.**

### 2. publish.new — generalized digital-artifact marketplace

`https://publish.new` — anyone publishes content (markdown OR file, up to 100MB) at a USD price; agents/users pay $price USDC via x402 (tempo / base / mainnet) to unlock. URL slug → API → x402 buy. Idempotent buying. Already operational.

**Implication:** publish.new is the actual implementation surface for **"the verdict as a shared trust artifact"** — the deeper-thesis claim from `bazaar-deeper-thesis-2026-04-30.md`. We don't need to build a verdict-publishing surface ourselves; we ship our verdicts AS publish.new artifacts.

### 3. The framing already exists

`paragraph.com/@blog/your-work-paid-for-by-agents` — Paragraph is publicly framing creator content as agent-payable. The vocabulary, the buyer profile, the per-call pattern: all aligned. Co-marketing is plausible (Gecko + Paragraph joint launch).

---

## What this enables (4 surfaces)

### Surface A — Gecko consumes Paragraph posts as paid sources

Pipeline calls `mcp.paragraph.com` `search` + `feed` + `post.get` tools to fetch creator content. When a Paragraph post enters Gecko's RAG context for a research run:

- Pay the creator (via Paragraph's payout layer; tx hash recorded as `Provenance.payment` on the citation)
- Surface the creator handle in citations footer (per S13-PD-01)
- Receipt shows "Creator payouts: $0.05 → @author1, $0.03 → @author2"

This is the **inbound creator-monetization** flow. Sprint 14, simplified scope per above.

### Surface B — Gecko publishes verdicts as publish.new artifacts (NEW)

After every paid `gecko_research` run, automatically (or on opt-in) publish the verdict + business plan + PRD + advisor panel as a publish.new artifact:

- Title: "Gecko verdict: [idea summary] — KILL/REFINE/BUILD"
- Body: full ResearchResult markdown
- Price: $0.50 (or founder-set)
- Author wallet: founder's wallet (or Gecko's, with founder revenue share)

**Why this matters:**
- Other agents/founders can BUY past Gecko verdicts on similar ideas → trust artifact realized
- Founders earn revenue from publishing their own validation results (incentivizes sharing)
- Gecko earns marketplace cut OR a fixed markup on each publish
- Network effect: more verdicts published → more searchable verdict corpus → higher-quality future verdicts

Pricing implication: this is **NEW REVENUE** not in the BM 6-month projection. A founder who paid $0.75 for Pro now generates $0.50/sale recurring artifact revenue. LTV math reshapes again.

### Surface C — Gecko publishes deep research to Paragraph (publication)

Spin up a Gecko Paragraph publication: `paragraph.com/@gecko`. Publish:
- Weekly trend reports ("This week in DeFi validation: 47 ideas, 32 KILL, 12 REFINE, 3 BUILD")
- Vertical deep-dives ("DeFi vertical-suite v1: what we learned from 100 validations")
- Founder spotlight verdicts (with founder permission)

Paragraph already supports x402-gated subscriptions and per-post pricing. Gecko becomes a creator on Paragraph, paid by agents.

### Surface D — Gecko earns x402 on Paragraph-MCP-to-MCP traffic (speculative)

Once Gecko is itself a known MCP that other Paragraph users discover, Paragraph's user base may call `gecko_research` from inside Paragraph workflows (Paragraph's "search" tool returning Gecko-validated content as a layer above raw posts). Future revenue surface, no engineering this sprint.

---

## Updated roadmap implications

| Theme | Was | Now |
|---|---|---|
| **Theme 2 (Paragraph connector)** | Sprint 14, custom extractor + creator pay hop, ~5 days | Sprint 14, MCP-client wrapper + Paragraph MCP integration, ~1-2 days. Surface A only. |
| **Theme 2b (publish.new artifacts) — NEW** | not on roadmap | Sprint 14 add (Surface B): publish each research session as a publish.new artifact. ~2-3 days web3-engineer + software-engineer. |
| **Theme 2c (Gecko Paragraph publication) — NEW** | not on roadmap | Sprint 15 (Surface C): set up `paragraph.com/@gecko`, weekly trend report cron. ~2 days BM + product-designer. |
| **Trust-artifact framing** | "earned by Sprint 17 four-rail proof" | partially earned earlier — publish.new IS the artifact surface. Apex landing can claim it sooner. |

---

## Pricing & monetization impact

The original BM memo projected $8k/mo MRR mid-case. publish.new artifact revenue adds:

**Conservative:** 100 founders publish their verdicts at $0.50 each, 5 sales per artifact average → 100 × 5 × $0.50 = **$250 incremental marketplace revenue/month**. Tiny. But:

**Compounding:** the artifact corpus grows monthly. By month 6: 600 published verdicts × 3 average sales = 1,800 sales × $0.50 = **$900/month**. Still small but growth-shaped, not flat.

**Real value:** the verdict corpus becomes a moat. Every published verdict is a data point Gecko's flywheel learns from. Other validation tools can't easily replicate "5,000 paid verdicts with founder + agent attestations."

**Marketplace cut decision:** if Gecko takes 20% on each publish.new artifact sale (precedent: app stores), that's $180/mo at month 6. Not material as revenue line; material as moat depth.

---

## Sprint 12 / 14 amendments (concrete)

### Sprint 12 amendments

Add to chores:
- **Probe `https://mcp.paragraph.com/mcp` connectivity from gecko-api.** Verify the MCP server responds, list available tools, test a public post fetch. ~30 min, AI/ML engineer or software-engineer.
- **Fetch `paragraph.com/@blog/your-work-paid-for-by-agents`** and capture framing alignment notes. ~15 min product-designer for landing-copy alignment.
- **Probe `publish.new` API** with one test artifact create + buy on Base Sepolia (~$0.01). Document response shapes for Sprint 14 web3-engineer. ~1 hour web3-engineer.

These are exploration, not commitment. The actual Sprint 14 design depends on what we find.

### Sprint 14 plan revision (for the formal `build-plan-sprint-14.md` later)

Was: "Paragraph connector + creator citations" (one large theme).
Now: split into three tickets:
- **S14-PARA-01** — Paragraph MCP client wrapper as a `SourceProvider` instance. Reads from `mcp.paragraph.com`. ~1-2 days SE.
- **S14-PARA-02** — Creator citation rendering (already pre-paid in S13 Track D — just wire to Paragraph creator handles). ~0.5 day PD.
- **S14-PUB-01 (NEW)** — Publish-after-research opt-in: post each `ResearchResult` to `publish.new` as an artifact at $0.50. ~2-3 days web3 + SE.

Total Sprint 14 paragraph-related effort: ~4-5 days, plus pulse v1 work.

---

## Risks specific to this expansion

1. **Paragraph MCP availability/SLA.** Hosted at `mcp.paragraph.com`. If they go down, Gecko's Paragraph-as-source breaks gracefully (per the S12 SourceProvider Protocol's `degraded_sources` field). No new architecture risk; just a vendor risk.

2. **publish.new content moderation.** Auto-publishing every research run includes failed verdicts (KILLs that may name competitors negatively). Need an opt-in flow per session, not auto-fire. Founders should approve before their verdict goes public.

3. **Wallet attestation.** publish.new uses 0x-prefixed Ethereum addresses (Base/mainnet). Founders authenticated via frames.ag with Solana wallets won't have a Base wallet by default. Either: (a) we publish under Gecko's wallet and remit, (b) we require Base wallet at publish time, (c) wallet-bridge via CDP. Decision needed before S14.

4. **Brand risk: Gecko publishes wrong verdict, founder ships idea anyway, idea succeeds.** Public KILL verdicts that prove wrong erode trust. Mitigation: include the gap_classification + cited evidence + advisor panel transcript so the verdict is auditable. The "Validated by Gecko" stamp ages well only if the audit trail is public.

---

## Recommendation

**Commit the Sprint 12 chores (3 probes, ~2 hours total).** They de-risk Sprint 14 and let us write a real Sprint 14 plan with current platform data instead of stale assumptions.

**Don't redesign Sprint 12 main tracks.** The CDP listing + SourceProvider seam + rubric v2 work is correct. The Paragraph/publish.new expansion lands in S14 with sharper scope thanks to today's discovery.

**Strongly consider promoting publish.new artifact publishing to a Sprint 14 commit.** It's the cheapest path to landing the "verdict as shared trust artifact" claim that the deeper thesis promises but otherwise wouldn't earn until Sprint 17.

**Update the deeper-thesis doc** to reference publish.new and Paragraph MCP as the implementation surfaces for the trust-artifact claim. Cleaner story for the apex landing.
