# Sprint 12 chore probe results — 2026-04-30

**Trigger:** user redeployed gecko-api + asked us to verify the verdict-shape leak is fixed AND probe Paragraph MCP / publish.new for Sprint 14 readiness.

---

## 1. gecko-api redeploy verified ✅

Re-fired `mcp__gecko__gecko_research` with the same prompt. Now returns:

```json
{
  "verdict": "REFINE",
  "validation_report": {
    "gap_classification": "Partial:UX",
    "gap_summary": "Agentward covers permission control but lacks a payment-gated decision-making process for AI agents.",
    ...
  }
}
```

Sprint 11 Track A's verdict shape is fully on the wire. Tx settled on Solana devnet (`24Tut8TZYNQveGgA18jys1C2qhnxycke5mBChgWqVX3R95xhEkGENew6EHFkdg4afdiVYfMvM2fKcUUfKK2vFz79`).

Notable secondary finding: `awesome-mcp-servers` GitHub repo indexed at **436 chunks**, way above the typical 6-30 we see. Either the repo is enormous or the chunker took the README + docs as one corpus. Worth a quick AI/ML engineer check whether one massive source is dominating the RAG context inappropriately.

## 2. publish.new is Paragraph (same platform) ✅

Probed `https://publish.new/api/artifact/<slug>/content?chain=base` and decoded the `payment-required` header:

```json
{
  "x402Version": 2,
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:8453",
    "amount": "1000000",
    "resource": {
      "url": "https://public.api.paragraph.com/x402/<slug>?chain=base"
    },
    "payTo": "0x952a149E5D303C7A39A8B613250193418AFD6683",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    ...
  }]
}
```

**Headline:** the resource URL points at `public.api.paragraph.com` — **publish.new and Paragraph are the same backend.** Same wallet ecosystem, same auth surface, same x402v2 contract.

Implications for Sprint 14:
- The Paragraph connector + publish.new artifact publishing are **one integration**, not two
- Once we authenticate to Paragraph (OAuth, see §3), we can both consume Paragraph posts and publish Gecko verdicts as artifacts via the same auth context
- The x402v2 contract on publish.new is identical to what CDP Bazaar uses (Sprint 12 Track A) — our `CDPX402Client` likely works for publish.new artifacts as-is. **Estimate: Sprint 14 publish.new integration = 1-2 days, not 2-3.**

The publish.new artifact list shows real volume: most recent at $1.00 each, mixed wallet authors. Functional today, not vapor.

## 3. Paragraph MCP requires OAuth ⚠️

`mcp.paragraph.com/mcp` returns **401 with Bearer challenge**:

```
www-authenticate: Bearer realm="OAuth",
                  resource_metadata="https://mcp.paragraph.com/.well-known/oauth-protected-resource",
                  error="invalid_token"
```

OAuth metadata at `https://mcp.paragraph.com/.well-known/oauth-protected-resource`:
```json
{
  "resource": "https://mcp.paragraph.com",
  "authorization_servers": ["https://mcp.paragraph.com"],
  "bearer_methods_supported": ["header"]
}
```

Self-hosted authorization server. Implication for Sprint 14:
- Need an OAuth flow for users — likely "connect your Paragraph account" once at install time, store token in `~/.gecko/paragraph_token.json` similar to how frames.ag wallet config works
- Per Paragraph docs the alternative is API key via `paragraph login --token <api-key>` from their CLI — that's the simpler path
- web3-engineer + software-engineer co-design needed; not a blocker but not free

**Add to Sprint 14 ticket list:** S14-PARA-AUTH-01 — Paragraph token bootstrap (CLI flag + persistent storage). ~0.5 day.

## 4. Sprint 14 plan tightening (final)

Based on these probes, the Sprint 14 Theme 2 work is now:

| Ticket | Scope | Effort |
|---|---|---|
| **S14-PARA-AUTH-01** | OAuth/API-token bootstrap for Paragraph (one-time CLI flow) | 0.5 day |
| **S14-PARA-01** | `ParagraphProvider(SourceProvider)` — calls `mcp.paragraph.com` for posts/feed/search | 1.5 days |
| **S14-PARA-02** | Creator citation rendering (already pre-paid in S13 Track D — wire Paragraph creator handles) | 0.5 day |
| **S14-PUB-01** | Publish-after-research opt-in: post each `ResearchResult` to `publish.new` (= same backend) at $0.50, payable in USDC on Base | 1.5 days |

**Total Sprint 14 Paragraph stack effort: ~4 days** (vs original ~5 days for inbound-only). Plus pulse v1 work in parallel.

## 5. The unification claim now lands earlier

Per `docs/strategy/paragraph-publish-new-expansion-2026-04-30.md`: publish.new IS the implementation surface for "verdict as shared trust artifact." Now confirmed by the probe:
- It's live, has volume, accepts USDC on Base, uses x402v2
- Same backend as Paragraph means we don't need to ship two integrations

Updated apex landing claim becomes earnable in **Sprint 14, not Sprint 17**. The macro thesis ("trust layer of the agentic economy") gets the trust-artifact proof point in this near-term arc.

---

## Outstanding probe (in flight)

product-designer is fetching `paragraph.com/@blog/your-work-paid-for-by-agents` for framing-alignment notes. That'll close the third chore. Will surface when in.

---

## Recommendation

Sprint 12 plan **does not need re-revision**. Add three tickets to Sprint 14 backlog (above) and one note to the AI/ML engineer chore list:

> **AI/ML chore:** investigate whether `awesome-mcp-servers` (or any single source) is dominating RAG retrieval. If one source returns 436 chunks while others return 0-6, top-K similarity may be sourcing predominantly from one corpus. Quick fix: per-source max_chunks_in_context cap.

Sprint 11 Track A is fully shipped + verified. Sprint 12 ready to fire whenever you greenlight it.
