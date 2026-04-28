# Path to Deploy — gecko-api

**Goal:** from "MCP→Frames flaky on localhost" → **gecko-api live at https://api.geckovision.tech**, ngrok retired, MCP works deterministically from any user's machine.

**Estimate:** ~5 hours of focused work, parallelizable in places.

---

## Stage 1 — Fix the MCP→Frames 502 (60-90 min)

The root cause is unclear but reproducible. Three observations:

| Caller | Result | Inference |
|---|---|---|
| `curl` directly to frames.ag | ✅ 200 in 4-6s | Network + payload + facilitator are healthy |
| `python -c` invoking `FramesAGWallet.x402_fetch` | ✅ 200 in 3-4s | Our SDK logic is correct |
| MCP subprocess invoking the same `FramesAGWallet.x402_fetch` | ❌ 502 every time | Something specific to the MCP runtime |

### 1.1 Capture the actual error body (15 min)

Our current `_paid_post_via_frames` catches `httpx.HTTPError` and re-raises a generic message. The 502 has a body — let's see it.

```python
# packages/gecko-mcp/src/gecko_mcp/api_client.py
except httpx.HTTPStatusError as exc:
    body = exc.response.text[:500]
    raise GeckoAPIError(
        f"frames.ag /x402/fetch failed [{exc.response.status_code}]: {body}"
    ) from exc
```

Restart Claude Code, fire one MCP call, read the new error. Likely candidates:
- "Connection reset" → middlebox issue
- "Cloudflare error 1015" → rate-limit
- HTML error page → frames' nginx cycling

### 1.2 Try httpx with curl-equivalent settings (20 min)

Add explicit settings to `FramesAGWallet`:

```python
self._http = httpx.AsyncClient(
    base_url=FRAMES_BASE,
    headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "gecko-mcp/0.1 (+https://geckovision.tech)",
        "Accept": "application/json",
    },
    http2=False,                    # explicit, in case default differs
    timeout=httpx.Timeout(120, connect=10),
    limits=httpx.Limits(            # no connection reuse — every call fresh
        max_connections=1,
        max_keepalive_connections=0,
    ),
    transport=httpx.AsyncHTTPTransport(retries=0),
)
```

Hypothesis: keepalive connection reuse is hitting a frames.ag-side connection pool issue. Disabling pool forces a fresh TCP+TLS handshake every call (slightly slower but matches curl behavior).

### 1.3 If still flaky: rate-limit ourselves and retry (15 min)

```python
# packages/gecko-mcp/src/gecko_mcp/wallet.py — FramesAGWallet
async def x402_fetch(self, ...):
    for attempt in range(3):
        try:
            return await self._do_fetch(...)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (502, 503, 504) and attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s
                continue
            raise
```

Three attempts with backoff is a fair balance between honest failure and resilience.

### 1.4 Validation (10 min)

```bash
# Repro 5x in a row, expect 5/5 success
for i in 1 2 3 4 5; do
  uv run python -c "
  import asyncio; from gecko_mcp.wallet import FramesAGWallet
  async def go():
      w = FramesAGWallet()
      r = await w.x402_fetch(url='https://<tunnel>/research', method='POST', body={'idea':'a hotel guide for Bonito MS in Brazil','tier':'basic','auto_approve':True}, max_payment_usd='0.50')
      print(i, r.get('paid'), r.get('errorCode'))
      await w.aclose()
  asyncio.run(go())
  "
done
```

Then restart Claude Code and run the MCP call once. **Acceptance:** 5/5 paid via repl + 1/1 paid via MCP.

---

## Stage 2 — Close the open V3 TODOs (45 min)

Two known gaps before deploy:

### 2.1 Real tx signature on `x402_tx_signature` (20 min)

Today the column reads `"pending-settle"` because we set it before the middleware settles. The real signature lives in the `PAYMENT-RESPONSE` header on the 202 response. We capture it client-side; we should also persist server-side.

Two paths:
- **Server-side via `add_after_settle_hook`** (cleaner) — register a hook on the x402 server that writes the real signature into `sessions.x402_tx_signature` after settlement.
- **Client-side stamp on poll completion** (already partially done in api_client.py:_poll_result) — push the captured signature into `result_json`.

Recommend the server-side hook. Cleaner; the API is the source of truth for the column.

### 2.2 Async pattern for `/research/pro` (20 min, optional)

Currently `/research/pro` returns 501 after payment. If we want the demo to charge $0.75 and return Pro results, we need a separate background task. Or punt to V2 — the basic flow demos the architecture.

