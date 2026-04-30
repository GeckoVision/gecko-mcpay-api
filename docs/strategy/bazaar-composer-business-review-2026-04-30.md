# Bazaar-as-composer — business review

**Date:** 2026-04-30
**Author:** business-manager
**Status:** Strategy memo. Drives Sprint 13 scope, landing v3, and PRD edits in a later sprint. Does not edit landing or PRD.
**Reads against:** `docs/research/bazaar-as-composer-2026-04-30.md`, `docs/research/cdp-bazaar-2026-04-30.md`, `docs/marketing/landing-copy-v2.md`

---

## 1. The V1 commercial wedge — pick **Vector 3 (vertical suites)**, not Vector 2

**Recommendation: Sprint 13 ships one vertical suite end-to-end. Not a generic Pro+.**

Vector 2 (Pro+ with bundled Bazaar sources) is the safe answer. It's also the wrong one. Pro+ as a horizontal upsell asks the buyer to believe "more sources = better verdict" — a quality claim we cannot prove inside one sprint, and one that gets squeezed the moment a competing MCP bundles the same Bazaar feeds.

A vertical suite asks them to believe something different and provable: **"Gecko knows travel/fintech/DeFi the way a domain analyst would."** That claim is defended by:

- A category-specific prompt + critic agent
- A category-specific source mix (the right Bazaar APIs for that vertical)
- A category-specific eval fixture (10–20 ideas in that vertical, scored)

That is a moat. Pro+ is a SKU.

Pick **DeFi protocol** as the first vertical, for three reasons:
1. Helius + DefiLlama + on-chain data are already partly built — lowest engineering cost.
2. Solana is our existing audience. We sell to people we already reach.
3. Bazaar's current top-quality crypto entries (`capminal.ai`, etc.) are token-research, not protocol-validation. The slot is empty.

Travel is the *demo* vertical for the pitch deck. DeFi is the vertical we *ship and sell* in Sprint 13. Travel comes Sprint 14 once the suite pattern is templated.

**Vector 1 still ships in Sprint 12.** This memo is about what comes after.

---

## 2. Pricing — push back on $1.50

The composer doc's $1.50 anchor for Pro+ is wrong twice over.

**Cannibalization risk is real.** Pro at $0.75 → Pro+ at $1.50 is a 2x step for "more sources." The buyer who would have paid Pro asks: "do I need the extra sources?" Most will guess no. Pro revenue softens, Pro+ doesn't pick up enough volume to compensate. Classic mid-tier trap.

**Sub-$3 leaves money on the table for verticals.** The landing v2 document already references $19–49/run founder SKUs. A DeFi protocol founder paying $19 for a protocol-validation suite with 5 specialist agents, on-chain receipts, and DefiLlama-grounded citations is *not* a stretch — it's underpriced relative to what a Solana dev shop charges for an hour of advisory.

**Recommended price ladder (post-Sprint 13):**

| Tier | Price | Position | COGS target | Margin |
|---|---|---|---|---|
| Free (stub) | $0 | Try the flow | $0 | — |
| Basic | $0.10 | Single LLM pass, 3 docs | $0.012 | 88% |
| Pro | $0.75 | 5-agent debate, 6 sources | $0.16 | 79% |
| **(skip the $1.50 mid-tier)** | | | | |
| **Vertical Suite — DeFi** | **$9** | Category-tuned, Bazaar-bundled, 5 agents, on-chain receipt | ~$1.20 | 87% |
| **Vertical Suite — Fintech / Travel / SaaS** | **$12–19** | Same shape, more expensive Bazaar bundles | ~$1.50–$2.50 | 85%+ |

The jump from Pro ($0.75) to Suite ($9) is a **product jump**, not a tier jump. Different buyer intent: Pro = "is this a real idea?" Suite = "I'm going to build in this category, give me the validated brief." That gap protects Pro from cannibalization.

**Orchestrator pricing (Vector 4, V3 territory):** **hybrid, not subscription.** A flat sub muddies what Gecko sells (a verdict, not access). Recommend:
- **$29 base orchestration fee per run** — covers planning + verdict synthesis + receipt
- **+ pass-through of bundled Bazaar calls at 1.5x markup** — transparent line items in the receipt, capped per run
- **No monthly sub.** Founders don't validate weekly; charging them like SaaS misreads the use case.

The receipt block on landing already trains buyers to expect line items. Lean into that — it's our pricing differentiator vs. opaque consultancy SaaS.

---

## 3. GTM positioning — **(a) sharpen, with one concession**

**Recommendation: keep "founder validation" as the external promise. Composer is internal architecture, not external positioning.**

The thesis sub-fold "validation layer above frames.ag" is the cleanest sentence we own. Generalizing to "judgment layer for any agent that buys things" is true but unsellable: there is no buyer searching for that today. Founders search for "is my idea good." Agents don't search at all — their humans do, and humans search by problem.

