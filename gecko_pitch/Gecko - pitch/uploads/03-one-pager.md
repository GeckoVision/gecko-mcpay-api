# Gecko — Builder Bootstrap Platform

**The first product where an AI agent commissions startup validation for the founder it works for.**
**Powered by x402 throughout. Built on Solana.**

---

## The problem

Every founder loses 20+ hours to research before knowing if their idea is real. Most quit. Most ship the wrong thing. **The cost is six months of building something nobody wants** — not the research time itself.

There's no "good enough" tool today. ChatGPT gives unsourced opinions. Consultants cost $5,000 and take two weeks. Manual research at 1 AM produces unstructured notes nobody acts on.

## What Gecko does

| Step | What happens |
|---|---|
| 1. Founder describes their idea | "A hotel guide for Brazil that highlights local hosts." |
| 2. Agent calls `gecko_research` via Claude Code or any MCP client | Triggers HTTP 402 from `gecko-api` |
| 3. Agent's wallet pays $20 USDC on Solana | Via x402 — no API keys, no signup |
| 4. Gecko discovers + indexes sources | Tavily, YouTube, web — chunked, embedded, stored |
| 5. Gecko generates three documents with citations | Business Plan, Validation Report, PRD — every claim cited to a source URL |
| 6. Knowledge base stays alive 90 days | `gecko_ask` — free follow-up questions, grounded answers |

**30 minutes from idea to validated decision. Not 20 hours.**

## Why we win — the moat in three pieces

**1. Encoded judgment.** Our Pro tier orchestration runs five specialist agents (Research, Market Analyst, Technical Architect, Validator, Orchestrator) using prompts that encode the specific lines of questioning a senior product person would run. A weekend clone can copy the architecture. They cannot copy 15 years of seeing pitches and watching products fail.

**2. Sessions, not transactions.** Every other product on x402 — MCPay, Cloudflare pay-per-crawl, Nous pay-per-inference — is transactional. Gecko sells **a 90-day knowledge base with grounded follow-ups**, not a one-shot call. The unit is a decision, not a query. Different category entirely.

**3. Claude Code-native distribution.** No signup, no website, no email. The user pastes one URL into Claude Code and Gecko installs itself. Other x402 products target developers who already want a wallet. We target founders who don't know x402 exists. The wallet is invisible.

## How x402 is load-bearing (not decoration)

Without x402, Gecko cannot exist as designed:

- **The buyer is an AI agent.** Agents cannot use Stripe. Agents cannot fill out a payment form. x402 is the only payment standard that lets a machine pay for a service autonomously.
- **The user has no API keys.** Authentication via wallet signature, payment via wallet signature. Same primitive does both jobs. Removing x402 means re-introducing API keys, signups, and human-mediated billing — which kills the agent-mediated UX.
- **The stack composes from independent x402-native primitives.** frames.ag (wallet), ClawRouter (LLM router), and Gecko (research) are three independent products that interoperate purely because they all speak x402. Without the protocol, none of these compositions work.

## Architecture (one paragraph)

Builder's agent calls `POST /research` on `api.geckovision.tech`. We respond with HTTP 402 + payment requirements. The agent pays via frames.ag (its wallet) on Solana. We verify the payment, ingest sources via Tavily/YouTube/web, embed into Supabase pgvector, and generate documents through ClawRouter — which routes each LLM call to the cheapest capable model and pays per call via x402. **Every payment in the stack is x402, end to end.** The agent doesn't see API keys. The user doesn't see model names. They see documents with citations.

## Status

| Component | State |
|---|---|
| Core SDK (`gecko-core`) | Working — V1 of the original product is live |
| FastAPI service with x402 middleware | Implemented |
| frames.ag wallet integration | Implemented and tested |
| ClawRouter LLM integration | Implemented and tested |
| MCP server for Claude Code | Working — `gecko_research`, `gecko_ask`, `gecko_sources` |
| Public skill bootstrap (`app.geckovision.tech/skill.md`) | Live |
| Solana mainnet payments | Live, with real transactions visible on Solana Explorer |
| Pro tier (5-agent GroupChat) | In progress — V1.5 |
| Web app | V2 (post-hackathon) |
| Creator attribution graph | V2 (post-hackathon) |

## Pricing

| Tier | Price | What you get |
|---|---|---|
| **Basic** | $20 USDC / session | Single-pass document generation, 90-day knowledge base, free follow-ups |
| **Pro** | $75 USDC / session | 5-agent GroupChat orchestration, deeper analysis, 72h persistent agent context |

No subscriptions. No per-call billing. The unit is a decision.

## Team

**Ernani Britto** — 15+ years software engineering (backend, frontend, database administration). Lived the "20 hours of bad research" problem twice. Building Gecko full-time.
**Co-founder, Design** — User experience and visual design.
**Community:** SuperteamBR.

## What we want from Colosseum

- **Accelerator slot.** $250K in pre-seed funding to build full-time through Q3 2026.
- **Network access.** Founder mentors who've shipped on Solana, especially in agentic infrastructure.
- **Credibility signal.** Colosseum's stamp opens doors for partner integrations (more x402-native services Gecko can interop with).

## What's next if we win

1. Ship Pro tier publicly with verified per-session output quality
2. Open the API to other agentic frameworks (Cursor, OpenAI Agent SDK, ElizaOS)
3. Expand the research category beyond startup validation: due diligence, technical research, market sizing — same model, different content
4. Creator attribution graph (V2) — give the people whose content powers Gecko's output a way to claim earnings

## Links

- **Install:** Read `https://app.geckovision.tech/skill.md` in Claude Code
- **Repo:** `github.com/<owner>/gecko` (MIT licensed core)
- **On-chain:** [Real transaction example] — `solana.fm/tx/...`
- **Demo video:** [link to the 3-min pitch]
- **Technical walkthrough:** [link to the 3-min walkthrough]

---

*Builder Bootstrap Platform · geckovision.tech*
*An AI agent just paid for its founder to find out if their idea is real.*