**Recommend punt for v1 deploy.** Keep 501 with a clear "Phase 7" message.

### 2.3 Apply remaining migrations on prod Supabase (5 min)

Verify the production project has all of:
```
20260425000000_init.sql
20260425000100_pgvector_index.sql
20260425000200_rag_match.sql
20260425000300_doctor_rpcs.sql
20260426000000_x402_tx_signature.sql
20260427000000_session_costs.sql
20260427000100_tavily_extract_cache.sql
20260427000200_session_results.sql   ← latest
```

If you've been applying along the way, only the last two are likely missing.

---

## Stage 3 — Generate deploy artifacts (90 min)

These are the four files I held back until you signed off on the decision table in `docs/deploy-plan.md`.

### 3.1 Dockerfile (multi-stage Python + uv)

Builder stage: `python:3.12-slim`, install uv, `uv sync --frozen --no-dev`. Runner stage: copy the venv + workspace, run `uvicorn gecko_api.main:app --host 0.0.0.0 --port 8000`.

### 3.2 `docker-entrypoint.sh`

One-liner: `exec uv run uvicorn gecko_api.main:app --host 0.0.0.0 --port 8000`. Mirrors the sister repo's pattern.

### 3.3 `.dockerignore`

Exclude: `.venv`, `tests/`, `docs/`, `infra/`, `.env*`, `*.pyc`, `__pycache__`, `apps/cli/`, `apps/demo-agent/`. Keeps the image lean (gecko-api only ships what it needs).

### 3.4 `infra/ecs-stack.yml`

Adapted from `../gecko-social-fi-creators-api/infra/ecs-stack.yml`:
- Same VPC + ALB + Fargate cluster pattern
- Single service (`api`), single port (8000)
- Healthcheck path: `/healthz`
- Task definition: 0.5 vCPU / 1 GB
- Secrets block pulls from `/gecko-api/*` SSM parameters

### 3.5 `infra/deploy.sh`

Adapted from sister repo with three substitutions:
- `STACK_NAME=gecko-api-ecs`
- `SSM_PREFIX=/gecko-api`
- `ECR_REPOSITORY=gecko-api`

Same flags: `--region`, `--env`, `--cert`, `--skip-build`.

---

## Stage 4 — Deploy infrastructure (60-90 min)

### 4.1 ACM certificate (10 min, one-time)

```bash
aws acm request-certificate \
  --domain-name api.geckovision.tech \
  --validation-method DNS \
  --region us-east-2
```

Add the CNAME validation record to your Route 53 zone. Wait ~5 min for issuance. Save the cert ARN — `deploy.sh` needs it on first run.

### 4.2 SSM parameters (15 min)

Create each as `SecureString` in `us-east-2`:

```bash
declare -A PARAMS=(
  [SUPABASE_URL]="https://<project>.supabase.co"
  [SUPABASE_SERVICE_ROLE_KEY]="..."
  [TAVILY_API_KEY]="..."
  [OPENAI_API_KEY]="..."
  [X402_MODE]="live"
  [X402_NETWORK]="solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
  [X402_FACILITATOR_URL]="https://www.x402.org/facilitator"
  [GECKO_WALLET_ADDRESS]="<production treasury address>"
  [RESEARCH_BASIC_PRICE]="\$0.10"
  [RESEARCH_PRO_PRICE]="\$0.75"
  [GECKO_LLM_ENDPOINT]="https://api.openai.com/v1"
  [CHAT_MODEL]="gpt-4o-mini"
  # GECKO_LLM_API_KEY mirrors OPENAI_API_KEY — set explicitly
  [GECKO_LLM_API_KEY]="..."
)

for KEY in "${!PARAMS[@]}"; do
  aws ssm put-parameter --name "/gecko-api/$KEY" \
    --value "${PARAMS[$KEY]}" --type SecureString \
    --region us-east-2 --overwrite
done
```

**Treasury address decision:** generate a fresh Solana mainnet keypair (or use an existing one you own). Don't use the dev `8QUR...QxV` for production — that's your personal frames.ag wallet, mixing concerns.

### 4.3 Production treasury keypair (5 min)

```bash
# packages/gecko-mcp/src/gecko_mcp/wallet_self_custody.py already has the
# keypair generator. Use it once for the production treasury, save the
# secret in 1Password (NOT in the repo).
uv run python -c "
from solders.keypair import Keypair
kp = Keypair()
print('PUBLIC (set as GECKO_WALLET_ADDRESS):', kp.pubkey())
print('SECRET (save to 1Password):', list(bytes(kp)))
"
```

