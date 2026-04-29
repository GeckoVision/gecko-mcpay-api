# Sprint 4 build plan — "the closing loop"

**Author:** ernani + claude (Sonnet 4.6 via Opus 4.7 1M)
**Date:** 2026-04-29
**Sprint duration:** ~5 working days
**Theme:** From "Gecko gives you a verdict" → "Gecko keeps planning your roadmap with the market in real time."

## Context — what shipped before this sprint

| Wave | Tickets | Status |
|---|---|---|
| Sprint 2 Final | 15 (V1 sources, flywheel, classifier, eval expansion, twit.sh wallet, mainnet runbook) | Done — eval gate verdict_accuracy: general 0.95, crypto 1.0, saas 1.0, holdout 1.0 |
| Sprint 3 | S3-01 scaffold generator + S3-05 gecko_route + v5.4 prompts + landing v2 briefs + PyPI v0.1.4 | Done |
| Smoke + production deploy | API on devnet, real Pro session settled on-chain | Done |
| **Mainnet cutover** | Wallet generated, NOT funded yet | **Deferred — explicit user choice** |

## Sprint 4 priorities (in order)

### 1. Close the feedback loop — Gecko Planner (the marquee feature)

**Why this is #1**: today the loop is one-way (idea → verdict → scaffold → user builds). Sprint 4 closes it: what the market says feeds the next sprint. Per the user's framing — "what the market is saying, will dict how we will evolve our product."

Two new agents that run AFTER the Pro debate:

- **staff_manager** — reasons at the roadmap level. Takes the Pro verdict + flywheel precedents + V1-source signal (twit.sh / HN / Reddit / colosseum) + the user's existing PRD if present. Outputs: "Next 3 sprints should focus on X, Y, Z because A, B, C."
- **product_manager** — reasons at the feature level. Takes the same input + the user's actual user metrics if available. Outputs: a prioritized backlog with named features, named acceptance criteria, named risk-of-skipping.

**S4-PLAN-01: agent definitions + orchestration shell**
New module `packages/gecko-core/src/gecko_core/orchestration/planner/`. Same shape as `pro/`: prompts.py with versioned bundle, agents.py builds the GroupChat, `__init__.py` exposes `generate_plan(session_id, ...)`.

The Planner is NOT a 5-agent debate — it's a 2-agent sequential pipeline (staff_manager analyzes, product_manager prioritizes). Cheaper than Pro, more focused.

