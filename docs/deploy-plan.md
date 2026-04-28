# gecko-api — AWS ECS Fargate deploy plan

**Goal:** ship `gecko-api` to `https://api.geckovision.tech` on AWS ECS Fargate, behind an ALB, secrets in SSM Parameter Store, infrastructure as CloudFormation. Reuse the pattern proven in `../gecko-social-fi-creators-api/`.

**Status:** plan only — no files written yet. Review, then we generate.

---

## Decisions to confirm

Before scaffolding files, confirm these answers (most carry over from the sister repo):

| # | Var | Recommended value | Notes |
|---|---|---|---|
| 1 | `APP_NAME` | `gecko-api` | Used as prefix for every AWS resource. |
| 2 | `SERVICES` | `api:8000` | Single service. The Python repo doesn't have the multi-service worker pattern the skill scaffolds for; we ship one Fargate task. |
| 3 | `PUBLIC_SERVICE` | `api` | The ALB targets it. |
| 4 | `SSM_PREFIX` | `/gecko-api` | Mirrors `/gecko-campaign-api` in the sister repo. |
| 5 | `ECR_REPOSITORY` | `gecko-api` | Single image. |
| 6 | `REGION` | `us-east-2` | Matches sister repo so IAM roles, VPC peering (if any), and CloudWatch log groups stay in one place. |
| 7 | `DOMAIN` | `api.geckovision.tech` | Cert + Route 53 record done outside the stack. |
| 8 | `STACK_NAME` | `gecko-api-ecs` | CloudFormation stack name. |

If you want to deviate (e.g. `us-east-1`, dedicated VPC), call it out before A2.

---

## Differences from the sister repo

The deploy-to-ecs skill is Node-flavoured by default. Adapting to Python:

| Layer | Sister repo (Node) | gecko-api (Python) |
|---|---|---|
| Build tool | `npm ci` + `tsc` | `uv sync --frozen` |
| Base image | `node:20-alpine` | `python:3.12-slim` (slim, not alpine — `pgvector` / `tiktoken` wheels need glibc) |
| Multi-stage | `builder` (deps + tsc) → `runner` (dist + node_modules) | `builder` (uv sync → wheels) → `runner` (venv copy + uvicorn) |
| Entrypoint | `node dist/index.js` | `uvicorn gecko_api.main:app --host 0.0.0.0 --port 8000` |
| Healthcheck | `/health` | `/healthz` (already exists in `main.py`) |
| Port | 3001 | 8000 |
| Image size | ~120 MB | ~250 MB (Python wheels for openai, supabase, x402, pydantic — acceptable on Fargate) |

CloudFormation stack reuses 100% of the sister repo's resource set (VPC, subnets, NAT, ECS cluster, ALB, target group, listener, log group, task def, service). Only diff: container image, port, healthcheck path.

`deploy.sh` is a near-verbatim copy with three substitutions: `STACK_NAME`, `SSM_PREFIX`, `ECR_REPOSITORY`.

---

## Files we will generate

```
gecko-mcpay-api/
├── Dockerfile                    NEW — multi-stage Python+uv → uvicorn
├── docker-entrypoint.sh          NEW — `exec uvicorn gecko_api.main:app ...`
├── .dockerignore                 NEW — exclude .venv, tests, infra/, docs/
└── infra/
    ├── ecs-stack.yml             NEW — CloudFormation, adapted from sister
    └── deploy.sh                 NEW — adapted from sister
```

That's it. No application code change required for v1 deploy — the FastAPI app already reads everything from env via `Settings.from_env()`.

---

## SSM parameters required

Create these once via the AWS Console or CLI before the first deploy. All are `SecureString`.

```
/gecko-api/SUPABASE_URL                # https://<project>.supabase.co
/gecko-api/SUPABASE_SERVICE_ROLE_KEY   # service-role JWT
/gecko-api/TAVILY_API_KEY              # tavily search + extract
/gecko-api/OPENAI_API_KEY              # only if running v2 fallback
/gecko-api/X402_MODE                   # "live" (post-stub)
/gecko-api/X402_NETWORK                # "solana-devnet" or "solana-mainnet"
/gecko-api/X402_FACILITATOR_URL        # e.g. https://facilitator.x402.io
/gecko-api/GECKO_TREASURY_ADDRESS      # Solana address receiving USDC
/gecko-api/GECKO_TREASURY_ADDRESS_EVM  # optional — Base USDC route
/gecko-api/DEEPGRAM_API_KEY            # optional — YouTube fallback
```

