# Sprint 5 build plan — "persistent decisions + production hardening"

**Author:** ernani + claude
**Date:** 2026-04-29
**Sprint duration:** ~5 working days
**Theme:** Memory becomes a first-class feature. The follow-ups Sprint 4 deferred land. Dashboard MVP gets the user-facing flow on app.geckovision.tech.

## What shipped before Sprint 5

| Sprint | Marquee | Status |
|---|---|---|
| 2 Final | Eval gate, V1 sources, classifier, flywheel, mainnet runbook | Done |
| 3 | Scaffold generator, gecko_route, v5.4 prompts, landing v2 briefs, PyPI v0.1.4 | Done |
| 4 | Model catalog (per-role matrix), gecko_route hardening (usage.cost + /route + fallback), twit.sh active in Pro debate, **5-voice Advisor Panel + pulse mode** | Done |

End-to-end builder loop now works inside Claude Code via MCP:

```
gecko_research → gecko_scaffold → gecko_route (subagent calls) → gecko_plan / gecko_advise → gecko_pulse
```

What's missing for "daily companion that compounds": **persistent decision memory**. Today every loop iteration is fresh. The Advisor Panel can't say "you contradicted last week's CEO priority." The flywheel only fires on new ideas, not on the same project's evolution.

Sprint 5 fixes that.

## Sprint 5 priorities (in order)

### Track A — Native gecko memory layer (THE marquee)

User decision (Sprint 4 lock-in): build our own instead of bolting on OneContext / mem0. Reasoning:

1. **Decision-aware structure** — typed entry types around the verdict-scaffold-plan-advise-pulse loop. Generic memory MCPs treat everything as free text and can't model "this contradicts a prior decision."
2. **On-chain anchors** — every paid Gecko call has a Solana tx hash. Journal entries anchor to immutable receipts.
3. **No new external dependency** — Supabase + pgvector + OpenAI embeddings + MCP server are already operating.
4. **Long-term moat** — outsourcing memory means the moat lives in someone else's repo.

**S5-MEM-01: migration `018_memory.sql`**
Schema:
```sql
CREATE TABLE memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type TEXT NOT NULL CHECK (scope_type IN ('project','session','user')),
  scope_id TEXT NOT NULL,
  entry_type TEXT NOT NULL,  -- 'verdict_received','scaffold_generated','plan_advised','advisor_voiced','pulse_run','feature_shipped','user_note'
  key TEXT,                  -- optional named key for exact-match recall
  value JSONB NOT NULL,
  embedding VECTOR(1536),    -- text-embedding-3-small
  tx_signature TEXT,         -- optional Solana anchor
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ttl_at TIMESTAMPTZ          -- optional expiry
);

CREATE INDEX idx_memory_scope ON memory (scope_type, scope_id, entry_type, created_at DESC);
CREATE INDEX idx_memory_embedding ON memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_memory_ttl ON memory (ttl_at) WHERE ttl_at IS NOT NULL;
```

RLS: read-all (or scope-bound for project owners), delete-own. Mirror gecko_precedent's RLS pattern.

Plus `gecko_memory_search` SQL RPC (cosine similarity, top-k filtered by scope).

**S5-MEM-02: `gecko_core/memory/` module**
Public API:
```python
class MemoryScope(BaseModel):
    type: Literal['project','session','user']
    id: str

class MemoryEntryType(str, Enum):
    verdict_received = "verdict_received"     # auto on gecko_research
    scaffold_generated = "scaffold_generated" # auto on gecko_scaffold
    plan_advised = "plan_advised"             # auto on gecko_plan
    advisor_voiced = "advisor_voiced"         # auto on gecko_advise (single voice)
    pulse_run = "pulse_run"                   # auto on gecko_pulse
    feature_shipped = "feature_shipped"       # manual via gecko_memory_save
    user_note = "user_note"                   # manual

class MemoryEntry(BaseModel):
    id: UUID
    scope: MemoryScope
    entry_type: MemoryEntryType
    key: str | None
    value: dict[str, Any]
    embedding: list[float] | None
    tx_signature: str | None
    created_at: datetime

async def save(scope, entry_type, value, key=None, tx_signature=None) -> UUID
async def recall(scope, entry_type=None, key=None, limit=20) -> list[MemoryEntry]
async def search(scope, query: str, top_k=5) -> list[tuple[MemoryEntry, float]]
async def delete(entry_id, requesting_user_id) -> None
```

