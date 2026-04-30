# Bazaar-as-composer — staff engineering review

**Date:** 2026-04-30
**Inputs:** `docs/research/bazaar-as-composer-2026-04-30.md`, `docs/research/cdp-bazaar-2026-04-30.md`, `docs/build-plan-sprint-12.md`
**Reviewer:** staff-engineer

## TL;DR

RECOMMENDATION: **(c) Different framing — ship Vector 1 in Sprint 12 as planned, but pre-pay one architectural debt this sprint (a `SourceProvider` protocol seam) so Vector 2 in Sprint 13 is a 3-day add, not a 3-week refactor. Defer Vectors 3-5 to a strategic option set; do not commit them until Bazaar traffic > 0.**

The composer reframe is correct as positioning. It is wrong as a sprint commitment right now. The thesis sub-fold ("validation layer above frames.ag") **extends** under composer framing — we become the judgment layer above any commodity data substrate, not just frames.ag. But committing Vectors 1-3 over Sprints 12-14 trades a known-shippable Monday-demoable Vector 1 for a multi-sprint refactor whose payoff depends on (a) Bazaar provider quality we don't control and (b) traffic that doesn't exist yet.

The right move is **a small, cheap seam now** that makes the composer pivot a configuration change later.

---

## 1. Architecture blast radius

Three concrete seams need work if we commit to the composer path. Two are cheap; one is real.

### 1a. Source dispatcher (`packages/gecko-core/src/gecko_core/ingestion/`)

Today's discovery returns `SourceCandidate` from a single backend (Tavily), then `pipeline.ingest()` extracts content per URL via `httpx` + `youtube_transcript_api`. That's a **monolithic dispatcher with two source types** (`web`, `youtube`).

For N x402 providers we need:

- A `SourceProvider` Protocol (in `gecko_core/ingestion/providers/__init__.py`) with `name`, `cost_estimate()`, `health()`, async `fetch(query) -> list[SourceChunk]`, plus `kind: Literal["free", "x402-bazaar", "first-party"]`.
- Existing Tavily/Reddit/GitHub/twit.sh become `FreeProvider` subclasses. New `BazaarProvider` wraps a CDP MCP `proxy_tool_call` invocation.
- `discover()` becomes `dispatch()`: `asyncio.gather(*[p.fetch(...) for p in selected_providers], return_exceptions=True)` with per-call timeout (recommended: 3.5s p50 budget per provider, 6s hard cap) and a `degraded_sources: list[str]` field added to `IngestionResult` so the critic agent can surface gaps in-debate.
- The existing `_BLOCKED_DOMAINS` and `_CATEGORY_QUERY_HINTS` logic in `discovery.py` lines 51-114 stays Tavily-specific — it's the FreeProvider's internal config, not the dispatcher's concern.

**Cost to introduce protocol seam now (Sprint 12):** ~1 day. Cost to retrofit later (Sprint 13/14): 3-5 days plus risk of breaking the live eval gate. **Pre-pay this.**

### 1b. Idea classifier growth

The classifier referenced from `discovery.py:11-19` (`gecko_core.classify`) currently returns category labels (`crypto`, `defi`, `devtools`, `saas`, `regulated`, `hackathon-team`) that drive Tavily query hints. For composer mode it needs a second output: a **provider plan**.

Cleanest seam: add `gecko_core/orchestration/provider_router.py` (new file) that takes `(idea, categories, tier) -> ProviderPlan(free=[...], paid=[...], budget_usd=...)`. Classifier stays as-is; routing becomes a separate, testable pure function. This decouples "what is this idea about" from "which APIs do we hit" — they grow at different rates.

### 1c. Right seam between Gecko-owned and Bazaar-routed

Your hint is correct, with one refinement. The boundary is **provenance**, not source identity:

- **First-party (must stay Gecko-owned):** session memory layer, embedding store, twit.sh judge ingestion (we have a relationship there), the `Verdict` synthesis, the multi-agent debate orchestration (`orchestration/pro.py` GroupChat), the eval-gate fixtures.
- **Commodity (can route through Bazaar):** Reddit, GitHub, news, vertical APIs (Amadeus, FlightAware, Plaid-equivalent), generic web scraping.
- **Tavily is in the gray zone.** Tavily today is doing *discovery* (which URLs) plus *summarization* (Tavily Extract). Discovery is a Gecko-owned function — it depends on our category classifier and blocklist tuning. Extraction is commodity. Don't migrate Tavily in V1; reconsider in V3.

The seam: `SourceProvider.kind` plus a `Provenance` field on every `Citation` so the verdict-renderer can show "evidence from <provider>, paid via <facilitator>, $0.05" without changing the verdict shape.

---

## 2. The "should we" call — argued

**Pick: (c).** Sprint 12 = Vector 1 + a single architectural pre-payment (the `SourceProvider` Protocol). Sprint 13 = re-evaluate based on **two signals only**:

1. Did any Bazaar agent traffic actually hit gecko-api in the 7-14 days post-listing?
2. Did we identify ≥1 Bazaar provider with proven volume + clean schema in a vertical we care about?

If both yes → Vector 2 with one vertical (probably travel — best Bazaar coverage per the landscape probe). If either no → stay on Vector 1 and double down on the Claude Code skill flywheel.

**Why not (a) — full composer commit:**
- Vectors 2-3 depend on provider quality we don't yet have evidence of. The probe found OrbisAPI proxies at 1-5 calls/30d — that's not "providers we can build a margin on", that's vapor.
- Latency budget (5-10s extra per call) hurts the demo. Pro tier today already runs 30-60s; doubling that on idea-validation calls is a positioning hit ("slower than just using Claude").
- Margin compression: bundling cheap commodity calls and marking up 5x only works if buyers can't easily replicate. If Vector 4's *agents* are the buyers, they can — they just call the providers themselves. The composer story works for *humans*, less for autonomous agents.

