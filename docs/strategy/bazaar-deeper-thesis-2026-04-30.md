# Bazaar — the deeper thesis

**Date:** 2026-04-30
**Predecessor:** `docs/research/bazaar-as-composer-2026-04-30.md` (5-vector monetization), `docs/strategy/bazaar-composer-decision-2026-04-30.md` (synthesis call), `docs/positioning/2026-04-30-thesis-synthesis.md` (validation layer above frames.ag)

**The user's prompt:** "what Bazaar Marketplace enables us to? I think we can be even stronger on our thesis."

This document goes deeper than the 5 monetization vectors. It asks: what does Bazaar uniquely enable that no prior surface did, and what does that mean for Gecko's positioning?

---

## The single-line thesis (sharpened)

**In the agentic economy, capability is commoditized; judgment is scarce. Bazaar makes capability tradeable. Gecko makes judgment tradeable.**

Or, the operational version: **Bazaar lets agents discover what to buy. Gecko tells them what to build.**

Everything below extends this.

---

## What Bazaar uniquely enables

### 1. Pre-execution authorization at protocol scale

Today's pattern: agent pays → agent acts → user reads outcome. There is no protocol-level mechanism for *"should this agent pay for this thing in the first place?"*. Frames.ag has session policies (max spend, rate limits) — those are *budget* gates, not *judgment* gates. They protect against runaway spend, not against spending on the wrong thing.

Bazaar makes paying easy and discoverable; that *increases* the surface area for paying on the wrong thing. Bazaar without judgment is more agent commerce, not better agent commerce.

**Gecko fills this gap.** Adversarial validation produces a signed verdict (KILL / REFINE / BUILD) before the agent commits real money to a build. The verdict is the missing primitive in agentic spending.

### 2. The verdict as a shared trust artifact

Today, Gecko emits a verdict that exactly one founder consumes. In a Bazaar world, the verdict can be:

- **A reusable reference** — other agents look up "what did Gecko say about validating-flight-rebooking ideas, last 90 days?" without re-running.
- **A token-gated good** — historical Gecko verdicts on similar ideas become a paid corpus (Vector 1+ extended: pay to query the verdict graph, not just generate one).
- **An on-chain commitment** — DeFi contracts could be programmed to *only execute if Gecko's verdict on the underlying thesis is BUILD*. The verdict becomes a smart-contract input.
- **A trust signal in Bazaar's own ranking** — once Gecko has reviewed a Bazaar service, that review can be surfaced by Bazaar's quality ranking (with permission), advantaging Gecko-validated providers.

The verdict moves from one-off output → shared infrastructure.

### 3. Adversarial defaults in a world that defaults to capability

Every agent platform shipping in 2026 optimizes for "make agents easier to ship":
- Anthropic Managed Agents: ship a Claude agent in hours
- Coinbase Bedrock-style stacks: pre-built wallet/MCP/tool surfaces
- Bazaar itself: discover paid services, integrate in minutes

This is deflationary on quality. The bottleneck stops being technical capability and becomes **discrimination**: which of the infinite shippable agents should actually exist?

Gecko inverts the default. We make agents *harder to ship cheaply* by demanding pre-build adversarial validation. In the long run, the most valuable layer in the agentic stack is not the layer that ships agents — it's the layer that *kills bad agents before they ship*.

This is the real thesis macro: **Gecko owns the discrimination layer.** Bazaar is one surface where that discrimination matters; the broader agentic economy is the full TAM.

### 4. Two-sided market with three ICPs

Bazaar creates a two-sided market: sellers want discoverability, buyers want trust. Gecko sits on the trust side. The same adversarial-debate output monetizes against three different ICPs:

