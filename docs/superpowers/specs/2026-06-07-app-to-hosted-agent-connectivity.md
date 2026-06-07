# How the app connects to the deployed agent (no public ALB, session-scoped)

**Date:** 2026-06-07 · **Status:** design (answers "connect the deployed agent to the app, like local, API↔task only, no ALB").

## Confirmed: there is NO ALB on the agent
The `gecko-agent` Fargate task runs in a **private subnet with zero inbound** —
no ALB, no open security-group port (`infra/ecs-agent-stack.yml`). It only makes
*outbound* calls (OKX tape, OpenRouter, Mongo). That's the strongest posture:
nothing on the agent is reachable from the internet, period.

So "connect it to the app" cannot be the app hitting the task directly (it can't
reach it, by design). There are two valid internal patterns.

## Local vs hosted (the mapping)
| | Local (what we had) | Hosted (now) |
|---|---|---|
| App reads agent state | app → bot `localhost:8265/api/state` | app → **gecko-api** → state |
| The bridge | localhost HTTP | **Mongo `agent_state`** (Pattern A) or internal HTTP (Pattern B) |
| Inbound on the agent | localhost only | **none** (zero-inbound) |
| Access control | none (single user) | **session-scoped** (only the owning user) |

## Pattern A — Mongo bridge (RECOMMENDED for V1)
The deployed agent already writes its full state to **Mongo** (`GECKO_STATE_BACKEND=mongo`,
collection `agent_state`, keyed by `GECKO_AGENT_ID`). So:

```
app → gecko-api  GET /v1/agent/state   (Bearer session)
        → verify session → resolve user → user_agents binding (Supabase RLS)
        → read agent_state[that agent_id] from Mongo → return curated fields
```

- **Zero inbound on the task** stays true — the API and the task never talk
  directly; they meet at Mongo. Most decoupled, most secure.
- Already 90% wired (the agent writes; gecko-api needs the read endpoint + the
  binding lookup from the data-engineer's `user_agents` table).
- Great for **reads** ("watch your agent": PnL, positions, status, heartbeat).
- Commands (set strategy / stop) go via the control plane the orchestrator
  already owns (registry + `launch_agent.sh`), not a live socket.

## Pattern B — internal API↔task HTTP (add later, only if needed)
If we later need the API to call the *running* task in real time (e.g. push a
live config change to an in-flight process), expose the task's `:8265` to the
**gecko-api security group ONLY** (still no public ALB) and add **ECS Service
Connect / Cloud Map** so gecko-api can resolve the task's dynamic Fargate IP:
- `AgentSecurityGroup` ingress: `FromPort 8265 / SourceSecurityGroupId = <gecko-api SG>` (internal only).
- Service Connect namespace shared by both services → gecko-api calls `http://gecko-agent:8265/api/state`.
- Still zero *public* surface; the only caller is gecko-api in-VPC.
This is the "exactly like local" HTTP model, internal-only. We don't need it for
V1 reads — defer until bidirectional real-time control is required.

## Session-scoping ("only the user session can access this bot session")
Enforced in two layers (the data-engineer's schema PR provides the tables + RLS):
1. **gecko-api**: every `/v1/agent/*` route requires the onboarding Bearer
   session → resolves `user_id` → looks up `user_agents` for THAT user → only
   ever reads the `agent_id`s they own. A request for someone else's agent_id
   returns 404/403, never data.
2. **Supabase RLS**: the `user_agents` (+ `wallet_links`, `agent_grants`) rows
   are readable only by their owning user — defense in depth, so even a bug in
   the API layer can't leak another user's binding.
The Mongo read is gated by (1): you can only reach an `agent_state` doc whose
`agent_id` is in your own `user_agents` rows.

## Recommendation
- **V1: Pattern A (Mongo bridge)** + the session-scoped `GET /v1/agent/state`
  endpoint (next build, after the data-engineer's `user_agents` table lands).
- **Pattern B** is a clean follow-up when we need live API→task control; the
  CFN delta above is ready to drop in. No public ALB in either case.

## "Is it up?" — how to check (founder-run; the agent is unreachable from here)
The task is zero-inbound + this environment has no AWS creds, so verification is
operator-side:
```bash
aws ecs describe-services --cluster gecko-api --services gecko-agent --region us-east-2 --query 'services[0].{running:runningCount,desired:desiredCount,status:status}'
aws logs tail /ecs/gecko-agent --since 15m --region us-east-2   # poll loop + heartbeat
```
Up = `runningCount==1`, logs show `still_alive_at`/`poll_count` advancing, and a
fresh `agent_state` doc for `hosted-setupc-001` in Mongo. (Full runbook:
`docs/runbooks/2026-06-07-hosted-agent-deploy.md`.)
