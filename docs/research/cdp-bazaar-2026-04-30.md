# CDP Bazaar — landscape probe + Gecko integration analysis

**Date:** 2026-04-30
**Source:** `https://docs.cdp.coinbase.com/x402/bazaar` (user-supplied) + live API probes against `api.cdp.coinbase.com/platform/v2/x402/discovery/*`

---

## What CDP Bazaar is, in one paragraph

CDP Bazaar is the discovery layer above x402. Sellers register routes via the `@x402/extensions/bazaar` SDK; the CDP Facilitator catalogs them automatically the first time a payment **settles** through CDP. Buyers (humans, dashboards, AI agents) discover services through three surfaces: a paginated catalog (`/discovery/resources`), a semantic search endpoint with quality ranking (`/discovery/search`), and an MCP server (`/discovery/mcp`) that wraps `search_resources` + `proxy_tool_call` so agents can call paid APIs transparently. Quality ranking blends retrieval relevance with **objective** signals: 30-day buyer reach, 30-day transaction volume, recency, metadata quality.

## Live landscape probe — what's there today

Probed semantic search for slots Gecko could plausibly occupy. Findings:

### "research + validation" (Gecko's primary slot)

5 results. **All from OrbisAPI** (a thin-proxy factory churning out generic-shape APIs). Top result: `market-validation-score-api` with **1 call in 30 days, 1 unique payer**. The whole "validation" semantic slot is **uncontested at quality scale.** OrbisAPI scaffolds the metadata but has no real users.

### "competitor research"

5 results. Two real entries (`api.strale.io/x402/competitor-compare` at 5 calls/30d, OrbisAPI competitor-analyzer at 1-2 calls). Same story — early, low-traffic, generic.

### "founder research"

3 results. Top: `capminal.ai/api/x402/research` — "AI-powered Token Deep Research API" at $0.01. Adjacent (crypto token research, not startup founder research). Slot is **wide open** for Gecko-shaped product validation.

### Adjacent paid sources (potential V2 source candidates)

- **Reddit posts/comments**: OrbisAPI proxy at $0.001/call (Gecko hits Reddit JSON for free today)
- **GitHub repo search/compare**: `staging.toolkit.dev` and `api.strale.io` (Gecko hits GitHub public API for free today)
- **Crypto news**: `coinstats.app/news`, `palmvox.com/news` at $0.001-0.005

### Headline observation

**Gecko would land as the highest-quality entry in the "founder validation" semantic slot on day one.** The competition is OrbisAPI's auto-generated proxies with single-digit usage. Gecko's adversarial multi-agent debate + RAG'd citations + on-chain receipts is structurally differentiated. The thesis claim ("validation layer above frames.ag") translates 1:1 to "the best-ranked validation entry in the CDP Bazaar."

## Strategic implications for Gecko

### Distribution: Bazaar > Claude Code skills (long-term)

Today's distribution: humans run `Read app.geckovision.tech/skill.md` to install the Gecko Claude Code skill. That's frames.ag-style — works for Claude Code users, captures 0% of every other agent ecosystem.

Bazaar MCP server (`/discovery/mcp`) is a different model: any AI agent using a CDP-aware MCP client can discover and call `gecko_research` **without ever installing anything on the user side**. The user funds an Agentic Wallet (`awal`) or any x402-capable wallet; the agent finds Gecko via semantic search; the agent pays and calls; results return.

This is meaningfully bigger distribution than what we have. The Claude Code skill stays as the human-facing surface; the Bazaar listing is the **agent-facing** surface.

### Settlement: today Solana-only, Bazaar opens Base/EVM cleanly

Gecko's x402 today settles on Solana via frames.ag. Bazaar registration requires settlement through the **CDP Facilitator** (Base mainnet, Base Sepolia, Solana). To list, Gecko needs to either:
- (a) Add CDP Facilitator as an alternate settlement mode (Base/EVM); keep frames.ag for Solana.
- (b) Route Solana settlements through CDP's Solana facilitator (would replace frames.ag for that flow).

**Recommendation: (a).** Don't burn the frames.ag relationship. Add CDP as a parallel settlement path for Base. Two networks > one. Users on Base get a faster fiat onramp via Coinbase; Solana users keep frames.ag.

### Coinbase Agentic Wallet (`awal`) is a wallet — not a competitor

`npx awal` and `@coinbase/payments-mcp` are wallet/skill surfaces for end users. They sit at the same layer as frames.ag (and any other x402-capable wallet). Gecko stays neutral: any x402-capable wallet works. No special coupling.

### Quality ranking is the moat compound

Bazaar ranks by **buyer reach × transaction volume × recency × metadata quality**. Gecko's existing flywheel (live-V1 eval, live mainnet smokes once funded, the upcoming Sprint 11 verdict-renderer) all feed this. Once listed, every paid call from Claude Code skill users **also** counts toward Gecko's Bazaar rank — because the same gecko-api endpoint settles both flows. The flywheel that already exists turns into ranking signal automatically.

Compounds further: high rank → top semantic-search hit for "founder validation" / "product research" / "PRD generation" → more agent traffic → more buyer reach → higher rank.

### Risks

1. **Lock-in to CDP Facilitator.** Settling through CDP means Coinbase sees every transaction. Acceptable for V1 (operational simplicity); revisit if Coinbase's ToS changes.
2. **Route consolidation.** Bazaar collapses paths with bare UUIDs/addresses into one entry. Today's `/research/{session_id}` URL pattern would consolidate every research session into a single Bazaar row. **Fix before listing:** prefix the session ID (e.g. `/research/session-{uuid}`) so each surface stays distinct.
3. **Verify-then-settle requirement.** Bazaar only catalogs after a successful **settle**. Pure-verify dry-runs don't show up. Need a real (test or production) payment to register.
4. **JSON Schema strictness.** Extension `input` must pass strict JSON Schema validation. Gecko's input is a plain `idea` string — easy, but every endpoint we want listed needs a complete schema declaration. Cost: ~1-2h per endpoint.

## Decision summary

- **List in Bazaar?** Yes. Slot is uncontested, quality signals favor us, agent-side distribution is meaningfully wider than skills alone.
- **Add Base settlement?** Yes, as a parallel path to Solana. Keep frames.ag; don't replace it.
- **Consume Bazaar APIs as V2 sources?** Not yet. Free sources work; Reddit/GitHub paid proxies don't add quality. Revisit after Sprint 13 if a high-quality paid source emerges.
- **Adopt Coinbase Agentic Wallet (`awal`)?** No — stay wallet-neutral. Document in `docs/runbooks/` that any x402-capable wallet works (frames.ag, awal, custom).