| ICP | Why they pay Gecko | Surface |
|---|---|---|
| **Founders** (today's primary) | Validate before building | `bb research --idea "..."` → verdict + PRD |
| **Agents** (Bazaar listing) | Validate before spending | MCP `gecko_research` via Bazaar → verdict |
| **Sellers** (future) | Get reviewed, earn the stamp, rank higher | Inverse Vector 5: services pay to be validated |

The same engine, three buyer surfaces. Same prompts, same RAG, same eval gate. The product has 3x the addressable market without 3x the build.

### 5. Composability against composability — the flywheel

If Gecko's verdict shape is itself listed in Bazaar (as a primitive), other agents can compose against it:

- "Agent that builds vertical SaaS" calls `gecko_research` first, branches on verdict
- "Agent that allocates founder time" pays Gecko before committing weeks
- "Agent that funds early-stage projects" subscribes to Gecko's verdicts as filtration

Network effects emerge:
1. More agents use Gecko → more validation calls
2. More validation calls → more eval data + flywheel signal
3. Better eval data → tighter prompts, sharper verdicts
4. Sharper verdicts → more agents trust Gecko → more agents use Gecko (back to 1)

This is the moat that compounds. The thesis sub-fold ("validation layer above frames.ag") was a placeholder for this flywheel. Bazaar makes the flywheel accessible because it's the surface where agents shop for capabilities.

---

## What this means for Sprint 12–14 commitments

The 5-vector ladder still holds. The deeper thesis sharpens *why* each vector matters:

| Vector | Surface monetization | Deeper claim |
|---|---|---|
| 1: List in Bazaar | Per-call revenue | Gecko shows up in the agent economy's discovery layer |
| 2: Pro+ with bundled sources | Markup | Gecko is the orchestrator, not the data |
| 3: Vertical suites (DeFi, etc.) | Productized SKUs | Domain-specific judgment is more valuable than generic judgment |
| 4: Orchestrator | Base + markup | Gecko is the budget approver for agentic commerce |
| 5: Certification | Sellers pay for review | Gecko's verdict becomes a public-good trust artifact |

The deeper thesis says: **Vectors 4 and 5 are not future revenue lines — they are the real product, and Vectors 1-3 are the bootstrap.** We start by being *one* discoverable validation MCP. We end by being *the* trust primitive that the agent economy verifies against.

---

## What this means for landing copy

The Sprint 11 sub-fold under the apex hero is currently:

> **The validation layer above frames.ag.**
> Agents will spend your money. Gecko approves the spec first — adversarial debate, six sources, fundable PRD — so the budget you fund actually pays for the right work.

After Sprint 12 lists in Bazaar, this can grow into a dual sub-fold (per product-designer's recommendation):

> **The validation layer above frames.ag.**
> Agents will spend your money. Gecko approves the spec first.
>
> **And above the Bazaar, too.**
> Bazaar lets agents discover what to buy. Gecko tells them what to build.

Don't unify into "above any x402 facilitator" yet — wait until the third concrete sub-fold exists (e.g., "above any agentic wallet" once `awal` traction is observable). PD called this right.

---

## What this means for ICP and PRD

The PRD currently names a single V1 ICP (Sprint 11 S11-PRD-01: "Claude Code / Cursor power users with founder ambition — technical or technical-adjacent"). The deeper thesis says we will have **three ICPs over time**:

- **Sprint 12:** founders (current ICP) + Bazaar-discovering agents (new ICP, no PRD work needed because the same MCP surface serves them)
- **Sprint 14+:** sellers seeking Gecko-validation for ranking advantage (new ICP, requires inverse-pricing surface)

Don't update the PRD now. But mark in `docs/strategy/option-set.md` (proposed) that the "agent" and "seller" ICPs are real future surfaces, not afterthoughts.

---

## What this means for the orchestrator price ($29)

The business-manager pricing memo set Vector 4 at "$29 base + 1.5x pass-through markup, no subscription." Under the deeper thesis, $29 is a *bargain* — you're paying to have an adversarial CFO sit between your agent and a thousand vendors, killing the bad spending decisions. The right comparison isn't "5 free LLM queries" — it's "the salary of a junior associate analyst who could read the contracts." That's $5–15k/month at human rates.

When we ship Vector 4, position it as: **"Gecko replaces the analyst who tells you not to do the thing. Per call, not per month."** The deeper thesis is what gives that line teeth.

---

## What I'm NOT saying

Three traps to avoid:

1. **Don't pivot the V1 product.** The founder-validation MCP is correct. The deeper thesis says that product *also* serves agents and sellers — it doesn't say we should rebuild for them. Same engine, broader distribution.
2. **Don't over-claim the trust artifact in V1.** The on-chain commitment surface (verdict-as-smart-contract-input) is V3+. Today's verdicts are JSON in a database; the trust artifact framing is what we *grow into.* Saying it on the apex landing today would be hand-wavy.
3. **Don't let the macro vision distract from Sprint 12 execution.** Vector 1 (listing in Bazaar) is the bootstrap. Without it, all the deeper thesis is air. Ship the listing first.

---

## Open questions worth probing in Sprint 12

1. Does Bazaar's `proxy_tool_call` preserve the original-provider receipt on-chain, or only the proxy hop? (Affects whether Gecko's "verifiable receipt" claim transitively covers downstream calls — staff-engineer flagged.)
2. Does Bazaar quality ranking allow editorial signals (curator-driven) on top of the algorithmic signals (calls + recency)? If yes, Gecko-as-curator (Vector 5) lands earlier.
3. Can a Bazaar-listed service expose multiple tool surfaces under one listing, or is each route a separate entry? (Affects whether `gecko_research`, `gecko_plan`, `gecko_advise` are 3 listings or 1.)

These don't block Sprint 12 — they're things to learn during it.