Embeddings via existing `gecko_core.ingestion.embedder` with retry + concurrency cap.

**S5-MEM-03: MCP + CLI surface**
- `gecko_memory_save(scope, entry_type, value, key?)` — free
- `gecko_memory_recall(scope, entry_type?, key?)` — free
- `gecko_memory_search(scope, query, top_k?)` — free
- `gecko memory <subcommand>` CLI mirroring the MCP

**S5-MEM-04: auto-journaling hooks**
Every paid Gecko call (research / scaffold / plan / advise / pulse) auto-appends a typed memory entry on success. Hooks live in `gecko_core/workflows.py` (research) and the orchestration `__init__.py` files (scaffold, advisor).

Each entry's `value` includes:
- For `verdict_received`: idea text, verdict, scores, sources count, tx_signature
- For `scaffold_generated`: session_id, output paths, file sizes, total tokens
- For `plan_advised`: closing lines from all 5 voices, tier_preset, total cost
- For `advisor_voiced`: role, closing line, model_used
- For `pulse_run`: prior_panel_id, current_closing_lines, deltas

Opt-out: `--no-journal` flag on every call (default ON). Per-project opt-out via `project_settings.journal_enabled` for users who don't want to retain history.

**S5-MEM-05: `gecko_resume <project_id>`**
Free MCP tool + CLI. Walks the project's memory entries from the last 30 days (configurable), groups by entry_type, surfaces:

```
Project: <name>
Last activity: 3 days ago

Recent decisions:
  2026-04-26 SHIP — "Carta-aware cap table diff for early-stage founders"
              session 12841e51, scaffold at .gecko/scaffolds/12841e51/
  2026-04-23 KILL — "AI tax preparer without CPA"
              session aa3abd99 (no scaffold)

Last advisor panel (2026-04-26):
  CEO: lock the design-partner LOI with Carta this sprint
  CTO: ship the SAFE-diff parser before any UI polish
  PM: side-by-side SAFE diff with MFN highlighted

Pulse delta vs. prior week (2026-04-19):
  CEO priority shifted: "raise seed" → "lock LOI" (twit.sh signal: 4 builders complaining about Carta cap table fees)
```

This is the "where I left off" superpower. Sub-second to render (one indexed query + group), saves ~5K tokens vs. re-deriving from chat history.

**S5-MEM-06: contradiction detection**
When a new verdict / advisor priority lands, run a search against same-scope prior entries with cosine similarity ≥ 0.78. If a near-duplicate exists with an OPPOSING outcome (kill-vs-ship, contradicting closing lines), flag it inline:

> ⚠️ **Contradicts a prior decision.** 3 weeks ago, Gecko killed "AI tax preparer without CPA" — and your CEO advisor today says "ship AI estate planner with attorney in loop." The pattern is similar (regulated financial advisory). **Difference:** estate planner has the licensed attorney in loop; tax preparer didn't. Ship is justified, but flagging.

Renderer logic in `gecko_core/memory/contradictions.py`. Surfaces in the MCP response payload + a CLI banner.

This is structurally novel — no off-the-shelf memory MCP does decision-aware contradiction detection. It compounds with the flywheel: every paid call refines what counts as "similar."

### Track B — API hardening (Sprint 4 follow-ups)

**S5-API-01: paid `POST /plan` endpoint**
Currently `gecko_plan` calls `gecko_core.orchestration.advisor.generate_panel` directly (free MCP/CLI path, mirroring scaffold). For production frames.ag wallet attribution + revenue, wire it through gecko-api with x402 middleware. Pricing: $0.25 per panel call. Same RouteConfig pattern as `/research` and `/route` (Sprint 4 S4-ROUTE-02).

**S5-API-02: `pulse_runs` persistence + project walk**
Migration `019_pulse_runs.sql` — `(id, project_id, session_id, panel_json, deltas_json, created_at)`. Update `gecko_pulse` to:
- Take `project_id` (not just `session_id`) — walk to most recent paid session in that project
- Persist each panel run for delta computation in subsequent pulses
- Compare current closing lines vs prior run, surface deltas inline

Today's `session_id`-only path stays as a manual override.

**S5-API-03: dynamic markup on `/route`**
Sprint 4 shipped flat $0.02 per call because x402's pre-payment model can't easily charge a percentage of post-call cost. Sprint 5 ships streaming-charge support: charge a refundable max (e.g. $0.10) up front, settle to actual `usage_cost_usd × 1.10` on completion, refund the difference.

