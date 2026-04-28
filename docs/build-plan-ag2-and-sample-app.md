# Build Plan — AG2 Pro Tier + Sample App Deliverable

## 1. Executive summary

- **Pro tier runs server-side in `gecko-api` with SSE streaming** to `gecko-mcp` so Claude Code shows the multi-agent debate live. One code path, one settlement, real-time wow moment.
- **AG2 GroupChat with 5 agents** (Analyst, Critic, Architect, Scoper, Judge), max 12 turns, hard wall-clock + token budget caps. New module `packages/gecko-core/src/gecko_core/orchestration/pro.py` plus `pro/agents.py` and `pro/budget.py`.
- **Sample app lives in a separate public repo** `gecko-sample-devbrief` linked from `gecko-claude/README.md` and embedded as a 60s GIF on the landing page. Not a submodule — submodules are friction for skill installers and we want it to evolve independently.
- **Validated idea for the sample app**: "Devbrief — a CLI that turns a GitHub repo into a recruiter-ready 1-pager." Dev-audience, narrow, V1 is genuinely shippable in one Builder pass, dogfoods the loop.
- **Pricing plumbing**: a separate route `POST /research/pro` already exists in stub form; just swap the 501 for the real handler and wire `$0.75` into x402 `RouteConfig`. No facilitator changes.

## 2. Decision log

### Q1: Where do AG2 agents run? **(a)+(c) hybrid — server-side execution with SSE streaming back to MCP. Pure-server fallback if SSE proves flaky.**

**Why:**
- Cost-of-compute exposure: keeping LLM keys + ClawRouter URL on Fargate avoids leaking them through MCP/CLI to user machines.
- Demo-ability: the wow moment IS watching agents argue in real time. (b) loses this. (a)-only also loses it unless we poll, and polling at 1Hz is uglier than SSE.
- Iteration: server-side means we ship Pro tier improvements without users updating their `gecko-mcp` PyPI install.
- Settlement timing: x402 settles at request time on `/research/pro`; the SSE stream is on a follow-up `GET /research/pro/{session_id}/events` (no payment, scoped by session ownership). Same pattern as existing async poll.
- IP/secrets: prompts and agent personas stay in `gecko-core` on Fargate, not shipped to clients.

**Rejecting (b):** developer-machine variance is real (Windows users, slow boxes, no GPU is fine but rate-limit handling on local OpenAI keys is not our problem to own). Also kills the upsell — if you pay $0.75 and your laptop runs hot for 90s, that's a worse experience than a streamed cloud response.

**Rejecting pure (a):** misses the headline.

### Q2: Where does the sample app live? **Separate public repo `gecko-sample-devbrief`, linked from `gecko-claude/README.md`.**

**Why:**
- `templates/` implies "scaffold from this," `examples/` implies "snippet." This is neither — it's a real product that happens to have been generated.
- Submodule = installer pulls extra megabytes; we run `install.sh` thousands of times, this matters.
- Separate repo gets its own GitHub stars, its own README, its own "Made with Gecko" badge. Marketing surface.
- Keeping it out of `gecko-claude` means we don't bloat the skill repo's git history every time Devbrief evolves.

**Rejecting `gecko-claude/templates/`:** couples skill repo lifecycle to sample app lifecycle. Bad.

**Rejecting `gecko-claude/examples/`:** same problem, plus "examples" implies multiple — we don't have the bandwidth for a portfolio.

### Q3: What idea? **"Devbrief: turn a GitHub repo into a recruiter-ready 1-pager."**

**Why:**
- Audience overlap: every Gecko user has a GitHub. They will run Devbrief on themselves the day they install it. Built-in distribution.
- Narrow V1: scrape repo README + commit graph + top 3 files → LLM → static HTML page. One afternoon.
- Believable validation: there's actual TAM here (devs job-hunting), real competitors (read.cv, Polywork), real differentiation (auto-generated, repo-grounded).
- Dogfooding: `gecko_research --idea "Devbrief..."` produces a real PRD; Builder sub-agent generates real Next.js. The artifact IS the proof.

## 3. Workstream A — AG2 Pro tier in `gecko-core`

### Files touched