**S4-PLAN-02: MCP + CLI surface**
- MCP tool: `gecko_plan` — takes session_id (from a prior gecko_research run) + optional `existing_prd_path` (so we read the user's current PRD if they have one)
- CLI: `gecko plan <session_id> [--existing-prd ./PRD.md]`
- Output: writes `.gecko/plans/<session_id>/sprint_plan.md` with proposed Sprints 1-3, prioritized backlog, and "what to revisit when" trigger conditions

**Pricing**: $0.25 (cheap; doesn't touch x402 wallet — uses gecko_route under the hood). Plans are cheap to generate frequently.

**S4-PLAN-03: precedent-aware re-planning**
The Planner reads `gecko_precedent` for similar ideas and surfaces "Gecko evaluated 4 similar products — 3 shipped successfully by hitting feature X first, 1 stalled because it skipped Y. Recommend X first."

**S4-PLAN-04: pulse mode (weekly digest)**
A scheduled `gecko_pulse <project_id>` that re-runs the Planner against fresh V1-source signal weekly. Free to the user (paid via project budget if attached). Surfaces in MCP as "your Sprint 4 priorities have shifted because [twit.sh shows N builders newly complaining about feature Y]."

**Acceptance**: a real builder can run `gecko_research` → `gecko_scaffold` → builds V1 → comes back next week → `gecko_plan` outputs a v2/v3 plan that reflects what twit.sh + flywheel learned in the meantime.

### 2. Make gecko_route honest about cost (S4-ROUTE-01)

The v0.1.4 release silenced the AG2 cost-attribution WARNING via price-injection (commit `adc268e`). But OpenRouter returns `usage.cost` directly in every API response — that's the canonical billing figure.

Per `docs/openrouter-integration-notes.md`:

```json
"usage": { "prompt_tokens": 194, "completion_tokens": 2, "cost": 0.95, "cost_details": { "upstream_inference_cost": 19 } }
```

**S4-ROUTE-01**: After every routed call, read `usage.cost` from the response and persist that to the session ledger as the source of truth. Our `MODEL_PRICING` table becomes a pre-flight estimator only.

- Add `usage_cost_usd` field to `RouteResult` in `routing/models.py`
- In `routing/__init__.py`: extract `response.usage.cost` (with `getattr` fallback in case the response shape varies)
- Reconciliation alarm in CloudWatch: if `pre_flight_estimate / usage_cost > 1.10` (10% drift), log warning — suggests our price table is stale
- Store the truth: `sessions.cost_llm_usd` updated from `usage.cost`, not from estimate

**S4-ROUTE-02 (Path B)**: Wire `gecko_route` through gecko-api with the same x402 middleware as `/research`. Today `gecko_route` is a free local-only call; this exposes it as a paid surface so it works from Claude Code via the deployed API + frames.ag wallet (not just from a locally-installed CLI). Per S3-05's flagged follow-up.

- Add `POST /route` endpoint to gecko-api with x402 RouteConfig
- Update gecko-mcp's `gecko_route` to forward to the API instead of calling `gecko_core.routing.route` directly
- ~10% markup on routed calls baked in here

**S4-ROUTE-03**: cross-provider fallback via `extra_body.models`. If Anthropic 429s, fall through to OpenAI automatically. Surface `model_used` (which one actually answered) in the demo log line. Per OpenRouter docs.

### 3. Activate twit.sh in Pro debates (S4-TWITSH-01)

Today the twit.sh wallet is funded ($5 USDC on Base mainnet, address `0x7cc33a7B...`), the source dispatcher is wired (S2X-08 client + S2X-10 cache), and the Source Protocol is implemented. But twit.sh isn't actually firing in Pro debates because the dispatcher isn't yet hooked into the orchestration's pre-debate stage.

**S4-TWITSH-01**: Activate twit.sh in `_run_pro_debate` — call `dispatch_sources([TwitshSource(), HackerNewsSource(), RedditSource()], idea, categories)` before the AG2 GroupChat starts, render the results into `rag_context`. Cap total per-session twit.sh spend at $0.05 (already enforced in TwitshSource).

**S4-TWITSH-02**: Add a session-economics line item showing actual twit.sh spend vs cap. This is per-Pro-session telemetry: `sessions.cost_twitsh_usd`.

**S4-TWITSH-03**: Re-baseline the eval gate WITH twit.sh active in `rag_context`. Today the gate fixtures use canned bullets — Sprint 4 should add a "live-rag" gate variant where twit.sh fires for real on a held-out 10-idea suite. Confirm the prompt v5.4 → v5.5 (if needed) doesn't regress when fed real V1-source signal.

### 4. Mainnet cutover (deferred — when user funds the wallet)

Already runbook-ready (`docs/runbooks/mainnet-cutover.md`). The user generated the keypair but explicitly chose to defer funding. When they're ready: Phase 3 of the deploy plan (~30 min). Independent of all S4 features above.

## What's NOT in Sprint 4

Cut these to keep scope tight:

- ❌ Pro+/Studio/Studio Max tier ladder (push to Sprint 5 — tier diversification matters less than feature depth right now)
- ❌ V3 dashboard at app.geckovision.tech (push to Sprint 5 — landing v2 + MCP-native flow is enough audience surface for now)
- ❌ Sample app dogfood marketing (Saturday demo IS the dogfood; no separate sample needed)
- ❌ Live project reconciliation (`gecko_eval_project`) — pushed to Sprint 5; depends on real users having shipped V1s, which won't happen at scale until Sprint 5+
- ❌ `gecko_research_feature` (incremental Pro for new features) — overlaps with Gecko Planner, redundant for Sprint 4
- ❌ MCP marketplace, wellfound positioning, V2 sources — all post-Sprint 5

### 4. Per-role curated model matrix (the OpenRouter moat)

Today both the Pro debate and the new Advisor Panel run on a narrow OpenAI-family slice. OpenRouter exposes 662 text models + 26 embedding models — and most agents in our stack are not running on the best model for their specific task profile. This is a structural moat: ship a curated, benchmarked matrix the user doesn't have to pick from.

**The pitch becomes:** *"Each agent runs on the best model in the world for its task. We picked them. You ship faster."*

**S4-MATRIX-01: ship the catalog + per-role matrix**

**Operational source of truth** (already authored, ready to import):
`docs/external/how_to_build_a_task_based_model/model_database.json` — typed catalog of frontier/premium/premium_value/budget/free models with fields `pricing`, `score`, `score_per_dollar`, `tier`, `strengths`, `weaknesses`, `best_for`, `swe_bench_verified`, `modalities`, `openrouter_rank`. Plus the `GeckoVision Model Routing Strategy.md` + `Quick Reference.md` companion docs that map 15 task profiles × 4 tiers (Quality First / Balanced / Budget / Free).

Concrete steps:
- Copy `model_database.json` to `packages/gecko-core/src/gecko_core/routing/model_catalog.json` (committed — this is operational data, not gitignored external).
- Build `packages/gecko-core/src/gecko_core/routing/catalog.py` with: typed `ModelEntry` Pydantic model matching the JSON schema, `load_catalog()` (lru_cache'd reader), `lookup_model(task: TaskProfile, tier: Tier) -> ModelEntry` selector, and `models_for_role(role: AgentRole) -> dict[Tier, ModelEntry]` for the multi-tier matrix.
- Define `TaskProfile` enum to match the Quick Reference table's 15 categories: `complex_coding`, `simple_coding`, `planning`, `file_navigation`, `code_review`, `general_reasoning`, `creative_writing`, `summarization`, `image_analysis`, `audio_processing`, `tool_calling`, `data_analysis`, `classification`, `long_context`, `math_science`.
- Define `Tier` enum: `quality`, `balanced`, `budget`, `free`.
- Define `AgentRole` enum for both Pro debate (`analyst`, `critic`, `architect`, `scoper`, `judge`) and Advisor Panel (`ceo`, `cto`, `business_manager`, `product_manager`, `staff_manager`).
- Curate `_ROLE_TO_TASK_MATRIX: dict[AgentRole, TaskProfile]` mapping each role to its primary task profile (per the table in §3).
- Extend existing `gecko_core/routing/costs.py` `MODEL_PRICING` to load from the catalog at module init (single source of truth — no duplicate price tables).
- Update `gecko_core/orchestration/pro/router.py` `MODELS_BY_ROUTER` to look up from catalog by `(role, tier)` rather than hardcoded model strings.
- Default fallback: if `LLM_ROUTER=openai` (no OpenRouter), select OpenAI-only subset of catalog (gpt-4o + gpt-4o-mini variants); curated multi-provider matrix is OpenRouter-gated.
- User-facing surface: add `--tier-preset {quality,balanced,budget,free}` arg to `gecko research` / `gecko_research` MCP. Default `balanced`. Lets users dial cost/quality without picking individual models.

This makes the catalog the single source of truth — model bumps (DeepSeek V5 lands, Kimi K2.7 ships) are JSON edits, not code changes.

**S4-MATRIX-02: ablation ahead of shipping**
Before flipping the matrix in production, ablate per-agent on the eval suite to confirm each model bump actually lifts that agent's contribution. Sequence:
- Run baseline (all-gpt-4o-mini except Judge on gpt-4o, current Sprint 3 default) → confirm 1.0/0.95/1.0/1.0 holdout still
- Bump Critic to `claude-sonnet-4-6`, others same → measure
- Bump Architect to `qwen-3-coder`, others same → measure
- Bump full matrix → measure
Only ship matrix changes that lift verdict_accuracy OR maintain it while reducing cost. Cost: ~$5-10 in live API calls for the ablation runs.

**S4-MATRIX-03: marketing surface — "best model per task" claim**
Write a landing v2 section explaining the matrix. Show 3 agent rows with their assigned models + 1-line rationale. Anti-positioning: *"Most AI tools use one model. ChatGPT uses GPT. Claude uses Claude. Cursor lets you pick. Gecko routes each of 5 (or 10) agents to the best model in the world for that specific task — and we keep tuning."*

This becomes a structural feature Kiro cannot match — they're bundled with AWS Bedrock, not OpenRouter, so they're capped at Bedrock's model selection.

**Why this is in Sprint 4**: doing this BEFORE Sprint 4's Advisor Panel ships means the panel launches with the curated matrix already in place — one launch, not two. Doing it AFTER means we re-launch the panel a sprint later with "now smarter" framing, which dilutes the wedge.

**Ablation comes BEFORE marketing**: don't claim "best model per task" until we've measured it. The eval gate is the proof point.

## Order of execution

| Day | Track A (Advisor Panel + matrix) | Track B (gecko_route hardening) | Track C (twit.sh + eval re-baseline) |
|---|---|---|---|
| Mon | S4-MATRIX-01 extend pricing + per-role matrix | S4-ROUTE-01 usage.cost surfacing | — |
| Tue | S4-ADVISOR-01 5 advisor system prompts | S4-ROUTE-02 API wiring (Path B) | S4-TWITSH-01 dispatcher activation |
| Wed | S4-ADVISOR-02 orchestration shell + S4-ADVISOR-03 MCP/CLI | S4-ROUTE-03 cross-provider fallback | S4-TWITSH-02 telemetry |
| Thu | S4-MATRIX-02 ablation runs ($5-10) | (slack for whatever broke) | S4-TWITSH-03 + S4-MATRIX-02 combined re-baseline |
| Fri | S4-ADVISOR-04 project context loader + S4-ADVISOR-05 pulse + S4-MATRIX-03 marketing surface | Demo + integration | — |

Tracks A, B, C are non-overlapping — software-engineer + web3-engineer can run them in parallel.

**Cost envelope for ablation**: S4-MATRIX-02 + S4-TWITSH-03 combined ~$15 in live API calls. The eval gate's 50 ideas × ~$0.005 with curated matrix ≈ $5-7 per full re-baseline. We need 2-3 ablation runs to isolate which model bumps lift accuracy.

## Acceptance for Sprint 4

A user runs:

```
gecko_research "..."          # Sprint 1-2 (existing) — verdict
gecko_scaffold <session>       # Sprint 3 (existing) — PRD + business plan + BUILDING.md
gecko route ...                # Sprint 3 (existing) — credit-saver
gecko plan <session>           # Sprint 4 (new) — Sprint 1-3 priorities for what they're building
# A week later:
gecko pulse <project>          # Sprint 4 (new) — re-planned priorities based on fresh market signal
```

End-to-end: idea → verdict → scaffold → route subagent calls → plan sprints → ship V1 → pulse re-plan v2 → repeat.

That's the full daily-use loop. After Sprint 4, Gecko stops being a tool and becomes the persistent control plane for builders. Per the demand_proof X-signal: that's exactly what the market is asking for.

## What we'll learn from this sprint that informs Sprint 5

The Planner outputs are themselves a market-research signal:
- Which features does the Planner most-frequently propose first? → those are validated SaaS wedges in 2026
- Which features get killed in the Planner's prioritization? → those are saturated patterns  
- Which weekly pulses flip a verdict from "build X next" to "build Y instead"? → real-time market drift signal that Sprint 5 dashboards visualize

Sprint 5 then becomes data-driven by Sprint 4's Planner output, not by our gut. The flywheel grows the moat.

## Open questions to confirm before kickoff

1. **Is `gecko_plan` priced at $0.25 or free?** Free makes adoption easier; $0.25 keeps the unit-economics story consistent. Recommend $0.25 with a "first plan free per session_id" carve-out.
2. **Does the Planner have access to read external repos** (e.g. user's GitHub) for context, or only the gecko_research session? Recommend: only gecko_research session in v1, repo-aware in v2.
3. **Should pulse mode push proactive notifications** (email, Discord webhook) when priorities flip, or only update on `gecko pulse` invocation? Recommend: invocation-only in v1, push-notify in Sprint 5.

These are decisions for the kickoff conversation — not blockers.

## Sprint 5 / 6 follow-ups (out of Sprint 4 scope but committed)

### Native Gecko memory layer (NOT external dep)

User decision: build our own instead of bolting on OneContext / mem0. Reasoning:

1. **Decision-aware structure**: Gecko's memory is typed around the verdict-scaffold-plan-advise loop (`verdict_received`, `scaffold_generated`, `plan_advised`, `feature_shipped` entry types). Generic memory MCPs treat everything as free text — they can't warn "you're contradicting a prior decision" because they don't model decisions.
2. **On-chain anchors**: every paid Gecko call has a Solana tx hash. We can anchor journal entries to these immutable receipts — "what was decided AND when was it paid for" becomes a composable proof, not just notes.
3. **No new dependency**: we already run Supabase + pgvector + OpenAI embeddings + an MCP server. Building memory uses the components we already operate.
4. **Long-term moat**: this is the persistent layer that turns Gecko from "tool you call" into "co-founder you work with daily." Outsourcing it to OneContext means the moat lives in someone else's repo.

**Sprint 5/6 tickets:**
- **S5-MEM-01**: migration `016_memory.sql` — `memory` table with `id`, `scope` (project_id | session_id | user), `entry_type` (typed enum), `key`, `value` (jsonb), `embedding` (vector(1536)), `created_at`, `tx_signature` (optional Solana anchor), `ttl_at`. Index on `(scope, entry_type, created_at)` and ivfflat on `embedding`.
- **S5-MEM-02**: `gecko_core/memory/` module — `save(scope, entry_type, key, value)`, `recall(scope, key)`, `search(scope, query, k=5)`. Pydantic-typed.
- **S5-MEM-03**: MCP tools — `gecko_memory_save`, `gecko_memory_recall`, `gecko_memory_search`. Free (no x402).
- **S5-MEM-04**: auto-journaling hooks — every paid Gecko call (research/scaffold/plan/advise) appends a `verdict_received` / `scaffold_generated` / `plan_advised` / `advisor_voiced` entry automatically. User opt-out via `--no-journal` flag.
- **S5-MEM-05**: `gecko_resume <project_id>` — formatted summary of the last N journal entries scoped to a project. Surfaces "last decided X, currently working on Y, next is Z."
- **S5-MEM-06**: contradiction detection — when a new verdict contradicts a prior one (via embedding similarity + opposite verdict), flag it: "Gecko killed this idea 3 weeks ago for reason X — what's changed?" This is the structurally novel feature.

**Why this isn't Sprint 4**: it depends on the Advisor Panel + Planner shipping first (so journal entry types are stable). Building it Sprint 5+ means we know what to remember.

**For your daily work TODAY**: while we build, install OneContext / mem0 / equivalent if the resume-pain is biting now. We'll migrate when ours ships. No commitment — temporary scaffolding is fine.

### Other Sprint 5+ items
- Pro+/Studio/Studio Max tier ladder ($2 / $5 / $19)
- V3 dashboard at app.geckovision.tech
- `gecko_eval_project` live reconciliation (predicted ICP vs actual user data)
- Auto-refresh of model catalog via LiveBench / Artificial Analysis APIs (cron'd weekly)
- Cross-project flywheel — public-opt-in precedents to grow the corpus

## Reference

- `docs/build-plan-v2-and-beyond.md` — original multi-sprint plan (now superseded for Sprint 4 by this doc)
- `docs/openrouter-integration-notes.md` — OpenRouter API actionable bits (usage.cost, fallback chain)
- `docs/marketing/demand_proof.md` — 8 high-signal X posts validating the "research co-founder" wedge
- `docs/decisions/0001-mainnet-after-v1-sources.md` — ADR governing mainnet cutover trigger
- `tests/eval/live_runs/2026-04-29-*.json` — Sprint 3 eval-gate baselines
