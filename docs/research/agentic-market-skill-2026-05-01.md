# agentic.market — skill reference

**Source:** https://agentic.market/SKILL.md (fetched 2026-05-01)
**Why we have this:** S16 Track B context. We want Gecko to consume the *whole* Bazaar catalog, not vendor-by-vendor adapters. This file is the canonical reference engineers should read before touching `BazaarSourceProvider`.

---

## What it is

Agentic Market is a public service directory aggregating "thousands of services" with **pay-per-request pricing in USDC**, no registration, no API keys. Operated by Coinbase atop the x402 protocol (Linux Foundation). Same x402 fabric we already settle on (S12 CDP listing).

## Resources

- **Main site:** https://agentic.market
- **x402 docs:** https://docs.cdp.coinbase.com/x402/welcome
- **LLMs configuration:** https://agentic.market/llms.txt
- **Skills CLI install:** `npx skills add coinbase/agentic-wallet-skills`

## API endpoints (the only two we need)

```
GET https://agentic.market/v1/services
GET https://agentic.market/v1/services/search?q={query}
```

Both are read-only discovery. **No auth.** This is the catalog. Settling against any individual service is a per-call x402 payment, separate from discovery.

## Why this matters for Gecko (S16 Track B)

User-flagged 2026-04-30: TripAdvisor blocks our crawl, but is listed on Bazaar with x402 endpoints. The right answer is **not** "build a TripAdvisor adapter." The right answer is:

1. At ingestion time, query `/v1/services/search?q=<idea>` and get a ranked list of paid endpoints relevant to the topic.
2. Filter by per-call price ≤ session cap.
3. Settle x402, fetch, normalize into chunks. Same path for hotel reviews, market data, scientific corpora, anything else listed.
4. The adapter layer is **generic** — vendor-specific shims exist only when the response shape demands it.

This means S16-BAZAAR-CONSUMER-03 (`BazaarSourceProvider`) is **catalog-aware**, not adapter-led. TripAdvisor is the **first proving smoke**, not a special case.

## Open questions for engineering

1. **Catalog source:** prefer `agentic.market/v1/services` (richer metadata, search) or `api.cdp.coinbase.com/v2/x402/discovery/resources` (CDP-native, what we currently target in `S16-BAZAAR-DISCOVERY-01`)? Likely both, with agentic.market as primary for human-readable search and CDP discovery as fallback / cross-check.
2. **`llms.txt` signal:** worth fetching once at startup to seed our category-to-service routing? Or query per-session?
3. **Response-shape normalization:** what's the minimum structured envelope we can rely on across all listed services? Need to inspect 5-10 representative endpoints before committing the chunk-mapping contract.
4. **Skills CLI (`npx skills add coinbase/agentic-wallet-skills`):** orthogonal to our use — that's a Claude Code skill bundle for end-users to install agentic-market access into their Claude. We're going the other way (server-side ingestion). Cross-check what the skill bundle does for inspiration on the discovery UX.

## Action

Engineering team (data-eng + software-eng + web3-eng): read this, then revisit `docs/build-plan-sprint-16-bazaar-consumer.md` Track B with the reframe in mind. Architecture stays the same; the **adapter strategy** flips from vendor-led to catalog-led.