This requires extending the x402 middleware in `gecko-api` to support post-call settle-down. Not trivial — likely 1.5 days. If we don't get there, ship a tiered flat charge ($0.01 cheap-models / $0.05 mid / $0.20 premium) as v2 fallback.

### Track C — V3 dashboard MVP at app.geckovision.tech

Cross-repo work — lives in `gecko-mcpay-app`, not this repo. The brief should produce a new minimal flow:

- Login via frames.ag OTP (existing)
- "My Projects" — lists projects with the new Memory entries summary
- Per-project page — verdicts, scaffolds, advisor panels, pulses, contradictions
- Live cost ledger (from session_economics + V1 sources telemetry)
- Trigger `gecko_pulse` from the web UI

**Do NOT dispatch from this repo.** Switch to `gecko-mcpay-app` and dispatch a frontend-engineer there with this brief as the source of truth. The API surface is already there from Sprint 4.

### Track D — Tier ladder (deferred to Sprint 6)

Pro+/Studio/Studio Max ($2 / $5 / $19) needs business-manager + product-designer alignment on what each tier UNLOCKS. Sprint 5 lands the memory + dashboard MVP first; tier diversification happens once we have data on Pro tier conversion rates. Don't build pricing tiers without usage signal.

### Track E — Mainnet cutover (deferred — when user funds the wallet)

Already runbook-ready (`docs/runbooks/mainnet-cutover.md`). User generated the keypair Sprint 4 but explicitly chose to defer funding. Independent of all S5 features. ~30 min when ready.

## What's NOT in Sprint 5

- ❌ Tier ladder pricing surface (Sprint 6, after we have conversion data)
- ❌ `gecko_eval_project` live reconciliation (Sprint 6, depends on Memory landing first)
- ❌ Auto-refresh of model catalog from external benchmark APIs (Sprint 6, low priority)
- ❌ Cross-project flywheel public opt-in (Sprint 6+, governance work)
- ❌ V2 sources expansion (Wellfound, Crunchbase, Pitchbook) — Sprint 6+
- ❌ Mobile / extension surface — Sprint 7+

## Order of execution

| Day | Track A (Memory — software-engineer) | Track B (API hardening — software-engineer) |
|---|---|---|
| Mon | S5-MEM-01 migration + RPC | S5-API-01 /plan endpoint |
| Tue | S5-MEM-02 module + S5-MEM-03 MCP/CLI | S5-API-02 pulse_runs + project walk |
| Wed | S5-MEM-04 auto-journaling hooks | S5-API-03 dynamic /route markup (or tiered fallback) |
| Thu | S5-MEM-05 gecko_resume + S5-MEM-06 contradictions | (slack day for whatever broke) |
| Fri | Live integration test of full Memory loop | Demo + deploy bundle |

Tracks A and B are non-overlapping (Track A touches `memory/` + `workflows.py` hooks; Track B touches `gecko-api/main.py` + `pulse_runs` migration). Software-engineer × 2 in parallel.

Track C (dashboard) runs in `gecko-mcpay-app` — separate repo, separate dispatch window.

## Acceptance for Sprint 5

A user runs:

```bash
# Day 1
gecko_research "..."              # session A — auto-journaled
gecko_scaffold <A>                # auto-journaled
gecko_plan <A>                    # auto-journaled

# Day 7
gecko_resume <project_id>         # ✓ Memory recalls everything
gecko_pulse <project_id>          # ✓ Surfaces deltas vs Day 1's plan
gecko_research "<related idea>"   # ✓ Contradiction detector flags if similar

# Anytime
gecko_memory_search <project> "what did we decide about Carta"
# → returns the Day 1 verdict + scaffold paths + advisor closing lines
```

Plus: paid `/plan` endpoint deployed, dashboard MVP shipping at app.geckovision.tech, gecko_route's billing accuracy improved.

## Reference

- `docs/build-plan-sprint-4.md` — Sprint 4 plan (memory was deferred to here)
- `docs/openrouter-integration-notes.md` — OpenRouter response shape (informs S5-API-03)
- `docs/marketing/demand_proof.md` — X-signal validating the memory wedge ("OneContext + 566K bookmarks")
- `docs/external/how_to_build_a_task_based_model/` — model catalog source