The CloudFormation task definition wires these via the `secrets` block on the container, exactly as the sister repo does.

---

## Healthcheck contract

`gecko-api` already exposes:

```
GET /healthz  → 200 {"status": "ok", "payments": "<mode>"}
```

Use this for both the ALB target group health check and (optionally) the ECS task health check. ALB threshold: healthy after 2 successful checks at 30s interval. Same as the sister repo.

---

## Migrations

You said migrations are already applied to your Supabase project. Confirmed needed migrations on production:

- `20260425000000_init.sql` — sessions/sources/chunks
- `20260425000100_pgvector_index.sql` — IVFFlat
- `20260425000200_rag_match.sql` — `match_chunks` RPC
- `20260425000300_doctor_rpcs.sql` — `gecko_doctor_ping`, `gecko_doctor_manifest`
- `20260426000000_x402_tx_signature.sql` — `x402_tx_signature` column
- `20260427000000_session_costs.sql` — price + cost columns + `gecko_add_session_cost` RPC
- `20260427000100_tavily_extract_cache.sql` — Tavily Extract cache table

Sanity-check after pointing the deployed API at production Supabase: `gecko-mcp doctor` (with `GECKO_API_URL=https://api.geckovision.tech` exported). The doctor RPCs return the manifest of installed extensions/tables/functions.

---

## DNS + TLS

Out of scope for the stack; do this once, manually:

1. Request an ACM cert for `api.geckovision.tech` in `us-east-2`.
2. Pass its ARN to `deploy.sh` via `--cert <ARN>` on first run.
3. After the stack creates the ALB, point a Route 53 `A` record (alias) at the ALB DNS name.

The sister repo's `ecs-stack.yml` already accepts `CertificateArn` as a parameter — we keep that.

---

## Deploy day, step-by-step

```bash
# from gecko-mcpay-api repo root
aws configure                                  # if not already

# 1. create SSM parameters (once)
for KEY in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY TAVILY_API_KEY ...; do
  aws ssm put-parameter --name "/gecko-api/$KEY" --type SecureString \
    --value "<value>" --region us-east-2
done

# 2. first deploy — creates ECR, builds image, creates stack
./infra/deploy.sh --region us-east-2 --cert arn:aws:acm:us-east-2:...:certificate/...

# 3. point DNS at the ALB DNS name (Route 53 → A record alias)

# 4. verify
curl https://api.geckovision.tech/healthz
GECKO_API_URL=https://api.geckovision.tech uv run gecko-mcp doctor

# 5. subsequent deploys
./infra/deploy.sh --region us-east-2          # rebuild + push + update stack
./infra/deploy.sh --region us-east-2 --skip-build  # config-only update
```

---

## Cost estimate (steady-state)

- 1× Fargate task, 0.5 vCPU / 1 GB RAM: ~$15/mo
- 1× ALB: ~$18/mo
- NAT Gateway: ~$32/mo (the unavoidable AWS tax — used by Fargate to reach Supabase, OpenAI, Tavily)
- ECR storage: ~$0.10/mo per GB of images
- Data transfer: trivial at our request volume

**Total: ~$65–75/mo** before traffic. Same order as the sister repo.

If we ever want to drop the NAT, switch to Fargate in a public subnet with public IPs assigned to tasks. Not recommended for production but cuts ~$32/mo for dev environments.

---

## Open questions

1. **One env or two?** Sister repo deploys only `production`. Do we want a separate `staging` stack on the same account, or a separate AWS account entirely? My default: single `production` stack until we hit a customer that needs staging.

2. **Do we want `gunicorn + uvicorn workers` or `uvicorn` standalone?** For a single Fargate task at low traffic, plain `uvicorn` is fine. If we ever need >1 worker per task, switch to `gunicorn -k uvicorn.workers.UvicornWorker -w 2`. Defer.

3. **Logging.** CloudWatch is the default; sister repo uses `awslogs` driver. Carry over verbatim. If we want structured logs, swap stdlib logging for `structlog` in a v2 pass — not deploy-blocking.

4. **Autoscaling.** Sister repo runs DesiredCount=1. We do the same. Add target-tracking scaling on ALB request count later if traffic warrants.

---

## Next step

Confirm the table at the top + answer the open questions, then I generate `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`, `infra/ecs-stack.yml`, `infra/deploy.sh` in one pass. ETA after confirmation: ~15 minutes of writing, plus one local `docker build` smoke check before you run `deploy.sh`.
