# Sprint 13+ — Staff Engineer Synthesis Memo

**Date:** 2026-04-30
**Inputs:** roadmap-vision, bazaar-deeper-thesis, bazaar-composer-decision (all 2026-04-30)
**Lens:** synthesis across ai-ml / software / data / web3

## TL;DR

RECOMMENDATION: **Lifecycle monetization (`gecko_pulse`) leads Sprint 13 if the gate opens; Paragraph connector lands S14; Cloudflare x402 lands S15 (consumer-side only); app-launching template is S16+ and gated on a separate "do we want to be in the scaffolding business" decision.** The four themes are **additive** to the current arc — no roadmap re-anchor required, but theme 4 needs an explicit go/no-go before any tickets cut.

## 1. Per-theme sprint sequencing

| Theme | Slot | Why this slot |
|---|---|---|
| **Lifecycle monetization** (`gecko_pulse`) | **S13 (or S14 if S13 fires DeFi-suite per S12 retro)** | Same engine, new fixture+prompt set. Lowest blast radius, highest LTV expansion, and it converts the existing buyer rather than chasing a new one. The eval gate framework already exists; we extend rubric v2 with "phase=during/ongoing." |
| **Paragraph connector** | **S14** | Concrete wedge for the upstream-monetization pattern. Needs `SourceProvider` seam (pre-paid in S12) + a payable `Provenance.payee_wallet` field. Dependent on Paragraph's API maturity — `dev@paragraph.xyz` outreach is a S13 chore, not a ticket. Don't sequence this in S13 because it pulls web3 + data lanes into the same sprint as DeFi-suite if the gate fires. |
| **Cloudflare x402** (consumer-side) | **S15** | Hono/`x402-fetch` client in `BazaarProvider`-adjacent slot. Adds a third settlement path (Solana via frames.ag, Base via CDP, HTTP via Cloudflare) with no FastAPI migration. The producer-side (deploy gecko-api as a Worker) is **never** in the current arc — that's a V3 question, not S13+. |
| **App-launching template** | **S16+ AND gated** | This is a category change, not a feature. We become a scaffolding-product company. Needs a roadmap-level decision before tickets ship. Argue against it in S13 explicitly: it dilutes the discrimination-layer thesis (we'd be shipping the agents Bazaar-deeper-thesis says we should be killing). |

## 2. Why lifecycle-monetization leads S13 (not the other 3)

**Argument vs Paragraph:** Paragraph is a thinner wedge (one connector) but it requires partner velocity outside our control (API access, payee-wallet attestation). S13 cannot afford an external dependency on the critical path.

**Argument vs Cloudflare:** Pure infrastructure play with zero new buyer. We'd be adding a settlement rail before we've proved the deeper-thesis ICP expansion. S13 should compound revenue on existing buyers.

**Argument vs app-launching template:** Bazaar-deeper-thesis is explicit: *"the most valuable layer is the one that kills bad agents before they ship."* The scaffold makes shipping agents *easier*. Until we resolve that contradiction, no tickets. This isn't a sprint problem — it's a positioning problem.

**Why lifecycle wins:** It's the only theme that (a) reuses the verdict synthesis core, (b) extends LTV without adding a new ICP, (c) has zero external partner dependency, and (d) sharpens the deeper thesis (judgment is recurring, not one-shot — "is this still right?" is more discriminating than "should I build this?").

The conditional from S12 retro stands: if DeFi-suite gate fires, S13 is DeFi-suite + lifecycle prompt-set work in parallel (different lanes — ai-ml on prompts, software on SKU plumbing). If gate fails, lifecycle is the sole S13 thrust.

## 3. Cross-lane risks — seams that need protocol-design pre-tickets

**Lifecycle (ai-ml + software + data):** the seam is `SessionPhase` enum (`pre_product` | `during_build` | `ongoing`) on `Session`. Every fixture, prompt template, rubric row, and verdict renderer branches on it. **Pre-ticket needed:** define the enum + persistence migration before ai-ml writes prompts. If ai-ml ships first, we end up with three forked prompt files instead of one phase-aware template. **Owner:** staff-engineer + data-engineer co-design, ~0.5 day.

**App-launching template (web3 + software + product-designer):** the seam is the **scaffold registry** — where do generated apps' Bazaar metadata, wallet config, and route schemas live? If it lives in `gecko-mcpay-skills` (markdown), product-designer owns it. If it lives in `gecko-core` (Python module), software owns it. If it lives as a separate repo (`gecko-mcpay-templates`), staff-engineer owns the cross-repo contract. **This decision precedes any S16 ticket.** The wrong choice locks us into a maintenance burden we won't see for two sprints.

**Paragraph + Cloudflare collision:** both extend `SourceProvider` with payment side-effects. **Risk:** two providers each invent their own payee-attribution shape. **Mitigation:** when S14 Paragraph lands, formalize `Provenance.payment` as the contract — Cloudflare in S15 must conform, not extend.

## 4. The boundary, revisited

The non-composable core named in the S12 staff-eng review (verdict synthesis, adversarial debate, memory/flywheel, classifier+router) **does not change** under these four themes. Lifecycle, Paragraph, Cloudflare are all *upstream* of the verdict — they widen the evidence funnel; they don't touch synthesis.

**App-launching template is the exception.** It introduces a genuinely new first-party surface: **the scaffold/template registry itself.** That registry is not commodity — its curation, vertical taxonomy, and "pre-validated by Gecko" stamp are the first-party trust artifact. If we ship theme 4, the boundary expands to include `{ verdict synthesis, adversarial debate, memory/flywheel, classifier+router, scaffold registry }`. That's why theme 4 needs the positioning decision first: it's the only theme that grows the moat surface, which is also why it's the only one that can dilute it.

## 5. Sprint 13 architectural pre-payment (~1 day)

**Pre-pay: `SessionPhase` enum + phase-aware fixture loader.**

- Add `SessionPhase = Literal["pre_product", "during_build", "ongoing"]` to `gecko_core/sessions/models.py`.
- Default existing sessions to `pre_product` via migration (idempotent).
- Refactor fixture loader in eval harness to dispatch on phase: `fixtures/{phase}/{vertical}/*.yaml`. Existing fixtures move to `fixtures/pre_product/`.
- Add `phase` to rubric v2 row schema (nullable; defaults pre_product).
- **No new prompts this sprint.** The seam is the deliverable.

**What it unblocks:**
- S14 `gecko_pulse` ships in 3 days instead of 2 weeks (drop `during_build` fixtures + prompts into the slots; eval gate already routes correctly).
- S15 lifecycle SKU pricing lands without re-instrumenting telemetry.
- Avoids a fork where pre/during/ongoing become three parallel prompt directories.

Mirrors the S12 `SourceProvider` move: cheap structural seam now, multi-day refactor avoided later. Pattern is becoming a recurring one — I'd flag it in `CLAUDE.md` recurring patterns once we have a third instance.

## Roadmap re-anchor verdict

**Additive, not a re-anchor.** Themes 1-3 ride the existing arc:
- Lifecycle = LTV expansion on existing ICP (founders + agents)
- Paragraph = first instance of the upstream-monetization pattern that bazaar-deeper-thesis already named
- Cloudflare = third settlement rail under existing wallet/facilitator-neutrality claim

**Theme 4 is the exception and requires a separate positioning decision** before it enters any sprint plan. It's not Sprint 13's problem; it's a thesis-level call. The right sequencing is: ship S13-S15 (lifecycle, Paragraph, Cloudflare), gather signal on whether "trust layer of agentic economy" lands, *then* decide whether the scaffolding business is the next surface or a category trap.

## Open questions

1. Does `gecko_pulse` need a new MCP tool surface or is it `gecko_research` with a `phase` parameter? (Staff-eng lean: parameter, not new tool — preserves Bazaar listing simplicity.)
2. For theme 4: do we treat the scaffold-registry decision as a Sprint 15 retro question, or does it warrant a dedicated thesis doc round (analogous to bazaar-deeper-thesis)? Lean: dedicated thesis round.
