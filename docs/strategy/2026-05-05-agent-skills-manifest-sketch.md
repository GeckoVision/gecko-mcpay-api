# Agent-Skills Manifest Sketch — `app.geckovision.tech/.well-known/agent-skills/index.json`

**Status:** SKETCH — feeds the brainstorming round on knowledge-as-commodity positioning.
**Schema source:** `https://pay.sh/.well-known/agent-skills/index.json` (v1.0).
**Spec memory:** `project_knowledge_as_commodity_pivot`.

---

## Goal

Publish a single discovery document at `app.geckovision.tech/.well-known/agent-skills/index.json` that:

1. Lists every paid endpoint Gecko exposes (retrieval + team-debate + bulk credit).
2. Conforms to the pay.sh manifest schema so pay.sh's catalog crawler picks it up automatically.
3. Maps each skill to a per-call price + an x402-compatible HTTPS endpoint.
4. Doubles as the same endpoint that `gecko-mcp` reads on `serve` to register tools — single source of truth.

---

## Per-skill object shape (extends pay.sh v1.0)

The pay.sh schema is intentionally minimal (`name`, `title`, `description`, `url`). We extend with optional `pricing` and `category` blocks — non-breaking for pay.sh's crawler (extra fields ignored).

```json
{
  "name": "retrieve-market-intelligence",
  "title": "Retrieve market_intelligence chunks",
  "description": "Vector search the categorized base for market signals (competitive landscape, sizing, timing, analogous companies). Returns top-k chunks with citations and confidence scores.",
  "url": "https://app.geckovision.tech/skills/retrieve-market-intelligence",
  "pricing": {
    "flat_usd": 0.01,
    "bundled_output_tokens": 50000,
    "overage_per_1m_output_usd": 0.50,
    "currency": "USD"
  },
  "category": "data",
  "gecko_knowledge_category": "market_intelligence"
}
```

`category` = pay.sh's API-verb taxonomy (compute / finance / messaging / ai_ml / media / data / identity).
`gecko_knowledge_category` = our knowledge-noun taxonomy (the 7 buckets in Section 2 of the spec slides).

---

## Full sketch

