# Active-Universe Paper Agent — Spec (2026-06-16)

**Goal:** an agent that produces **observable paper trades** (entry → position → exit → PnL), so we can watch the full E2E loop — and demonstrate the **Gecko-gated decision flow** live — *before* planning a first live deploy. PAPER only; this is for observation + the product demo, not alpha.

## Why this exists
The deployed majors agent (`/ecs/gecko-agent`) is **healthy but inert**: scan-heartbeat shows `snapshots=4 ... open=0` across ~8,000 scans. The majors-5m `price_breakout` class is documented -EV/rare ([[project_sprint_17_strategy_class_dead]]), so the entry simply never fires on BTC/ETH/SOL/DOGE. "Running" ≠ "observably operating." We need an agent on a universe + strategy that **actually fires**, so the loop is visible and the oracle gate is demonstrably doing its job.

> **Reframe:** for the *oracle* product, a gate that declines everything is the product working. But to validate the plumbing (entry→exit→PnL) and to *show* the gate in action, we need entries to happen. The point of this agent is **demonstration + E2E validation, not returns.**

## Design

### Universe + strategy (pick one that fires)
- **Universe:** the active memecoin set that traded before (PYTH / WIF / POPCAT / BOME class) — high volatility → frequent entry signals. (Majors stay as the disciplined-decline demo on the existing agent.)
- **Strategy:** the existing `price_breakout` is fine *on a volatile universe* — it'll fire. Keep `SL -0.8% / TP +1.0%` (or the Setup-C trail). Frequency > edge here; we want trades to observe.
- **Mode:** `PAPER_TRADE=true`, `X402_MODE=stub`. No wallet, no money. Existing circuit breakers on (flat-stall, MFI hard-gate).

### The Gecko-gated decision flow (the demo)
Every entry candidate passes the **two-tier gate** before a paper fill — this is the live demonstration of the latency strategy:
1. **Fast tier — `POST /safety`** (the new sub-second endpoint, PR #140): instant deterministic veto. `gate=block` → skip; `gate=caution` → size-down/log; `gate=ok/unknown` → proceed to tier 2. Sub-second, runs every candidate.
2. **Slow tier — `gecko_trade_research`** (cache-then-charge): the considered 7-voice verdict on cadence/triggers (not per-candidate). `verdict=act` + acceptable dissent → allow; `pass/defer` → decline (logged with reasons). Re-verdict triggers per the existing cadence rules.

This makes the agent the **proof artifact**: its decisions are visibly gated by Gecko's fast + considered layers. It also exercises the thin-agent/fat-API model — the agent just calls the API; improving the API upgrades the agent with no redeploy.

### Deployment shape
- Run as a **parallel process** alongside the majors agent — the monolith is directory-keyed via `GECKO_STATE_DIR` and supports multi-process (no collision); the memecoin agent ran on port **8267** before. Either a second ECS task (own `GECKO_STATE_DIR` + dashboard port) or local-first for the demo.
- Reuse the existing observability: scan-heartbeat (`[scan #N] snapshots/open`), decision-store, behavior-sink (Mongo `bot_behaviors`), dashboard.

### Observability / success criteria
- **≥ N observable paper trades** (entry→exit, full PnL) over 48h — target N≥10 so the loop is unambiguous.
- Each trade record shows: the **fast `/safety` gate** result, the **cached oracle verdict** (act/pass/defer + dissent), entry/exit/PnL, and the exit reason (TP/SL/trail/flat-stall).
- A 48h window where we can point at: "agent saw X candidates → `/safety` blocked Y → oracle declined Z → entered W → here are the W closed trades + PnL."

## Phasing
- **P1 — local observable run.** Point a local agent at the memecoin universe + the two-tier gate; confirm entries fire + the gate logs. (Fastest path to "see it operating.")
- **P2 — wire the fast `/safety` veto** into the entry path (currently the agent calls the oracle; add the instant `/safety` pre-check as tier 1). Demonstrates the speed tier end-to-end.
- **P3 — parallel ECS task** (own state-dir + port) so the active-universe agent runs in prod alongside the majors agent, both visible.
- **P4 — 48h observation + writeup** → the artifact that grounds the first-live-deploy plan.

## Boundaries
- **PAPER + stub only.** No live flip, no real money, no x402 live — explicit founder gate ([[project_x402_stub_then_live]]).
- Never restart a bot with an open position. Active-universe agent is additive — it does not touch the majors agent.
- This is a **demonstration/validation** agent. Do NOT present its PnL as alpha (the memecoin scalp class is a documented null — that's fine; the deliverable is the *observable gated loop*, not returns).

## Open questions for the founder
1. **Universe:** memecoin set (fires often, -EV but observable) vs a curated mid-vol set? Recommend memecoin for P1 (fastest to observable).
2. **Where:** local-first for the demo (cheapest) or straight to a parallel ECS task?
3. **Gate strictness:** for observation, loosen the oracle gate (so more entries fire + we see the loop), or keep prod-strict (fewer entries, more honest)? Recommend a slightly-loosened "observation" profile, clearly labeled.

*Pairs with the fast `/safety` endpoint (PR #140) and the context-strategy checklist (`docs/strategy/2026-06-14-context-strategy-checklist.md`).*