**New:**
- `packages/gecko-core/src/gecko_core/orchestration/pro/__init__.py` — exports `generate(session_id, idea, rag_context, *, on_event) -> ProResult`
- `packages/gecko-core/src/gecko_core/orchestration/pro/agents.py` — `build_groupchat(llm_config) -> GroupChatManager`. Defines 5 ConversableAgents with system prompts.
- `packages/gecko-core/src/gecko_core/orchestration/pro/budget.py` — `BudgetGuard(max_turns=12, max_wall_seconds=120, max_tokens=80_000)`. Raises `BudgetExceeded` from a `select_speaker_auto` hook.
- `packages/gecko-core/src/gecko_core/orchestration/pro/events.py` — `AgentEvent` pydantic model: `{type: "turn_start"|"turn_end"|"final"|"error", agent: str, content: str, ts: float, tokens_in: int, tokens_out: int}`.
- `packages/gecko-core/src/gecko_core/orchestration/pro/transcript.py` — converts AG2 message list → `DebateTranscript` pydantic model embedded in `ResearchResult`.
- `packages/gecko-core/tests/orchestration/test_pro_budget.py` — unit: budget guard halts at max_turns; raises before exceeding token cap.
- `packages/gecko-core/tests/orchestration/test_pro_transcript.py` — unit: transcript shape stable across AG2 message variations.
- `packages/gecko-core/tests/orchestration/test_pro_smoke.py` — integration with stubbed LLM client returning canned responses for each agent. NO live OpenAI in CI.

**Modified:**
- `packages/gecko-core/src/gecko_core/workflows.py` — `research()` already takes `tier`. Add branch: if `tier == "pro"`, call `pro.generate(...)` with the same `rag_context` Basic uses; pass through `progress_callback` extended to accept `AgentEvent` (not just str).
- `packages/gecko-core/src/gecko_core/models.py` — add `DebateTranscript`, `AgentTurn`, extend `ResearchResult` with `transcript: DebateTranscript | None`.
- `packages/gecko-core/pyproject.toml` — add `ag2[openai]>=0.8` (the `autogen` import path is preserved per AG2 fork compat).
- `packages/gecko-api/src/gecko_api/main.py` — replace 501 stub on `POST /research/pro` with real handler. New route `GET /research/pro/{session_id}/events` returning `text/event-stream`.

### `tier=pro` flow (MCP → API → AG2 → result)

1. `gecko_research(idea, tier="pro")` in `gecko-mcp` calls `frames.ag /x402/fetch POST api.geckovision.tech/research/pro`.
2. x402 middleware on `/research/pro` requires `$0.75` USDC. On settle, returns `202 {session_id}`.
3. API spawns `asyncio.create_task(_run_pro(session_id, idea))`. The task writes `AgentEvent`s to a new Postgres table `pro_events` (append-only, indexed on `(session_id, seq)`).
4. `gecko-mcp` opens SSE on `GET /research/pro/{session_id}/events`. API streams events from `pro_events` (LISTEN/NOTIFY OR a 250ms tail poll — start with poll, no new infra).
5. MCP renders each event into Claude Code's stdout via the standard `progress` mechanism: `[Critic]: "Your TAM estimate is hand-wavy — cite a source"`.
6. Final event `type=final` carries the `ResearchResult` payload; MCP returns it to Claude.

### Cost tracking — schema

The existing `session_costs` migration tracks `(session_id, line_item, cost_usd)`. Per-agent attribution matters for Pro. **Decision: add a column, not a new table.**

- Migration `009_session_costs_agent.sql`: `ALTER TABLE session_costs ADD COLUMN agent TEXT NULL;`
- `line_item='llm'` rows for Pro tier set `agent='analyst'|'critic'|...|'judge'`. Basic tier leaves `agent NULL`. No backfill.

A separate table would force JOINs on every session economics query and double the migration surface. One nullable column is the right reversibility tradeoff.

### Debate transcript shape (in `ResearchResult.transcript`)

```
DebateTranscript:
  turns: list[AgentTurn]   # ordered
  total_tokens_in: int
  total_tokens_out: int
  budget_halt_reason: str | None  # "max_turns" | "max_wall" | "max_tokens" | None
AgentTurn:
  seq: int
  agent: Literal["analyst","critic","architect","scoper","judge"]
  content: str
  ts: float
  tokens_in: int
  tokens_out: int
```

