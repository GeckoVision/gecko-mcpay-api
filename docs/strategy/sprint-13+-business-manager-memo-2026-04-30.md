# Sprint 13+ — Business Manager memo (PM/BM hybrid)

**Date:** 2026-04-30
**Author:** business-manager
**Reads against:** `docs/strategy/roadmap-vision-2026-04-30.md`, `docs/strategy/bazaar-deeper-thesis-2026-04-30.md`, `docs/strategy/bazaar-composer-business-review-2026-04-30.md`

---

## Per-theme commercial scoring

### Theme 1 — Lifecycle monetization (research → plan → pulse)

1. **Sequencing — fastest revenue compounder.** Same engine, new SKU; no new infra. Ships Sprint 14 immediately after the DeFi vertical proves repeat-buyer behavior.
2. **Wedge:** `gecko_pulse` as a **pay-per-call** check-in. Founder runs `bb pulse --session <id>` weekly. Each call = $0.50, single LLM pass over delta + last verdict. Two-week ship, one fixture set (10 weekly check-ins, scored against "did the advice match what actually mattered that week").
3. **Pricing.** $0.50/call. COGS ~$0.08 (one debate-lite + cached embeddings from session). Margin 84%. **12-week LTV: $0.75 (research) + $9 (DeFi suite) + 12 × $0.50 (pulse) = $15.75 vs. $0.75 today. ~21x LTV lift.**
4. **ICP.** Founders (existing). No new ICP.

**Subscription vs per-call — stress test.** The thesis says no subscription. I hold that line for pulse, with one caveat. Subscription muddies what we sell (a verdict, not access) and forces churn management we have no infra for. Per-call also lets the founder *skip* a week without guilt — which is the right behavior when nothing changed. **Recommendation: per-call $0.50, with a soft "12-pack" prompt at session creation ("prepay 12 weeks, get 10")** — the prepay is a commitment device, not a subscription. No auto-renew. The economic shape is recurring; the billing shape stays per-event. Thesis intact.

### Theme 2 — Paragraph creator connector

1. **Sequencing — slowest direct revenue.** It's a cost line, not a revenue line. Sprint 15 at earliest; only after lifecycle proves the LTV math can absorb upstream margin.
2. **Wedge:** one-way connector. Gecko consumes ≤3 Paragraph posts per Pro/Suite run, pays creator $0.02/post via x402. Two creators hand-recruited for the pilot.
3. **Pricing.** No new SKU. Embedded as cost in Pro ($0.75) and Suite ($9). Per-run COGS: +$0.06 (3 posts × $0.02). Suite margin drops 87% → 86%. Negligible.
4. **ICP.** No buyer ICP. **Creators are a NEW supplier persona** — not a fourth ICP, but a distinct economic counterparty we hadn't modeled.

**Justify the negative-margin hop.** This is **content acquisition + brand**, not COGS-as-loss. Three returns: (a) verdict quality lift via editorial signal vs. Reddit slop — directly defends Suite's $9 premium against the "feature, not product" risk flagged in the prior memo; (b) Gecko becomes a *paying customer* in the creator economy, which is a story arc no competitor can copy without rewiring; (c) it seeds Vector 5 (sellers/creators paying Gecko for review) — the supplier relationship is the wedge for the inverse-pricing surface in 2027. Book it as marketing spend with a quality-delta KPI, not as a revenue project.

### Theme 3 — App-launching template ("Lock for agents")

