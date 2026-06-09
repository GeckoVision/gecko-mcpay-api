# Runbook — Hosted agent on ECS (paper)

How to deploy + operate the `gecko-agent` Fargate service (the Setup-C bot,
paper, Mongo-backed, zero-inbound). First deployed 2026-06-07 — up + healthy.

## Deploy
```bash
./infra/push-agent-ssm-params.sh            # /gecko-agent SSM params (MONGODB_URI, MONGODB_DB, OPENROUTER_API_KEY, LLM_ROUTER)
./infra/deploy-agent.sh                      # build+push image, deploy ecs-agent-stack (reuses gecko-api VPC/cluster)
```
- Region `us-east-2`, cluster `gecko-api`, stack `gecko-agent-ecs`, service `gecko-agent`.
- Zero inbound (private subnet, no ALB). Egress via the existing NAT.
- Safety env (`PAPER_TRADE=true`, `X402_MODE=stub`) is **baked in the entrypoint**, not overridable by SSM/task-def.

## Health
The bot's dashboard (`:8265`, localhost-only) has a **catch-all that returns 200
for any path**, so the container HEALTHCHECK (`curl localhost:8265/healthz`)
passes once the loop is up. Healthy ≈ steady RUNNING task, no flapping.

## Watch / diagnose
```bash
# service events (why pending/unhealthy)
aws ecs describe-services --cluster gecko-api --services gecko-agent --region us-east-2 --query 'services[0].events[:5]'
# why the last task stopped (the real reason)
aws ecs describe-tasks --cluster gecko-api --tasks $(aws ecs list-tasks --cluster gecko-api --desired-status STOPPED --region us-east-2 --query 'taskArns[0]' --output text) --region us-east-2 --query 'tasks[0].{reason:stoppedReason,containers:containers[].reason}'
# live logs
aws logs tail /ecs/gecko-agent --follow --region us-east-2
```

## Known first-deploy gotchas (checked 2026-06-07)
1. **`unable to pull secrets` / AccessDenied** → the `ecsTaskExecutionRole` SSM
   policy may be scoped to `/gecko-api/*`; grant `/gecko-agent/*` too, OR move the
   4 params under `/gecko-api/` and set the stack's `SSMPrefix=/gecko-api`.
2. **`Mongo unreachable` in logs (file-state fallback)** → add the NAT egress EIP
   to MongoDB Atlas' IP access-list. Bot keeps running on file-state, but the
   restart-resume proof needs Mongo.
3. **`exec format error`** → image built on ARM (Mac) for an x86 Fargate task;
   rebuild with `--platform linux/amd64` (n/a if building on the Linux box).

## Success signal
`aws logs tail /ecs/gecko-agent --follow` shows the poll loop, `still_alive_at` /
`poll_count` advancing, and the Setup-C voices (OpenRouter). Mongo `agent_state`
doc for `hosted-setupc-001` updates over time.

## The hosted-model proof (run once)
Force a new task and confirm it **resumes from Mongo state with no double-open**:
```bash
aws ecs update-service --cluster gecko-api --service gecko-agent --force-new-deployment --region us-east-2
# then tail logs: the new task should restore positions/poll_count from Mongo, not start clean.
```

## Stop / scale
```bash
aws ecs update-service --cluster gecko-api --service gecko-agent --desired-count 0 --region us-east-2   # stop
aws ecs update-service --cluster gecko-api --service gecko-agent --desired-count 1 --region us-east-2   # start
```

## App watches the agent — `GET /v1/agent/state` (Phase 1)
The app reads the agent's runtime state through **gecko-api**, not the zero-inbound
container. Path: app holds a user's HMAC session token → `GET /v1/agent/state` →
gecko-api verifies the token → looks up the caller's `user_agents` ownership row in
Supabase → reads the matching `agent_state` doc from Mongo → returns a **field-scoped**
view (`positions, realized_pnl_today, wins/losses_today, daily_trades, still_alive_at,
poll_count, updated_at`; never `spec`/`total_spent_usd`). A token for any other user
gets **404** (never leaks another user's agent). The agent stays zero-inbound.

**Prereqs (founder, once):**
1. **Apply the schema** if not yet applied: `infra/supabase/migrations/20260607010000_supabase_remodel.sql`
   (creates `app_users`, `user_agents` + the owner-only RLS).
2. **Seed the founder binding** so the app can read `hosted-setupc-001` before UI onboarding:
   ```bash
   FUID=$(python -c "import hashlib,sys;print('u_'+hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])" <FOUNDER_WALLET>)
   psql "$SUPABASE_DB_URL" -v founder_user_id="$FUID" -v agent_id="hosted-setupc-001" \
     -f infra/supabase/scripts/seed_founder_binding.sql
   ```
   The script creates the `app_users` owner row + the idempotent `user_agents` binding.
3. **Smoke:** `link → grant → GET /v1/agent/state` returns 200 with the scoped body (state may
   be empty until Mongo has a doc).

> **Phase-1 follow-ups (tracked, non-blocking for the single deployed agent):**
> - `bind_user_agent` (bind-on-grant) FK-fails silently for users with no `app_users` row —
>   nothing creates `app_users` yet. The seed covers the founder; the multi-user path needs an
>   `app_users` upsert in link/grant before bind-on-grant works end-to-end.
> - PostgREST `on_conflict="agent_id"` doesn't bind the partial unique index → a re-grant is a
>   silent no-op (the raw-SQL seed handles the predicate correctly; the writer needs select-then-upsert).
> Both want a **live contract test** (Pattern C) against the real Supabase tables.

## Boundaries
Paper + stub (baked). No real-money flip without explicit founder go. The bot
trades paper fills against live tape; no signing path exists in this image.
