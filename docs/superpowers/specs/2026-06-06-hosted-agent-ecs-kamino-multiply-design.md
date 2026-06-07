# Design — Hosted Agent on ECS + Kamino Multiply (two phases)

**Date:** 2026-06-06
**Status:** approved (founder, 2026-06-06)
**Owner lanes:** devops-engineer (Phase 1 infra), software-engineer + defi-engineer (Phase 2), web3-engineer (Phase 2E custody/broadcast)

## Goal

One user story in two phases: **"deploy my agent to the cloud, then put its profits to work."**

- **Phase 1** — the existing Setup-C trading bot runs 24/7 on AWS Fargate, **paper mode**, state in Mongo. The first proof of V1's hosted-only spine. No new bot logic; packaging + infra.
- **Phase 2** — load the **live Kamino catalog**, rank it by profile, the user **picks one** market, and the agent runs a **first Multiply test** — with a **minimum-hold lock** so a position is never liquidated for optimization reasons before it has held long enough to clear its round-trip costs (safety exits always override).

The two phases are independent to build; Phase 1 ships and is verified first.

---

## Phase 1 — Deploy the trading bot on ECS (fast path)

### Topology
One new `gecko-agent` Fargate **service inside the existing `gecko-api-ecs` stack** (reuse VPC, cluster, NAT, SSM, ECR — fastest, no new networking). One task, one container, one bot process. Runs in the **private subnet with zero inbound** — no ALB target, no open security-group port. Outbound only (OKX tape, OpenRouter, Mongo) via the existing NAT.

### Container
New **`Dockerfile.agent`** — the current `Dockerfile` deliberately excludes `contest_bot/`. The new image syncs the workspace venv with the bot's runtime deps (pymongo, httpx, OpenRouter/OpenAI client, ccxt, pydantic), copies `contest_bot/`, entrypoint = `python -u jto_breakout_gecko_gated_contest_bot.py`. **First plan step pins the exact dependency set** so the image isn't missing an import at runtime.

### Config (env)
- **Baked in entrypoint, non-overridable:** `PAPER_TRADE=true`, `X402_MODE=stub`, `GECKO_KAMINO_PAPER_SINK=0`. Plus the Setup-C knobs carried from `launch_setup_c.sh` (legacy breakout path, PYTH/WIF/RAY universe, `GECKO_MFI_HARD_GATE=1`).
- **State:** `GECKO_STATE_BACKEND=mongo` + a stable `GECKO_AGENT_ID` (e.g. `hosted-setupc-001`) → state in Mongo `agent_state`, **survives task restarts** (no orphaned positions). File fallback (`GECKO_STATE_DIR`) if Mongo is down.
- **Secrets via SSM** (extend `infra/push-ssm-params.sh`): `MONGODB_URI`, `OPENROUTER_API_KEY`.

### Safety / no-exploit posture
- **No funded wallet wired** — paper fills against real tape; no signing path exists, so no real-money exposure even in principle.
- **Zero inbound.** The bot's dashboard server binds **localhost-only** inside the container — used solely for the container's own health check (`curl localhost:8265/healthz`) and the future internal app read. Never published.
- ECS restarts the task on process exit; the health check catches a hung-but-alive process via the heartbeat (`still_alive_at`).

### Monitoring
- **Now:** CloudWatch Logs (`/ecs/gecko-agent`) for ops; Mongo `agent_state` doc for state.
- **User-facing (next slice, out of scope here):** the **app**, **session-scoped** via `gecko-api` → Mongo. A user only ever sees *their* agent, and only curated fields (PnL, positions, status) — never the raw technical dashboard. This rides V1 Phase A auth.

### Out of scope (Phase 1)
Control plane / orchestrator (single bot only), the app session-scoped UI, real money, multi-tenant.

### Verification
1. Image builds & runs locally (paper, Mongo).
2. Deploy the service → CloudWatch shows poll/heartbeat + decisions.
3. Mongo `agent_state` doc updates over time.
4. **Kill the task → it restarts and resumes from Mongo state with no double-open.** This last check is the whole point of the hosted model.

---

## Phase 2 — Kamino catalog → pick → Multiply (with min-hold lock)