Send a tiny mainnet USDC transfer to it once so the ATA exists (avoids the `InvalidAccountData` failure mode we hit on devnet).

### 4.4 First deploy (30 min, mostly waiting)

```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
./infra/deploy.sh \
  --region us-east-2 \
  --cert arn:aws:acm:us-east-2:<account>:certificate/<id>
```

Watch CloudFormation in the console. Stack takes ~10-15 min for VPC + ALB + initial Fargate task.

### 4.5 DNS + smoke test (10 min)

```bash
# Get the ALB DNS name
aws cloudformation describe-stacks --stack-name gecko-api-ecs \
  --region us-east-2 --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' \
  --output text

# Add Route 53 A-alias: api.geckovision.tech → <ALB DNS>
# (Console or aws route53 change-resource-record-sets — your call)

# Smoke
curl https://api.geckovision.tech/healthz
curl https://api.geckovision.tech/.well-known/x402 | jq
GECKO_API_URL=https://api.geckovision.tech uv run gecko-mcp doctor
```

---

## Stage 5 — Cut over the MCP (15 min)

### 5.1 Update `~/.gecko/.env`

```bash
cat > ~/.gecko/.env <<'EOF'
GECKO_API_URL=https://api.geckovision.tech
GECKO_MAX_PAYMENT=0.50
EOF
```

### 5.2 Re-register the MCP

Drop the `--directory` registration (which pinned to local source) — switch to a uv tool install once we publish to PyPI, or keep the editable registration if we're still iterating.

For the demo: keep current registration. It just calls our deployed API instead of localhost.

### 5.3 Kill ngrok

```bash
pkill -f ngrok
```

ngrok is gone forever. The MCP talks to `https://api.geckovision.tech` directly.

### 5.4 End-to-end MCP test (in a fresh Claude Code session)

```
Use gecko_research to validate: a hotel guide for Bonito MS in Brazil
```

Expected: 60-90s, real Solana mainnet tx (or stay on devnet if `X402_MODE=stub` — your choice based on whether the demo benefits from real-money flow).

---

## Stage 6 — Demo-day polish (60 min, optional)

These polish the experience but aren't deploy-blocking:

- **Real `x402_tx_signature` on the result** — server-side after_settle_hook (Stage 2.1)
- **Frontend dashboard** — `gecko-mcpay-app` shows recent sessions with margin charts. (Separate repo.)
- **Recorded fallback video** — script the demo flow + record once. If the live demo network-fails, you have video proof.
- **Pricing knob** — devnet stays at $0.10, mainnet pricing decision (start at $0.50 to get real signal, ramp to $20 once cost data confirms margin).

---

## Time-box summary

| Stage | What | Time | Deploy-blocking? |
|---|---|---|---|
| 1 | Fix MCP→Frames 502 | 60-90 min | No (workaround: poll-from-curl) |
| 2.1 | Real tx signature | 20 min | No |
| 2.2 | Pro tier async | 20 min | No (501 is acceptable for v1) |
| 2.3 | Verify migrations | 5 min | **Yes** |
| 3 | Generate deploy files | 90 min | **Yes** |
| 4 | Deploy infrastructure | 60-90 min | **Yes** |
| 5 | Cut over MCP | 15 min | **Yes** |
| 6 | Polish | 60 min | No |

**Critical path: 2.3 → 3 → 4 → 5 ≈ 3 hours.** Stage 1 in parallel.

If we time-box for tomorrow and hit blockers, Stage 1 is the only one I'd cut — the demo can survive on the **proven sessions we already have** (4 paid runs tonight, full results in Supabase, economics queryable).

---

## What I need from you to start

1. **Confirm the decision table** in `docs/deploy-plan.md` (region us-east-2, single env, etc).
2. **AWS credentials** with permissions for ECS, ECR, CloudFormation, ACM, SSM, Route 53. Run `aws sts get-caller-identity` to confirm.
3. **Production treasury decision** — fresh keypair or reuse an existing one you own?
4. **Pricing decision** — $0.10 (devnet semantics) or $0.50 (mainnet starter) for `RESEARCH_BASIC_PRICE`?
5. **Mainnet vs devnet for v1 demo** — do you want real money flowing on the demo, or keep devnet for safety until after Shipathon?

Answer these and I generate Stage 3 files in one pass.
