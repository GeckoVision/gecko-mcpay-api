# Verdict URL — Frontend Handoff (gecko-mcpay-app)

**Sprint:** S20-VERDICT-URL-IMPL-01 (#10)
**For:** frontend-engineer in `~/PycharmProjects/Gecko/gecko-mcpay-app`
**Source contract:** `docs/strategy/2026-05-02-verdict-url-api-contract.md` in this repo.

This is the design + integration brief. Routes / components / state management are your call — I name the must-haves.

---

## Route

`app/v/[hash]/page.tsx` — Next.js App Router, dynamic segment.

## Server Component fetch

```ts
const res = await fetch(`${process.env.GECKO_API_BASE}/v1/verdict/${params.hash}`, {
  next: { revalidate: 3600 },
});
if (res.status === 404) notFound();
if (res.status === 302) redirect(res.headers.get("Location")!);
const v = await res.json();
```

The `revalidate: 3600` cache is conservative — verdicts are immutable post-stamp, so even longer is fine. 1h gives editorial time to update the rendering layout without invalidating CDN.

## Render layout (unauth teaser, the only view shipping in #10)

1. `<h1>` — `v.idea_text`
2. **Verdict badge** — color-coded:
   - `GO` → green
   - `REFINE` → blue
   - `PIVOT` → amber
   - `KILL` → red
   Confirm exact palette with `brand.md` / `product-designer`.
3. `<p>` — `v.judge_prose_excerpt`
4. Small mono token: `<code>{v.verdict_hash_short}</code>` (muted, clipboard-copyable)
5. **CTA**: "Buy full verdict — ${v.price_usdc || '2.50'} USDC (coming soon)"
   - Disabled button, `aria-disabled="true"`
   - Goes live in #11
   - Read price from API response, NOT hardcoded — when tiered pricing lands, no frontend redeploy needed
6. **Footer**:
   - Relative `created_at` ("23 minutes ago")
   - `tier` chip ("basic" | "pro")
   - If `provider_mix_flag !== 'balanced' && provider_mix_flag !== null`: small warning chip ("⚠ thin diversity" or "⚠ single provider dominates")

## OG image

`app/v/[hash]/opengraph-image.tsx` — `next/og` rendering verdict badge + truncated idea snippet for shareable links. Same 1h revalidate.

## Crawl rules

- **Not in `sitemap.xml`** — verdicts are user-generated; no crawl.
- **`robots.txt`**: add `Disallow: /v/` to prevent indexing while still allowing direct link sharing (humans get the URL via the CLI footer or share buttons).

## Wedge alignment

This page **is** the "buy, sell, or stake on" half of the wedge sentence rendered in product. The disabled CTA copy should reinforce: "This verdict is tradeable. Full debate transcript settles on x402."

After #11 lands and the CTA is live, the page becomes the user-facing surface for the entire tradeable-judgment thesis.

## CORS / cross-origin

The teaser endpoint allows `Access-Control-Allow-Origin: *`. Server-side fetches (Server Components) ignore CORS anyway, but client-side share buttons / `navigator.clipboard` flows benefit from the wide-open policy. After #11, `?detail=full` will be restricted to `https://app.geckovision.tech` only.

## Coordination notes

- **`GECKO_API_BASE`** env var must be set on the Vercel deployment (likely `https://api.geckovision.tech` or similar).
- Test against the live `/v1/verdict/<hash>` endpoint as soon as the Python repo lands #10. Use a known good hash from your own `bb research` runs.
- For preview environments, point at a staging API or use Mock Service Worker with the teaser shape from the contract doc.

## What's NOT in #10 (deferred to #11)

- The actual paid view (full citations, PRD, transcript, advisor voices)
- x402 paywall settlement (frames.ag wallet flow, USDC transfer, settlement receipt)
- Reseller cut UI ("buy and resell for X" CTA)
- Revocation / refund window UI

#10 ships the unauthenticated teaser; #11 ships the paid view + settlement.

---

## #11 update — paid view + paywall (S20-X402-VERDICT-SETTLE-01)

The paid surface lives at `/v/[hash]/detail/page.tsx`. Two equivalent backend URLs:

```
GET /v1/verdict/<hash>?detail=full   ← canonical (matches contract doc)
GET /v1/verdict/<hash>/detail        ← path alias; 308-redirects to canonical
```

The frontend should always issue the canonical query-string form; the path alias exists for wallet-side x402 flows that prefer path-segment resources.

### 402 challenge body (no `X-Payment` header)

```json
HTTP 402
{
  "error": "payment_required",
  "message": "x402 settlement required for verdict detail",
  "verdict_hash": "<echo>",
  "price_usdc": "2.50",
  "x402_challenge": {
    "scope": "verdict:<hash>",
    "price_usdc": "2.50",
    "pay_to": "<recipient address>",
    "network": "stub|solana-mainnet|base-mainnet|...",
    "facilitator": "stub|frames-solana|cdp-base|...",
    "challenge_id": "<server nonce>"
  },
  "last_failure": "<optional — present iff a previous attempt was rejected>"
}
```

The frontend's wallet flow:

1. Reads `x402_challenge` from the 402 body.
2. In **stub mode** (`network=="stub"`), produces an `X-Payment` header of the form `stub:<verdict_hash>:<nonce>` and retries.
3. In **live mode**, hands the challenge to the buyer's wallet (frames.ag for Solana / CDP wallet for Base) which signs an x402 v2 PaymentPayload, base64-encodes it, and retries with `X-Payment: <base64>`.

If the retry fails (bad signature, scope mismatch), the next 402 carries `last_failure` so diagnostic copy can render without a follow-up round-trip.

### 200 paid response

```json
HTTP 200
{
  "verdict_hash": "<full-64-hex>",
  "verdict_hash_short": "verdict@<12-hex>",
  "verdict": "GO|REFINE|PIVOT|KILL",
  "idea_text": "...",
  "tier": "basic|pro",
  "created_at": "2026-05-02T14:33:00Z",

  "judge_prose_full": "<full synthesizer prose, no excerpt cap>",
  "gap_classification": "Partial:UX",
  "gap_summary": "...",
  "provider_mix_flag": "balanced|single_provider_dominates|thin_diversity|null",

  "business_plan": { ... | null },
  "validation_report": { ... including all citations | null },
  "prd": { ... | null },
  "advisor_voices": [ ... | null ],
  "transcript": { ... | null },
  "agent_turns": { ... | null },

  "settlement_receipt": {
    "verdict_hash": "<echo>",
    "tx_signature": "<chain-specific signature, null in stub mode>",
    "facilitator": "stub|frames-solana|cdp-base|...",
    "settled_at": "2026-05-02T14:35:11Z"
  }
}
```

`business_plan` / `validation_report` / `prd` / `advisor_voices` / `transcript` are nullable: the persisted `judge_transcripts` document doesn't always carry the full ResearchResult shape, so the frontend renders conditionally and degrades gracefully when a field is absent.

### Render layout (paid view)

1. Hero: idea + verdict badge (same colors as teaser).
2. Full prose block (`judge_prose_full`) — no excerpt cap.
3. **Citations panel** — `validation_report.citations`, grouped by `provider_kind`. The S20 `provider_mix_flag` chip lives here too; show "balanced" / "thin diversity" / "single provider dominates" inline so the buyer sees the corpus shape at the same glance as the verdict.
4. **Advisor voices** — one card per voice in `advisor_voices` (skeptic / founder / etc.), with their per-voice verdict and 1–2 sentence summary. Dissent is the artifact buyers pay for; surface it prominently.
5. **PRD + Business plan** — collapsed by default; expand on click.
6. **Debate transcript** — `agent_turns` rendered as a chat-style timeline. Pro tier only; basic tier has no transcript.
7. Footer: settlement receipt block (truncated `tx_signature` with explorer link, `facilitator` chip, `settled_at` relative time).

### Stub-mode flow (development)

While `X402_VERDICT_SETTLE_LIVE` is unset, the backend serves stub challenges. Frontend should ship a "stub wallet" component that, on click, generates the `stub:<verdict_hash>:<nonce>` X-Payment header and retries. This unblocks dev / preview environments without funded wallets.

### Live-mode rollout

Live x402 settlement is feature-flagged behind `X402_VERDICT_SETTLE_LIVE=1` on the backend. **The flag stays off until the Pattern C contract test (`tests/payments/test_verdict_settle_contract.py`) is recorded green against the real facilitator's `/verify` AND `/settle` endpoints.** Frontend can build the live wallet flow against stub mode; the wire format is identical.