The composer reframe matters internally: it tells the engineering team what to build (route, don't ingest) and tells investors the moat (judgment, not data). It does **not** belong on the apex landing.

**One concession to broadening:** the *Bazaar listing metadata* (Vector 1) should describe Gecko in agent-search terms — "founder validation," "competitor research," "PRD generation," "product research." That's not positioning drift; that's SEO for the agent layer. The agent doesn't read landing copy; it reads JSON Schema and semantic-search snippets.

So: **two surfaces, two voices.**
- `geckovision.tech` apex (humans): "Plan your next app for ten cents." Founder-validation, period.
- Bazaar listing (agents): broad capability tags, schema-rich, ranked by usage.

Both feed the same gecko-api. Same product, two discovery paths.

---

## 4. Success metrics — what tells us in 6 months the composer bet was right

1. **Vertical suite revenue ≥ 40% of Gecko revenue by Q4 2026.** If suites haven't displaced Pro as the dollar majority, the bet didn't compound.
2. **Bazaar-originated calls ≥ 25% of paid runs.** Distribution claim from `cdp-bazaar` doc. If skill-installed humans still drive >75% of traffic, the agent-side surface didn't materialize and Vector 4 is dead.
3. **Repeat-buyer rate on suites ≥ 30%.** Founders re-running the same vertical (pivots, new ideas) is the signal that the suite earned trust. One-and-done means we shipped a novelty.
4. **Bazaar quality rank: top-3 in "founder validation" / "product research" semantic slots.** Defendable position in the discovery surface that drives Vector 4.
5. **Verdict-accuracy delta on vertical eval fixtures ≥ +0.10 vs. horizontal Pro.** If DeFi-tuned Gecko doesn't beat generic Gecko on DeFi ideas, the suite is marketing, not product.

If 3 of 5 hit, the composer thesis is validated and we commit Sprint 16+ to Vector 4. If fewer than 3, we hold at Vector 3 and stop.

---

## 5. Biggest commercial risk

**The biggest commercial risk is that vertical suites are a feature, not a product — and the buyer who'd pay $19 for one would rather pay $0.75 for Pro and read the verdict themselves.**

Restated: founders are price-sensitive and intellectually proud. The verticalization premium assumes they'll pay 12x for "we picked the sources for you." A meaningful slice will say "I'll pick them myself" — especially the technical Solana audience that is our beachhead. If we can't show, in the verdict itself, a claim a generic Pro run could not have made (a DefiLlama TVL chart referenced inline, a Helius wallet-cluster citation, a regulatory-tail risk surfaced from a fintech-only critic prompt), the suite collapses to Pro-with-extra-steps.

**Mitigation, in order of leverage:**
1. **Don't ship the suite without 3 category-only agent prompts.** A "DeFi critic" that knows TVL collapse patterns is the unit of value. Generic critic + DefiLlama feed is not.
2. **Show the delta in the verdict.** The receipt should literally include: "5 of 23 citations came from DeFi-only sources you would not have queried." Make the markup visible.
3. **Don't price the first suite at $19.** Launch DeFi at **$9** to seed adoption and case studies; raise to $12–15 once we have 3 testimonials. Travel/fintech can launch higher because the buyer is less technical and less proud.

Secondary risk worth flagging: **Bazaar provider reliability.** Per the composer doc, OrbisAPI proxies have <5 calls / 30 days. We should not bundle a provider with no production traffic. Curation policy before Sprint 13: a Bazaar source enters our suite only after (a) ≥100 calls/30d on its own listing, or (b) a manual reliability test of 50 calls with <2% error. This is a `data-engineer` + `staff-engineer` decision to formalize.

---

## Decision summary (one screen)

- **Sprint 13 wedge:** DeFi vertical suite. Not a horizontal Pro+.
- **Skip $1.50 mid-tier.** Price ladder: Free / $0.10 / $0.75 / $9 (DeFi) / $12–19 (other verticals).
- **Orchestrator (V3):** $29 base + 1.5x pass-through markup. No subscription.
- **Positioning:** sharpen on founder validation for humans; broaden tags on Bazaar listing for agents. Two surfaces, two voices, one product.
- **Six-month gate:** 3 of 5 metrics → commit Vector 4. Fewer → hold at Vector 3.
- **Biggest risk:** suite-as-feature collapse. Mitigation: category-specific critic prompts, visible source-delta in the receipt, $9 launch price to seed.

Next concrete moves (not this sprint):
- `staff-engineer`: scope the suite architecture as a templated overlay on Pro, not a fork.
- `data-engineer`: write the Bazaar provider curation policy.
- `business-manager` (me): draft landing v3 *only after* Sprint 13 ships, with a real DeFi case study as the proof block.