### A. Catalog loader (`contest_bot/kamino/catalog.py`, new)
Fetch the **live** Kamino Multiply/borrow markets (extend the `ts-sidecar` and/or `apy_cache.py`; confirm the Kamino public API endpoint in planning). Normalize each market to a `LeverageStrategy`-compatible row: `{market, collateral_yield, borrow_rate, max_ltv, liq_ltv, correlated, yield_source}`. Cache + refresh on cadence. **Fallback to the curated templates** (`_lend`/`_lst`/`_jlp`) if the API is unreachable.

### B. Cost model + min-hold primitive (extend `contest_bot/kamino/multiply.py`)
- **Round-trip cost** `C` (fraction of equity) = entry swap bps + flash-loan fee + exit swap bps + gas.
- **Min-hold period** (the new number the founder asked for):
  `min_hold_period = time_to_target(principal, net_apy, C · principal)` — hold at least this long or the costs eat the yield. Reuses the existing `time_to_target`.
- `net_apy_after_cost(horizon)` — net APY amortizing `C` over a horizon, for ranking.

### C. Ranker + profile filter (`contest_bot/kamino/selector.py`, new)
- The V1 profiles become a **filter** on the catalog (allowed `yield_source`s, max leverage, min liquidation-headroom): **Conservative / Balanced / Aggressive**.
- **Rename `moderate` → `Balanced`** across `PROFILE_BASKETS` and consumers (Pattern A: single source of truth + drift/alias test).
- Rank survivors by net-APY-after-cost; attach each option's **min-hold period**; return the menu → **the user picks one**.

### D. Min-hold lock in the monitor (extend `contest_bot/kamino/monitor.py`)
- On open: record `entry_ts` + `min_hold_until = entry_ts + min_hold_period`.
- **Optimization exits suppressed until `min_hold_until`:** `ROTATE` (chase a better yield) and `DELEVERAGE` driven by non-dangerous spread compression.
- **Safety exits ALWAYS override the lock:** Pegana `DEPEG`/`CRITICAL`, liquidation-distance breach, deeply-inverted spread, market-temp risk-off downside breaching headroom.
- Verdict surfaces `locked until T` vs `safety override: <reason>`.
- This is the "don't liquidate before this time" guarantee, with the one correct exception (safety).

### E. First Multiply test — small mainnet, explicitly gated
Rides tasks A2/A3/A4 (#191/#192).
1. Build + **dry-run** the Multiply tx via `ts-sidecar` + OKX-TEE custody.
2. Run the **pre-mainnet checklist** (verification, custody, contract test, fee sim).
3. **Explicit founder "go" with the dollar amount** before any broadcast.
4. Broadcast small ($20–50). Monitor runs with the min-hold lock active.

Pattern B: everything falsifiable for $0 first (paper/sim on live rates); the real broadcast is the **final** verification, never the debug tool. Devnet is skipped (Kamino devnet USDC oracle-blocked).

### Sequencing (Phase 2)
A → B → C → D built and verified against **live rates in paper/sim**. Only **E** touches real money, behind the founder gate.

---

## Boundaries held (both phases)
- Phase 1: `PAPER_TRADE=true` + `X402_MODE=stub`, baked non-overridable.
- Phase 2: the real-money step (E) is gated on explicit founder go with an amount; devnet skipped (oracle-blocked).
- No prod deploy / no PR merge without explicit founder OK; branches + PRs only.
- `private/` stays gitignored (public repo); positioning/numbers never pushed.
- Never restart a bot with an open position; never plain `pkill -f` (use the `[x]` trick).

## Key existing assets (reuse, do not rebuild)
- `infra/deploy.sh` + `infra/ecs-stack.yml` + `infra/push-ssm-params.sh` — ECS deploy machinery.
- `contest_bot/jto_breakout_gecko_gated_contest_bot.py` — the monolith; env-driven, Mongo state backend (`MongoBotStateStore`, `GECKO_AGENT_ID`).
- `contest_bot/kamino/{multiply,monitor,vault_orchestrator,vault_gate,apy_cache,paper_ledger}.py` + `ts-sidecar` — Multiply economics + decision layer + real klend tx-build (PR #84).