**Why not (b) — pure Vector 1:**
- Leaves the architectural debt unpaid. We will inevitably add a second provider (twit.sh judge data already lives outside the current dispatcher); doing it without a seam means a one-off branch in `discover()` that calcifies.

**Does composer reframe extend or dilute the thesis sub-fold?**
**Extends it,** *if* we hold the line on what stays first-party. The phrase "validation layer above frames.ag" was always a placeholder for "validation layer above the commodity payments+data substrate." Composer makes that explicit. It dilutes only if we let the verdict synthesis or debate orchestration become composable — which is the boundary defended in §4.

---

## 3. Scaling tradeoffs — keeping the adversarial layer fast when upstream is unreliable

Three levers, in order of impact:

1. **Decouple latency: parallel fan-out + speculative execution.** The provider dispatcher (§1a) calls all selected providers concurrently with `asyncio.gather`. Hard per-call timeout = `min(provider.p95_latency * 1.5, 6s)`. Whatever returns by deadline goes into the RAG context; the rest are recorded as `degraded_sources`. **Critic agent in `pro.py` is instructed to flag missing data as a real critique** — turning a failure mode into a feature ("we couldn't verify FAA reliability because FlightAware was unreachable; treat the verdict as conditional"). This is genuinely differentiated; no other validation tool does this.

2. **Cache hard at the chunk layer.** A given (provider, query) pair is hashed → `chunks` table keyed by `url_hash`. If FlightAware was hit yesterday for "regional jet startup", reuse those chunks for another regional-jet idea today, *as long as the provenance + freshness window is preserved*. This reduces both latency and per-call cost. The pgvector store (`infra/supabase/migrations`) already supports this; we just need a `provider_query_hash` index.

3. **Circuit breaker + provider health gating.** Before sending a paid call, check a 5-minute rolling success rate per provider (in-memory cache, Redis later). If < 80%, skip and emit a `degraded_sources` note. Prevents 4xx/5xx cascades from compounding into a busted verdict at the user's expense. Cost: 1 day to implement, lives in `gecko_core/ingestion/providers/health.py`.

The orthogonal cost-variance lever: **bound the per-session paid budget upfront**. `ProviderPlan.budget_usd` is computed at classification time, displayed to user before payment, and enforced in the dispatcher. If a provider raises prices, we drop low-priority providers from the plan rather than blowing the budget.

---

## 4. The boundary I would defend (validating your hint)

**Validated, with one addition.** The non-composable core is:

1. **Verdict synthesis** (`workflows.research` final step → `Verdict` shape). This is the IP. Composing it would mean letting another service emit our `KILL/REFINE/BUILD` shape — that destroys the brand and the eval-gate's integrity.
2. **Adversarial debate orchestration** (`gecko_core/orchestration/pro.py` AutoGen GroupChat). The agent personas, prompts, turn structure, and critic-arms-the-skeptic pattern are the moat. Never make this a Bazaar-callable API; that's how OrbisAPI eats us.
3. **Memory / flywheel layer** (sessions, chunks, embeddings, eval-gate fixtures, live-V1 holdouts). The compounding asset. Bazaar quality ranking signals feed this; this never feeds Bazaar.
4. **(Addition) The category classifier and provider router** (`gecko_core.classify` + the proposed `provider_router.py`). This is the "which APIs to bundle" intelligence. If this becomes composable, we become a thin storefront over Bazaar's own search. Keep it first-party, keep it improving against our eval set.

What can be composable: every individual data source, including Tavily eventually. The litmus test: "if we replaced this component with a competitor's, would Gecko still be Gecko?" If yes, it's composable. If no, it's first-party.

---

## Concrete asks for Sprint 12

- **Add to Track B (Bazaar declarations):** define `SourceProvider` Protocol + refactor `discover()` + `pipeline.ingest()` to call through it. Existing Tavily/web/youtube paths become the default `FreeProvider`. **No new provider implementations this sprint.** ~1 day for software-engineer.
- **Add to Track E (Bazaar-as-source feasibility):** explicit go/no-go gate based on (i) post-listing agent traffic and (ii) one named provider in a chosen vertical with > 100 calls/30d. Defer the Vector 2 commit to Sprint 13 retro.
- **Do not** add the orchestrator (Vector 4), certification (Vector 5), or vertical suites (Vector 3) to any committed sprint. Park them in a `docs/strategy/option-set.md` so business-manager can refer to them when talking GTM, but no code commitment.

## Open questions

1. Does the x402 Python SDK on PyPI cover CDP-facilitator Solana settlement, or only EVM? If EVM-only, Track A in Sprint 12 needs a hand-rolled Base path (likely fine; documented in the plan) but pricing of `awal` Solana parity gets murky.
2. Bazaar `proxy_tool_call` semantics: does it preserve original-provider receipts on-chain, or only the proxy hop? Affects whether Gecko's "verifiable receipt" claim transitively covers downstream Bazaar costs. Investigate before committing Vector 2.

---

## Files referenced

- `packages/gecko-core/src/gecko_core/workflows.py`
- `packages/gecko-core/src/gecko_core/ingestion/__init__.py`
- `packages/gecko-core/src/gecko_core/ingestion/discovery.py` (classifier + hint logic that stays first-party)
- `packages/gecko-core/src/gecko_core/ingestion/pipeline.py` (refactor target for `SourceProvider` seam)
- `packages/gecko-core/src/gecko_core/orchestration/pro.py` (adversarial debate — non-composable)
- `packages/gecko-core/src/gecko_core/payments/x402_client.py` (Sprint 12 Track A parallels its structure)
- `docs/build-plan-sprint-12.md` (to be amended with the SourceProvider seam)
