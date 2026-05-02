# Tradeable Judgment Surface — Spec (S19-S1)

**Ticket:** S19-TRADEABLE-SURFACE-01
**Status:** Spec only. No implementation, no on-chain work, no migrations.
**Author:** business-manager
**Date:** 2026-05-02
**References:** S18 plan §1, S19 plan §2c, `gecko_core.verdict_hash` (committed `a5502cf`, ships `verdict_hash_short()` = `verdict@<12-hex>`).

---

## 1. Wedge alignment

Verbatim wedge sentence (PRD/skill.md/splash):

> Gecko produces grounded, adversarial verdicts on pre-ideas — a judgment you can buy, sell, or stake on.

The *grounded* and *adversarial* halves are necessary but not sufficient — Perplexity and ChatGPT also synthesize cited prose. What they cannot replicate is a verdict that is **content-addressable, ownable, and resellable**: a sha256 over (idea, corpus fingerprint, verdict json) makes each verdict a discrete artifact, and an x402 paywall on its URL makes that artifact transferable. The defensibility is not "we wrote a verdict"; it is "this exact verdict, identified by this hash, has a settlement layer, an audit trail, and a market price." Perplexity outputs prose; Gecko outputs an asset.

---

## 2. Verdict hash → URL format

**Choice:** `https://app.geckovision.tech/v/<full-64-char-sha256>` for the canonical link, with `https://app.geckovision.tech/v/<12-hex>` as a redirect-only short form (matches `verdict_hash_short()`).

**Why:** Full sha256 is the content-addressable contract — any future on-chain settlement (S20+) will reference the full digest, not a truncated prefix. The 12-hex short form already exists in the CLI footer and is fine for human chatter, but the public canonical must be the full hash so collisions are not an attack surface as the corpus grows. Single-character path segment `/v/` keeps copy-paste friendly; `/verdict/` was rejected as noisier without adding clarity.

| Surface | Form |
|---|---|
| CLI footer (existing) | `verdict@<12-hex>` |
| Shareable canonical URL | `app.geckovision.tech/v/<64-hex>` |
| Short redirect | `app.geckovision.tech/v/<12-hex>` → 302 to canonical |

**Why redirect rather than first-class short URL:** one canonical = one hash to settle against. Keeping the short form a redirect avoids a second namespace to garbage-collect when collisions arrive.

---

## 3. What a paywalled URL renders

Two views off the same URL, gated by x402 payment receipt.

| Field | Unauthenticated (teaser) | Paid viewer |
|---|---|---|
| Idea string | shown | shown |
| Verdict token (GO / PIVOT / REFINE / NO) | shown | shown |
| Verdict hash (full + short) | shown | shown |
| One-paragraph judge prose | shown (≤ 80 words) | full synthesis |
| Citations (provider_kind + URLs) | hidden, count only | full list with chunk excerpts |
| Dissent block | hidden | full |
| Scaffolds (PRD, business plan, follow-ups) | hidden | full ResearchResult JSON |
| Original buyer (seller of record) | shown (wallet truncated) | shown |
| Purchase count | shown | shown |

**Why this split:** the teaser is enough to make the verdict *desirable* (you see the verdict token and a hint of the reasoning) but not enough to *substitute* for the purchase. Citations are the load-bearing artifact — that is what a buyer is paying for.

**Pricing model — pick: per-verdict purchase, no subscription in V1.** Each unique wallet pays once per verdict to unlock. Subscriptions are deferred — they couple Gecko to recurring billing infrastructure that x402 does not natively settle, and they dilute the per-artifact framing.

**Why:** the wedge is "judgment you can buy, sell, or stake on." A subscription makes verdicts feel like a feed; a per-verdict purchase makes each one feel like an asset. Subscriptions reopen in V2 if churn data demands it.

---

## 4. x402 paywall pricing + reseller cut

Starting numbers. **Flagged for `business-manager` review before S20 settlement work begins.**

| Party | Cut | Notes |
|---|---|---|
| Original buyer (seller-of-record) | 70% | The wallet that first paid Gecko to produce the verdict. Earns on every resale. |
| Gecko platform | 25% | Operating margin + LLM/embedding cost recovery. |
| Cited Bazaar resource creators | 5% | Pro-rata across cited Bazaar chunk authors. If zero Bazaar citations, this 5% rolls to Gecko (total 30%). |
| **Per-verdict purchase price** | **$2.50 USDC** | One-shot; no recurring. Same price for every viewer after the first buyer. |

**Why these numbers:**
- $2.50 is below the friction threshold for an impulse purchase by a builder evaluating a pre-idea, and high enough to be worth resale promotion.
- 70% to the original buyer makes "research a hot idea, then promote the verdict link" a real GTM channel for power users — they are rewarded for surfacing verdicts that others want to read.
- 25% covers Gecko's per-session unit economics with margin (one Pro session ≈ $1.20 in LLM + embed + rerank cost; one verdict resale at $2.50 × 25% = $0.625 amortizes session cost across ~2 resales).
- 5% to Bazaar creators wires the citation graph into a payout — a small but real signal that Gecko rewards the corpus it stands on. Pattern D-aligned: it deepens the moat by making contributors care.

Math sums to 100. No platform-level secondary-market fee in V1 (deferred — see §6).

---

## 5. Revocation / expiry

**Stance: immutable post-sale, with a 24-hour seller cancellation window before the first resale.**

A verdict cannot be retracted once any wallet other than the original buyer has paid for it. Before that first resale, the original buyer can cancel the listing and remove the verdict from public discoverability (the URL still resolves for them privately; Gecko keeps the hash on file).

**Why immutable post-sale:** the wedge is *ownability*. A verdict that can be silently rescinded is not an asset, it is a blog post. Buyers must be able to trust that the hash they paid for resolves to the same content tomorrow.

**Why a pre-resale cancellation window:** sellers occasionally regret listing (typo in the idea, accidental publish). Letting them cancel before the artifact has any third-party stakeholders is a free UX win that does not break the "ownable" promise.

**False-citation handling:** if a citation is later proven false, Gecko appends an **annotation** to the rendered page (visible to paid viewers) but the hashed verdict body is not mutated. Annotations are signed by Gecko, timestamped, and do not affect the hash. Refunds are not automatic — disputes route to S20+ resolution (see §6).

---

## 6. Open questions deferred to S20+

1. **On-chain settlement contract design.** Solana program vs. off-chain x402 facilitator with periodic batched settlement. Owner: `web3-engineer`.
2. **Dispute resolution.** Who arbitrates a "this verdict is wrong / its citations are fabricated" claim? Bonded reviewers? Gecko-as-judge? Punted until contributor count > 10.
3. **Secondary-market platform fee.** Should Gecko take an additional 2–5% on resales beyond the per-purchase 25%? Modeling deferred until first 100 resales of organic data exist.
4. **Staking semantics.** "Stake on" is in the wedge sentence but undefined here. Open question: stake = bond on a verdict's accuracy and earn from disputes, or stake = pre-pay for a stream of verdicts in a category? Pick in S20.
5. **Bucketed seller reputation surface.** Per `project_output_layer_positioning` and the bucketed-bands convention, sellers eventually need `emerging` / `established` / `senior` badges. Not until contributor count > 10.

---

**Design choices audit trail:** every "Why:" line above is a decision marker. Future audits should check that the wedge sentence in §1 still matches PRD/skill.md/splash verbatim before treating any downstream choice as still valid.