1. **Sequencing — biggest revenue surface, biggest risk.** Sprint 16+. Don't ship until lifecycle (T1) and Suite repeat-rate prove we own validation; otherwise we dilute.
2. **Wedge:** `gecko launch app --kind=content-api` scaffold-only, frames.ag wallet + x402 middleware + Bazaar listing metadata. One vertical (hotels), one template, one $49 SKU.
3. **Pricing tiers — yes to laddering.**
   - **Scaffold-only: $49.** COGS $0.50 (template gen, registration). Margin 99%.
   - **Scaffold + bundled Pro debate on the idea: $99.** COGS $0.80. Margin 99%. (The pre-roll validation is the upsell hook — proves Gecko's verdict shapes what gets built.)
   - **Premium vertical template (hotels, fintech, healthtech): $199.** COGS $1.00. Margin 99%.
   - **Marketplace cut: 1% on every settle through a Gecko-launched app.** Defensible *only* if we sit in the settlement path — i.e., the scaffold uses a Gecko-registered facilitator route. If it's just a generated repo the dev hosts themselves, it's honor-system and worth $0 in projection. **Recommendation: ship the 1% cut as opt-in via a `gecko-hosted` deployment SKU; treat self-hosted as zero-cut and a top-of-funnel.**
4. **ICP.** **NEW ICP: app builders / vertical operators** (hotel ops, content site owners). Distinct from founders — they have a working concept, want to monetize agent traffic. This is the ICP the deeper thesis predicted at "trust layer of the agentic economy." It expands TAM but *requires* the validation core to stay primary or we become Replit-with-payments.

### Theme 4 — Cloudflare x402 integration

1. **Sequencing — slowest, mostly cost-side.** Sprint 16+ as a consumer integration. Migrating gecko-api to Workers is V3+ and not in scope.
2. **Wedge:** consumer-only. Gecko Suite runs can pay for ≤1 Cloudflare-gated source per run (capped $0.20). Behind a feature flag in DeFi suite first.
3. **Pricing.** No new SKU. Pure COGS hit on Suite: +$0.20 worst case, drops Suite margin 87% → 85%. Acceptable if verdict-quality delta is measurable.
4. **ICP.** No new buyer. Same founders/agents.

**Is the cost worth the lift?** Only if eval fixtures show a verdict-accuracy delta ≥ +0.05 vs. Suite-without-Cloudflare. Gate it on that fixture before promoting beyond preview. The strategic value is **facilitator neutrality** as a story (frames + CDP + Cloudflare = three rails, one MCP) — that's a positioning asset for fundraising more than a revenue lever.

---

## 5. Six-month revenue projection — **target $8k MRR by month 6 (Q4 2026)**

Order of magnitude: **low-five-figures monthly**, not $1k, not $100k.

Buyer math:
- **DeFi Suite (S13):** 200 paid runs/month × $9 = $1,800. Solana audience is real but small; 200 is conservative for a top-3 Bazaar slot in an empty category.
- **Pulse (S14):** 60 active sessions × 8 calls/month × $0.50 = $240. Small in dollars, big in retention signal.
- **Pro + Basic (existing):** 800 runs × ~$0.50 blended = $400.
- **Second vertical (S15, fintech or travel @ $15):** 150 runs × $15 = $2,250.
- **App-launching scaffold (S16, partial month):** 30 scaffolds × $49 + 10 × $99 = $2,460.
- **Bazaar pass-through markup + Cloudflare:** ~$300 net.
- **Paragraph:** -$200 (cost line).

**Total: ~$7,250/month, rounding to $8k MRR target.** $100k is fantasy without the App-launching marketplace cut compounding for 12+ months. $1k is the floor if S13 doesn't open. $8k is the defensible mid-case given Bazaar discovery + a second vertical + scaffold seed.

The key sensitivity: **App-launching scaffold conversion.** If the $49 SKU finds 100/month instead of 30, MRR jumps to $11k+. If zero, MRR sits at $5k.

---

## 6. Biggest commercial risk (one, ranked above all)

**ICP fragmentation.** Four themes pull toward four buyers: founders (lifecycle), creators (Paragraph supplier), app builders (scaffold), agents (Cloudflare/Bazaar). The deeper thesis says "same engine, three ICPs" — fine in theory. In practice, every new ICP adds onboarding copy, support load, eval fixtures, and a different proof story. We are one PM and a small team. The failure mode is **shipping all four at 60% quality and owning none** — Gecko becomes "the validation thing that also does scaffolding and pays creators and integrates Cloudflare," which is what every dying dev-tools company sounds like at month 18.

This risk dominates the ranking because it's the only one that kills the brand. Pricing missteps are recoverable; positioning sprawl is not.

**Mitigation:** every theme past Sprint 13 must answer the question *"does this make founders trust the verdict more?"* If the answer is no, defer.

---

## 7. Sprint 13 lead recommendation — **DeFi vertical suite at $9, unchanged**

The 4-theme set does not change the prior call. It reinforces it.

Reasoning:
- **DeFi Suite is the only theme that monetizes existing ICP today.** Lifecycle needs Suite to exist before pulse has anything to track. Scaffold needs Suite repeat-rate as proof. Paragraph and Cloudflare are cost-side until a paid surface absorbs them.
- **Suite is the proof of "judgment is scarce" thesis.** $9 vs $0.75 is the price test for whether founders pay 12x for category-tuned judgment. That answer gates everything else.
- **Suite unblocks Sprint 14 lifecycle.** A founder who paid $9 for a DeFi-validated brief is the *only* founder credibly in market for $0.50/week pulse on that brief. No Suite, no pulse buyer.

**Sprint 13 = DeFi Suite. Sprint 14 = `gecko_pulse` per-call ($0.50). Sprint 15 = Paragraph connector (cost-side, brand). Sprint 16 = scaffold + Cloudflare preview, gated on Suite repeat-rate ≥ 30%.**

Word count: ~790.