```json
{
  "version": "1.0",
  "name": "Gecko",
  "description": "Categorized vector knowledge base + multi-team consumption layer for builder pre-ideation. Query the base, run market/build/strategy debates, or buy bulk credits. All paid via x402 on Solana or Base.",
  "skills": [
    /* ---------- 7 categorized retrieval endpoints ---------- */
    {
      "name": "retrieve-market-intelligence",
      "title": "Retrieve market_intelligence chunks",
      "description": "Vector search the categorized base for competitive signals, market sizing, timing, analogous companies.",
      "url": "https://app.geckovision.tech/skills/retrieve-market-intelligence",
      "pricing": { "flat_usd": 0.01, "bundled_output_tokens": 50000, "overage_per_1m_output_usd": 0.50 },
      "category": "data",
      "gecko_knowledge_category": "market_intelligence"
    },
    {
      "name": "retrieve-business-financial",
      "title": "Retrieve business_financial chunks",
      "description": "Unit economics, pricing models, GTM patterns, revenue signals.",
      "url": "https://app.geckovision.tech/skills/retrieve-business-financial",
      "pricing": { "flat_usd": 0.01, "bundled_output_tokens": 50000, "overage_per_1m_output_usd": 0.50 },
      "category": "finance",
      "gecko_knowledge_category": "business_financial"
    },
    {
      "name": "retrieve-investment-signals",
      "title": "Retrieve investment_signals chunks",
      "description": "What investors look for, funding patterns, due-diligence signals.",
      "url": "https://app.geckovision.tech/skills/retrieve-investment-signals",
      "pricing": { "flat_usd": 0.01, "bundled_output_tokens": 50000, "overage_per_1m_output_usd": 0.50 },
      "category": "finance",
      "gecko_knowledge_category": "investment_signals"
    },
    {
      "name": "retrieve-product",
      "title": "Retrieve product chunks",
      "description": "JTBD patterns, prioritization frameworks, PMF signals, user research.",
      "url": "https://app.geckovision.tech/skills/retrieve-product",
      "pricing": { "flat_usd": 0.01, "bundled_output_tokens": 50000, "overage_per_1m_output_usd": 0.50 },
      "category": "data",
      "gecko_knowledge_category": "product"
    },
    {
      "name": "retrieve-technical-engineering",
      "title": "Retrieve technical_engineering chunks",
      "description": "Architecture patterns, stack decisions, implementation patterns.",
      "url": "https://app.geckovision.tech/skills/retrieve-technical-engineering",
      "pricing": { "flat_usd": 0.01, "bundled_output_tokens": 50000, "overage_per_1m_output_usd": 0.50 },
      "category": "data",
      "gecko_knowledge_category": "technical_engineering"
    },
    {
      "name": "retrieve-ai-ml",
      "title": "Retrieve ai_ml chunks",
      "description": "Agent patterns, model selection, RAG design, eval frameworks.",
      "url": "https://app.geckovision.tech/skills/retrieve-ai-ml",
      "pricing": { "flat_usd": 0.01, "bundled_output_tokens": 50000, "overage_per_1m_output_usd": 0.50 },
      "category": "ai_ml",
      "gecko_knowledge_category": "ai_ml"
    },
    {
      "name": "retrieve-design-ux",
      "title": "Retrieve design_ux chunks",
      "description": "Design patterns, UX research, brand positioning.",
      "url": "https://app.geckovision.tech/skills/retrieve-design-ux",
      "pricing": { "flat_usd": 0.01, "bundled_output_tokens": 50000, "overage_per_1m_output_usd": 0.50 },
      "category": "data",
      "gecko_knowledge_category": "design_ux"
    },

    /* ---------- 3 team-debate endpoints ---------- */
    {
      "name": "research-market",
      "title": "Run Market Research debate",
      "description": "Investor + Business Manager agents debate the market case for an idea. Returns KILL / REFINE / BUILD verdict with cited evidence.",
      "url": "https://app.geckovision.tech/skills/research-market",
      "pricing": { "flat_usd": 0.10, "bundled_output_tokens": 100000, "overage_per_1m_output_usd": 1.00 },
      "category": "data",
      "gecko_knowledge_category": "market_intelligence"
    },
    {
      "name": "build-product",
      "title": "Run Product Building debate",
      "description": "PM + Designer + Software Engineer + AI Engineer agents debate what to build, in what order, and how it should feel. Returns build plan + implementation signals.",
      "url": "https://app.geckovision.tech/skills/build-product",
      "pricing": { "flat_usd": 0.25, "bundled_output_tokens": 200000, "overage_per_1m_output_usd": 1.00 },
      "category": "data",
      "gecko_knowledge_category": "product"
    },
    {
      "name": "strategy-architecture",
      "title": "Run Architecture & Strategy debate",
      "description": "CTO + Staff Engineer agents debate whether this is the right system to build, and the right way to build it. Returns architecture verdict + 6-month risk flags.",
      "url": "https://app.geckovision.tech/skills/strategy-architecture",
      "pricing": { "flat_usd": 0.15, "bundled_output_tokens": 100000, "overage_per_1m_output_usd": 1.00 },
      "category": "data",
      "gecko_knowledge_category": "technical_engineering"
    },

    /* ---------- 1 full-pipeline endpoint ---------- */
    {
      "name": "research-full",
      "title": "Run all 3 teams (Market + Product + Architecture)",
      "description": "Full Gecko pipeline: classify, retrieve, three-team debate, synthesized verdict. Output enriches the base for the matched category.",
      "url": "https://app.geckovision.tech/skills/research-full",
      "pricing": { "flat_usd": 0.50, "bundled_output_tokens": 500000, "overage_per_1m_output_usd": 1.00 },
      "category": "data",
      "gecko_knowledge_category": "market_intelligence"
    },

    /* ---------- 1 bulk credit ---------- */
    {
      "name": "credit-pack",
      "title": "Buy bulk Gecko credits ($10 = 1.5M output tokens)",
      "description": "Prepay credit pack consumable on any Gecko skill. Best blended margin for high-volume agent users.",
      "url": "https://app.geckovision.tech/skills/credit-pack",
      "pricing": { "flat_usd": 10.00, "bundled_output_tokens": 1500000, "overage_per_1m_output_usd": null },
      "category": "data"
    }
  ]
}
```

Total: **12 skills.** 7 retrieval + 3 team-debate + 1 full-pipeline + 1 bulk credit.

---

## Wire mechanics

Each `url` resolves to an HTTP endpoint that:

1. **First call (no x402 receipt):** returns HTTP 402 with `WWW-Authenticate: x402` header carrying the price + facilitator URL.
2. **Second call (with receipt):** verifies via `x402_facilitator_url`; on green, dispatches to the matching gecko-core function and streams the response.
3. **All retrievals enrich the base** — query + output embedded via Voyage, written to Mongo with `category`, `subcategory`, `source = user_query`, `metadata.confidence` (LLM self-rated), `metadata.usage_count` (bumped on citation in output).

---

## What this manifest is NOT

- **Not a category override for pay.sh.** We use pay.sh's `data` / `finance` / `ai_ml` for their crawler's filtering. Gecko's 7-category knowledge taxonomy lives in `gecko_knowledge_category` (extension field).
- **Not a free trial.** No skill is priced at $0 — Gecko is a paid layer end-to-end. (free *tier* exists internally but not on the public manifest.)
- **Not the sources list.** Tavily, twit.sh, Bazaar, pay.sh providers we *consume* are documented separately at `/.well-known/sources.json` (future ticket).

---

## Open before publishing

1. Final wording on each `description` (product-designer review).
2. Confidence-score formula (LLM self-rating spec — what's the prompt, what's the value space — `[0,1]`? Bucketed `low/medium/high`?).
3. Citation-extraction step in the synth so `usage_count` write-back has doc IDs.
4. Pricing review with business-manager: are the team-debate floors high enough vs Claude Opus cost at quality tier? (Quality tier may need a 4× multiplier or a token-only model.)
5. Settlement signing key for x402 — whose facilitator? frames.ag default for Solana, CDP for Base. Already covered by the wallet-neutrality rule.