## 4. Workstream B — Streaming the wow moment

SSE is the chosen path.

### Server (`gecko-api`)

- `GET /research/pro/{session_id}/events` returns `text/event-stream`. Auth: same Bearer (`frames.ag` apiToken) as the rest of the API; rejects if session owner ≠ token user.
- Event format: `event: turn\ndata: {json AgentEvent}\n\n`. Heartbeat `: ping\n\n` every 15s.
- Implementation: `StreamingResponse` over an async generator that polls `pro_events` every 250ms with `WHERE seq > $last_seq ORDER BY seq`. Closes when a `type=final` row is observed.
- No Redis. No queue. Postgres is the buffer.

### Client (`gecko-mcp`)

- New helper `gecko_mcp/x402_sse.py` — wraps `httpx.AsyncClient.stream("GET", ...)` over the frames.ag fetch path. Frames.ag is request/response, so we either:
  - **(preferred)** call the API directly with a short-lived signed URL the API issues alongside the 202, OR
  - have `gecko-mcp` open SSE through frames.ag once we confirm streaming is supported (it isn't reliably as of writing).
- Direct SSE from MCP → `api.geckovision.tech` is fine: this endpoint isn't payment-gated (the parent `/research/pro` already settled). Auth via session-scoped one-time token returned in the 202 body.
- Each event invokes the existing MCP `progress` callback so Claude Code sees streaming text. Format: `[{agent}] {first 200 chars of content}…`.

### Tests at boundary

- `packages/gecko-api/tests/test_pro_sse.py` — TestClient receives events from a seeded `pro_events` table; closes on `final`; rejects wrong owner with 403.
- `packages/gecko-mcp/tests/test_x402_sse.py` — mock httpx stream, assert progress callback fires per event, assert reconnect-once on transient drop.

If SSE proves flaky in the demo: `pro_events` is already persisted, so MCP falls back to polling `GET /sessions/{id}` for the final result and renders the transcript post-hoc. Same data, less wow.

## 5. Workstream C — Sample app generation

### How it gets generated

**Manual one-shot, scripted into a Makefile target in `gecko-claude`** — not a CLI command in `gecko`. Reasons: (1) we run this once per platform-major-version, not per-user; (2) a `gecko sample-app generate` command would need to be supported forever; (3) the Makefile target is a runbook, not a feature.

`gecko-claude/scripts/regenerate-sample.sh`:

```
#!/usr/bin/env bash
set -euo pipefail
cd /tmp && rm -rf devbrief-gen
mkdir devbrief-gen && cd devbrief-gen
# 1. Run the actual installed Gecko skill
claude code --headless << 'EOF'
Use gecko_research with tier=pro to validate:
"Devbrief — a CLI that takes a GitHub repo URL and produces a one-page
recruiter-ready HTML profile by analyzing README, commit history, and top files.
Open source, BYO OpenAI key, deploy to Vercel."
Then use the builder sub-agent to generate the V1 Next.js app from the
ResearchResult.
EOF
# 2. Snapshot to gecko-sample-devbrief repo
rsync -a --delete generated/ ../../gecko-sample-devbrief/
cd ../../gecko-sample-devbrief
git add -A && git commit -m "regen: from gecko v$(gecko --version)"
```

### What lives in `gecko-sample-devbrief`

- `README.md` with "Made with Gecko" badge linking to `app.geckovision.tech`, the original idea string, the session id, and a link to the public ResearchResult page (V3 surface — for now just dump the markdown).
- `app/`, `components/`, `package.json` — the actual Next.js V1.
- `.gecko/session.json` — the ResearchResult that produced this app, for provenance.
- Vercel deploy: `devbrief.geckovision.tech` (CNAME). One-click "Deploy to Vercel" button in README.

### Surfacing

- `gecko-claude/README.md`: top section "See it in action" → link + animated screenshot.
- `gecko-mcpay-app` landing page: hero CTA "Built with Gecko in 4 minutes" → link to live Devbrief.
- Demo video on the grant submission embeds the `regenerate-sample.sh` run.

### Keeping it fresh

Regenerate only on platform-major-version changes (Basic→Pro, V1→V2 schema, etc.). Stale-by-design. The README states the Gecko version it was generated with.

## 6. Workstream D — Pricing + payment plumbing

### Current state (verified)

- `packages/gecko-api/src/gecko_api/main.py` already has `/research` (basic, $0.10 / `2000` USDC base units) and `/research/pro` (501 stub).
- `PaymentMiddlewareASGI` is configured with per-route `RouteConfig` + `PaymentOption` keyed by path.

### Changes

- In `main.py`, register a second `RouteConfig` for `/research/pro` with `PaymentOption(amount=750_000, ...)` (USDC 6 decimals → $0.75 = 750_000; double-check the existing $0.10 = 100_000 base units convention before shipping — likely off-by-zero risk).
- `/.well-known/x402` advertises both routes automatically via the existing route catalog. No facilitator change — the facilitator (`x402.org/facilitator` for devnet) doesn't care about per-route price; it verifies signatures against the amount the resource server declared in the 402 challenge.
- `x402_mode` (`stub`/`live`/`frames`) flows unchanged: stub mode still 200s through the pro route for tests; `frames` mode means the client (`gecko-mcp`) is the one calling `frames.ag/x402/fetch` with the higher amount, frames.ag transparently signs.

### Tests

- `packages/gecko-api/tests/test_pricing.py` — assert 402 challenge on `/research/pro` advertises `750_000`; assert basic still advertises basic amount; assert stub mode bypasses both correctly.

### Frames.ag side

Confirm with `web3-engineer` that `/x402/fetch` doesn't cap per-tx amount at < $0.75 on the user's funded balance. $5 funded should cover $0.75 obviously, but the frames.ag client may have a confirmation UI threshold. If yes: surface in skill.md.

## 7. Demo script (60 seconds)

```
0:00  user types in Claude Code:
        "Use gecko_research with tier=pro to validate:
         a habit tracker that pays you in stablecoins for streaks"

0:03  Claude: "This will cost $0.75 from your frames.ag wallet. Confirm? [y/n]"
0:04  user: y
0:05  [x402 settle on Solana devnet — tx hash printed]

0:07  [Analyst]: "TAM analysis. Habit-tracking is $11B; stablecoin rewards
                  niche is unproven. Three comparables: Beeminder, StickK..."
0:18  [Critic]:  "Beeminder is fiat-only and dying. Need a sharper wedge —
                  who specifically wants crypto rewards for habits?"
0:28  [Architect]: "Stack: Next.js + Solana Pay + Supabase. Streak verification
                    via signed daily check-ins. Treasury contract on devnet."
0:38  [Scoper]:  "V1: 1 habit, 1 user, manual treasury top-up. 4 days work.
                  V2: multi-habit, social streaks. V3: DAO treasury."
0:48  [Judge]:   "Score 7.2/10. Wedge is fitness creators with paying audiences.
                  Recommend V1 ship to that segment first."

0:55  Claude renders the 3 docs + transcript. Session id printed.
0:58  user types: "now build V1"
0:59  Builder sub-agent kicks off. Demo cuts.
```

Length budget for real demo: 60s edited; the actual run is ~90s wall clock.

## 8. Risks and rollback

| Risk | Mitigation |
|---|---|
| AG2 GroupChat ping-pongs forever | `BudgetGuard` halts at `max_turns=12` AND `max_wall_seconds=120` AND `max_tokens=80_000`. Whichever first. Hard-coded, not user-configurable. |
| AG2 instability (it's young) | `tier=pro` path is fully isolated — Basic tier doesn't import `gecko_core.orchestration.pro`. If Pro breaks, Basic is unaffected. |
| Runaway LLM cost on Pro | Budget cap above. Plus: per-session economics row written incrementally, alarm in CloudWatch if a single session crosses $0.30 in COGS (margin floor). |
| SSE drops mid-demo | Reconnect-once in MCP client; on second drop, fall back to polling final result. Demo still works, just less live. |
| Frames.ag $0.75 UX friction | Confirm with web3-engineer this week; if their UI bounces, ship an inline `gecko-mcp` warning that Pro requires a frames.ag amount confirm step. |
| Sample app drift from current platform | Pin Gecko version in `gecko-sample-devbrief/.gecko/session.json`. Only regenerate on majors. |
| AG2 dep conflict with existing OpenAI client | AG2 0.8+ pins `openai>=1.0`; we already use `openai>=1.40`. Verify in `uv sync` once added; if it pins a lower upper-bound, vendor the agent shim instead of importing AG2 wholesale. |

**Rollback to Basic-only**: revert `gecko-api/main.py` route handler to 501; `gecko-mcp` already handles a 501 gracefully (existing path). One-commit rollback. Frontend has nothing to roll back yet.

## 9. Sequencing + estimate

| # | Ticket | Owner | Effort | Parallel? |
|---|---|---|---|---|
| A1 | Migration 009: `session_costs.agent` column | data-engineer | 1h | yes |
| A2 | `gecko-core/orchestration/pro/` skeleton + agent prompts | software-engineer | 4h | yes |
| A3 | `BudgetGuard` + tests | software-engineer | 2h | after A2 |
| A4 | Wire `tier=pro` branch in `workflows.research()` + transcript model | software-engineer | 2h | after A2 |
| A5 | `pro_events` table + migration 010 | data-engineer | 1h | yes |
| B1 | `/research/pro` real handler + spawning AG2 task | software-engineer | 3h | after A4 |
| B2 | `GET /research/pro/{id}/events` SSE endpoint + test | software-engineer | 3h | after A5 |
| B3 | `gecko-mcp` SSE consumer + progress rendering | software-engineer | 3h | after B2 |
| D1 | x402 RouteConfig for `$0.75` + pricing test | web3-engineer | 1h | yes |
| D2 | Frames.ag $0.75 confirm-flow check | web3-engineer | 1h | yes |
| C1 | `gecko-sample-devbrief` repo init | software-engineer | 1h | yes |
| C2 | Run `regenerate-sample.sh` once Pro tier is live | staff-engineer | 1h | after B3 |
| C3 | Deploy `devbrief.geckovision.tech` on Vercel | frontend-engineer (cross-repo stub) | 1h | after C2 |
| Demo | Record 60s video | product-designer | 2h | after C3 |

**Critical path:** A2 → A4 → B1 → B2 → B3 → C2 → C3 → Demo = ~17h serial.

**With parallelism (2 engineers + you):** **3 working days** to demo-ready. Day 1: A1/A2/A3/A5/D1 in parallel. Day 2: A4/B1/B2/B3. Day 3: C1/C2/C3 + demo recording.

**Buffer:** add 1 day for AG2 surprise (dep conflicts, async semantics, prompt iteration to make the debate feel real not stilted). **Total: 4 days.**

## Open coordination notes

- `frontend-engineer` (cross-repo stub): notify when `/research/pro` ships so `gecko-mcpay-app` can plan the V3 transcript viewer. Not blocking.
- `business-manager`: confirm $0.75 is the right Pro price post-grant; if changing, do it before D1 lands.
- `product-designer`: agent prompt voice/personas — Critic should be bitey, Judge should be calm. Worth a 30-min pass.

---

## TL;DR (5 bullets)

- **Pro tier = AG2 GroupChat (5 agents) on Fargate, streamed via SSE to MCP.** Server-side execution, live debate visible in Claude Code. Rejecting client-side AG2 (cost/secret leak) and pure-server (no wow).
- **Sample app = `gecko-sample-devbrief`, separate public repo, linked from `gecko-claude/README.md`.** Not a submodule, not a `templates/` dir.
- **Idea to validate = "Devbrief: GitHub repo → recruiter 1-pager".** Dev-audience, narrow V1, dogfoodable.
- **Schema: one nullable `agent` column on `session_costs` + new `pro_events` table.** No new infra. Postgres is the SSE buffer.
- **4 days to demo with 2 engineers + staff coordination.** Critical path runs through `pro/agents.py` → SSE → sample regen.

## References

- [AG2 GroupChat API](https://docs.ag2.ai/latest/docs/api-reference/autogen/GroupChat/)
- [AG2 async run_group_chat](https://docs.ag2.ai/latest/docs/api-reference/autogen/agentchat/a_run_group_chat/)
- [AG2 vs CrewAI / AutoGen rebrand explained](https://dev.to/agentsindex/ag2-vs-crewai-the-complete-comparison-including-the-autogen-rebrand-explained-248l)
- [x402 multiple payment options issue](https://github.com/coinbase/x402/issues/635)
- [x402 PyPI](https://pypi.org/project/x402/)
