# Hosted Agent on ECS + Kamino Multiply — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing Setup-C bot 24/7 on AWS Fargate (paper, Mongo-backed) and add a Kamino Multiply flow — live catalog → profile-ranked menu → user pick → minimum-hold lock → gated small-mainnet test.

**Architecture:** Phase 1 packages the env-driven monolith into a new container and runs it as a zero-inbound Fargate service in a small dedicated CloudFormation stack that reuses the existing VPC/cluster. Phase 2 adds pure-Python catalog/cost/selector/min-hold layers on top of the existing `kamino/` modules, all falsifiable in paper before the one gated real-money step.

**Tech Stack:** Python 3.12, uv workspace, Docker, AWS ECS Fargate + CloudFormation, SSM Parameter Store, MongoDB (state), Kamino API + `ts-sidecar`, pytest.

**Boundaries (non-negotiable, both phases):** `PAPER_TRADE=true` + `X402_MODE=stub` baked non-overridable in Phase 1; Phase 2's real-money step (Task 14) is gated on explicit founder go + amount; no AWS deploy / PR merge without explicit founder OK; `private/` stays gitignored; never restart a bot with an open position; targeted pytest only (never bare `uv run pytest`); never plain `pkill -f` (use the `[x]` trick).

---

## File Structure

**Phase 1 — container + infra (new files):**
- `Dockerfile.agent` — bot image (includes `contest_bot/`).
- `docker-entrypoint-agent.sh` — bakes paper/stub, execs the monolith.
- `infra/ecs-agent-stack.yml` — dedicated CFN stack: LogGroup + TaskDef + zero-inbound SG + Service. Imports VPC/cluster/subnets via parameters.
- `infra/deploy-agent.sh` — discovers networking from the running `gecko-api-ecs` stack, builds/pushes the agent image, deploys `ecs-agent-stack.yml`.
- `infra/push-ssm-params.sh` — MODIFY: add the agent's SSM params.
- `contest_bot/tests/test_agent_entrypoint.py` — entrypoint safety asserts.

**Phase 2 — Kamino (new + modified):**
- `contest_bot/kamino/multiply.py` — MODIFY: `round_trip_cost`, `min_hold_period`, `net_apy_after_cost`.
- `contest_bot/kamino/catalog.py` — NEW: live catalog loader + normalize + fallback.
- `contest_bot/kamino/selector.py` — NEW: profile filter + rank + min-hold menu.
- `contest_bot/kamino/monitor.py` — MODIFY: min-hold lock (optimization exits suppressed, safety overrides).
- `contest_bot/kamino/vault_orchestrator.py` — MODIFY: rename `moderate`→`Balanced` (Pattern A).
- `contest_bot/tests/test_min_hold.py`, `test_catalog.py`, `test_selector.py`, `test_min_hold_lock.py` — NEW.

---

## PHASE 1 — Deploy the bot on ECS

### Task 1: Agent container entrypoint (bake paper/stub)

**Files:**
- Create: `docker-entrypoint-agent.sh`
- Test: `contest_bot/tests/test_agent_entrypoint.py`

- [ ] **Step 1: Write the failing test** — assert the entrypoint hard-codes the safety env and never references a funded wallet / live flip.

```python
# contest_bot/tests/test_agent_entrypoint.py
import os, re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _entrypoint() -> str:
    with open(os.path.join(ROOT, "docker-entrypoint-agent.sh")) as f:
        return f.read()

def test_entrypoint_bakes_paper_and_stub():
    s = _entrypoint()
    assert re.search(r"export PAPER_TRADE=true", s)
    assert re.search(r"export X402_MODE=stub", s)
    assert "GECKO_STATE_BACKEND=mongo" in s

def test_entrypoint_never_flips_live():
    s = _entrypoint()
    assert "PAPER_TRADE=false" not in s
    assert "X402_MODE=live" not in s

def test_entrypoint_execs_monolith():
    assert "jto_breakout_gecko_gated_contest_bot.py" in _entrypoint()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest contest_bot/tests/test_agent_entrypoint.py -v`
Expected: FAIL (file not found / open error).

- [ ] **Step 3: Write the entrypoint**

```bash
# docker-entrypoint-agent.sh
#!/bin/sh
# Entrypoint for the hosted gecko-agent task. Paper-only, Mongo-backed.
# Safety env is BAKED here so it cannot be flipped by SSM/task-def env.
set -e

# --- Safety: non-overridable ---
export PAPER_TRADE=true
export X402_MODE=stub
export GECKO_KAMINO_PAPER_SINK=0

# --- State: Mongo so a task restart resumes (no orphaned positions) ---
export GECKO_STATE_BACKEND=mongo
export GECKO_AGENT_ID="${GECKO_AGENT_ID:-hosted-setupc-001}"
export GECKO_STATE_DIR="/tmp/gecko-state/${GECKO_AGENT_ID}"   # file fallback if Mongo down
mkdir -p "$GECKO_STATE_DIR"

# --- Setup-C strategy knobs (carried from launch_setup_c.sh) ---
export GECKO_ENTRY_REQUIRE_BREAKOUT=0
export GECKO_MFI_HARD_GATE=1
export MAX_DAILY_TRADES="${MAX_DAILY_TRADES:-20}"
export MAX_CONCURRENT="${MAX_CONCURRENT:-2}"
export DASHBOARD_PORT=8265          # localhost-only; used by container healthcheck

cd /app/contest_bot
exec python -u jto_breakout_gecko_gated_contest_bot.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest contest_bot/tests/test_agent_entrypoint.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Make executable + commit**

```bash
chmod +x docker-entrypoint-agent.sh
git add docker-entrypoint-agent.sh contest_bot/tests/test_agent_entrypoint.py
git commit -m "feat(s48-p1): agent entrypoint — bake paper/stub + Mongo state"
```

### Task 2: Dockerfile.agent (image that includes contest_bot)

**Files:**
- Create: `Dockerfile.agent`

- [ ] **Step 1: Write the Dockerfile** (mirrors the existing multi-stage `Dockerfile` but ships `contest_bot/`).

```dockerfile
# Dockerfile.agent — hosted Setup-C bot (paper). Reuses the workspace venv;
# adds contest_bot/. Deps (pymongo, ccxt, httpx, openai, pydantic) are already
# in uv.lock via the workspace.
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.30 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY packages/gecko-core/pyproject.toml ./packages/gecko-core/
COPY packages/gecko-api/pyproject.toml  ./packages/gecko-api/
COPY packages/gecko-mcp/pyproject.toml  ./packages/gecko-mcp/
COPY apps/cli/pyproject.toml            ./apps/cli/
COPY apps/demo-agent/pyproject.toml     ./apps/demo-agent/
COPY packages/gecko-core/src ./packages/gecko-core/src
COPY packages/gecko-api/src  ./packages/gecko-api/src
COPY packages/gecko-mcp/src  ./packages/gecko-mcp/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package gecko-core \
            --reinstall-package gecko-core

FROM python:3.12-slim AS runner
RUN useradd --create-home --shell /bin/bash gecko
WORKDIR /app
COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/packages/gecko-core/src ./packages/gecko-core/src
COPY --from=builder /app/pyproject.toml ./
COPY --from=builder /app/packages/gecko-core/pyproject.toml ./packages/gecko-core/
COPY contest_bot ./contest_bot
COPY docker-entrypoint-agent.sh ./
RUN chown -R gecko:gecko /app && chmod +x docker-entrypoint-agent.sh
USER gecko
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/contest_bot
# Healthcheck: bot's dashboard on localhost only.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8265/healthz',timeout=3).status==200 else 1)" || exit 1
ENTRYPOINT ["./docker-entrypoint-agent.sh"]
```

- [ ] **Step 2: Confirm `.dockerignore` doesn't exclude contest_bot**

Run: `grep -n contest_bot .dockerignore || echo "contest_bot NOT excluded (good)"`
Expected: prints "good". If it IS listed, add `!contest_bot` to un-ignore for this build (note in commit).

- [ ] **Step 3: Build the image locally**

Run: `docker build -f Dockerfile.agent -t gecko-agent:local .`
Expected: build succeeds; final image ~250–400 MB.

- [ ] **Step 4: Verify imports resolve inside the image** (catches a missing dep like `solders`/`onchainos` before deploy)

Run:
```bash
docker run --rm --entrypoint python gecko-agent:local -c \
  "import sys; sys.path.insert(0,'/app/contest_bot'); import jto_breakout_gecko_gated_contest_bot; print('IMPORT OK')"
```
Expected: `IMPORT OK`. If an import fails, add the missing package to the `gecko-core` deps (or a new `[project.optional-dependencies] agent` group) and re-`uv lock`, then rebuild. **Do not proceed until this prints IMPORT OK.**

- [ ] **Step 5: Commit**

```bash
git add Dockerfile.agent
git commit -m "feat(s48-p1): Dockerfile.agent — bot image w/ contest_bot, import-verified"
```

### Task 3: Local end-to-end paper run against Mongo

**Files:** none (verification task).

- [ ] **Step 1: Run the image locally in paper mode with a real Mongo URI** (use the dev `MONGODB_URI` from `.env`; never echo the value).

Run:
```bash
docker run --rm --name gecko-agent-smoke \
  -e MONGODB_URI -e MONGODB_DB -e OPENROUTER_API_KEY \
  -e GECKO_AGENT_ID=hosted-smoke-001 \
  --env-file <(grep -E '^(MONGODB_URI|MONGODB_DB|OPENROUTER_API_KEY)=' .env) \
  gecko-agent:local
```
Expected (in logs within ~60s): poll loop starts, `still_alive_at`/`poll_count` advancing, panel voices active (OpenRouter), no traceback. `Ctrl-C` to stop.

- [ ] **Step 2: Confirm state landed in Mongo** (the hosted-model proof)

Run: `uv run python -c "from contest_bot.kamino import *" 2>/dev/null; uv run python - <<'PY'
import os
from pymongo import MongoClient
c = MongoClient(os.environ["MONGODB_URI"])
db = c[os.environ.get("MONGODB_DB","gecko")]
doc = db["agent_state"].find_one({"agent_id":"hosted-smoke-001"})
print("FOUND" if doc else "MISSING", {k: doc.get(k) for k in ("poll_count","still_alive_at")} if doc else "")
PY`
Expected: `FOUND` with a non-zero `poll_count`.

- [ ] **Step 3: No commit** (verification only). Record the result in the PR description.

### Task 4: SSM params for the agent

**Files:**
- Modify: `infra/push-ssm-params.sh`

- [ ] **Step 1: Add the agent params block** under a new `/gecko-agent` prefix (mirror the existing put-parameter pattern in the file). Add `MONGODB_URI`, `MONGODB_DB`, `OPENROUTER_API_KEY`, `GECKO_LLM_ENDPOINT`, `GECKO_LLM_API_KEY`, `LLM_ROUTER` (value `openrouter`).

```bash
# --- gecko-agent params (Phase 1 hosted bot) ---
AGENT_PREFIX="/gecko-agent"
put () { aws ssm put-parameter --name "$AGENT_PREFIX/$1" --value "$2" --type "$3" --overwrite --region "$REGION" >/dev/null && echo "  set $1"; }
put MONGODB_URI       "${MONGODB_URI:?set MONGODB_URI in env}"       SecureString
put MONGODB_DB        "${MONGODB_DB:-gecko}"                          String
put OPENROUTER_API_KEY "${OPENROUTER_API_KEY:?set OPENROUTER_API_KEY}" SecureString
put LLM_ROUTER        "openrouter"                                    String
```

- [ ] **Step 2: Commit** (do NOT run it — founder runs against AWS).

```bash
git add infra/push-ssm-params.sh
git commit -m "feat(s48-p1): SSM params for hosted agent (/gecko-agent prefix)"
```

### Task 5: Dedicated CFN stack for the agent service

**Files:**
- Create: `infra/ecs-agent-stack.yml`

- [ ] **Step 1: Write the stack** — reuses the running cluster/VPC/subnets via parameters; zero-inbound SG; no ALB.

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: gecko-agent — zero-inbound Fargate service running the Setup-C paper bot.
Parameters:
  Image:        {Type: String, Default: PLACEHOLDER_SET_BY_DEPLOY_SCRIPT}
  ClusterArn:   {Type: String}
  VpcId:        {Type: String}
  PrivateSubnets: {Type: List<AWS::EC2::Subnet::Id>}
  SSMPrefix:    {Type: String, Default: /gecko-agent}
  AgentId:      {Type: String, Default: hosted-setupc-001}
Conditions: {}
Resources:
  AgentLogGroup:
    Type: AWS::Logs::LogGroup
    Properties: {LogGroupName: /ecs/gecko-agent, RetentionInDays: 30}
  AgentSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: gecko-agent - egress only, ZERO inbound
      VpcId: !Ref VpcId
      SecurityGroupEgress:
        - {IpProtocol: -1, CidrIp: 0.0.0.0/0}
  AgentTaskDef:
    Type: AWS::ECS::TaskDefinition
    DependsOn: AgentLogGroup
    Properties:
      Family: gecko-agent
      Cpu: '512'
      Memory: '1024'
      NetworkMode: awsvpc
      RequiresCompatibilities: [FARGATE]
      ExecutionRoleArn: !Sub arn:aws:iam::${AWS::AccountId}:role/ecsTaskExecutionRole
      TaskRoleArn:      !Sub arn:aws:iam::${AWS::AccountId}:role/EcsTaskRole
      ContainerDefinitions:
        - Name: agent
          Image: !Ref Image
          Essential: true
          Environment:
            - {Name: GECKO_AGENT_ID, Value: !Ref AgentId}
            - {Name: PYTHONUNBUFFERED, Value: '1'}
          Secrets:
            - {Name: MONGODB_URI,       ValueFrom: !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter${SSMPrefix}/MONGODB_URI'}
            - {Name: MONGODB_DB,        ValueFrom: !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter${SSMPrefix}/MONGODB_DB'}
            - {Name: OPENROUTER_API_KEY, ValueFrom: !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter${SSMPrefix}/OPENROUTER_API_KEY'}
            - {Name: LLM_ROUTER,        ValueFrom: !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter${SSMPrefix}/LLM_ROUTER'}
          LogConfiguration:
            LogDriver: awslogs
            Options:
              awslogs-group: /ecs/gecko-agent
              awslogs-region: !Ref AWS::Region
              awslogs-stream-prefix: agent
  AgentService:
    Type: AWS::ECS::Service
    Properties:
      ServiceName: gecko-agent
      Cluster: !Ref ClusterArn
      TaskDefinition: !Ref AgentTaskDef
      LaunchType: FARGATE
      DesiredCount: 1
      NetworkConfiguration:
        AwsvpcConfiguration:
          Subnets: !Ref PrivateSubnets
          SecurityGroups: [!Ref AgentSecurityGroup]
          AssignPublicIp: DISABLED
```

- [ ] **Step 2: Validate the template**

Run: `aws cloudformation validate-template --template-body file://infra/ecs-agent-stack.yml --region us-east-2`
Expected: returns parameter list, no error. (Founder runs if AWS creds are local; otherwise commit and let founder validate.)

- [ ] **Step 3: Commit**

```bash
git add infra/ecs-agent-stack.yml
git commit -m "feat(s48-p1): ecs-agent-stack — zero-inbound Fargate service"
```

### Task 6: deploy-agent.sh (founder-run)

**Files:**
- Create: `infra/deploy-agent.sh`

- [ ] **Step 1: Write the deploy script** — discovers networking from the running api stack, builds/pushes the agent image, deploys the agent stack.

```bash
#!/usr/bin/env bash
# infra/deploy-agent.sh — build/push the agent image + deploy ecs-agent-stack.
# Discovers VPC/cluster/private-subnets from the running gecko-api-ecs stack.
set -euo pipefail
REGION="${AWS_DEFAULT_REGION:-us-east-2}"
API_STACK="gecko-api-ecs"
AGENT_STACK="gecko-agent-ecs"
ECR_REPOSITORY="gecko-agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$REGION")
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPOSITORY}"
IMAGE_TAG="agent-$(git rev-parse --short HEAD)-$(date +%s)"; FULL_IMAGE="${ECR_URI}:${IMAGE_TAG}"

# Discover networking from the api stack's physical resources.
CLUSTER_ARN=$(aws ecs describe-clusters --clusters gecko-api --region "$REGION" --query 'clusters[0].clusterArn' --output text)
VPC_ID=$(aws cloudformation describe-stack-resources --stack-name "$API_STACK" --region "$REGION" \
  --query "StackResources[?ResourceType=='AWS::EC2::VPC'].PhysicalResourceId" --output text)
SUBNETS=$(aws cloudformation describe-stack-resources --stack-name "$API_STACK" --region "$REGION" \
  --query "StackResources[?LogicalResourceId=='PrivateSubnet1'||LogicalResourceId=='PrivateSubnet2'].PhysicalResourceId" --output text | tr '\t' ',')

echo "==> cluster=$CLUSTER_ARN vpc=$VPC_ID subnets=$SUBNETS image=$FULL_IMAGE"

aws ecr describe-repositories --repository-names "$ECR_REPOSITORY" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$ECR_REPOSITORY" --region "$REGION" >/dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_URI"
docker build -f "$REPO_ROOT/Dockerfile.agent" -t "$FULL_IMAGE" "$REPO_ROOT"
docker push "$FULL_IMAGE"

aws cloudformation deploy --stack-name "$AGENT_STACK" --region "$REGION" \
  --template-file "$REPO_ROOT/infra/ecs-agent-stack.yml" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides Image="$FULL_IMAGE" ClusterArn="$CLUSTER_ARN" VpcId="$VPC_ID" PrivateSubnets="$SUBNETS"
echo "==> deployed. logs: aws logs tail /ecs/gecko-agent --follow --region $REGION"
```

- [ ] **Step 2: chmod + commit** (do NOT run — founder-gated AWS deploy).

```bash
chmod +x infra/deploy-agent.sh
git add infra/deploy-agent.sh
git commit -m "feat(s48-p1): deploy-agent.sh — build/push + deploy agent stack (founder-run)"
```

### Task 7: Phase-1 verification checklist (founder-run, after deploy)
- [ ] `aws logs tail /ecs/gecko-agent --follow` shows the poll loop + heartbeat advancing.
- [ ] Mongo `agent_state` doc for `hosted-setupc-001` updates over ~10 min.
- [ ] Force a task restart (`aws ecs update-service --force-new-deployment`); confirm it resumes from Mongo with **no double-open** position.
- [ ] Record results in the PR; **do not merge without founder OK**.

---

## PHASE 2 — Kamino catalog → pick → Multiply

### Task 8: Round-trip cost + min-hold period (the new primitive)

**Files:**
- Modify: `contest_bot/kamino/multiply.py` (append functions)
- Test: `contest_bot/tests/test_min_hold.py`

- [ ] **Step 1: Write the failing test**

```python
# contest_bot/tests/test_min_hold.py
import math
from kamino.multiply import LeverageStrategy, round_trip_cost, min_hold_period, net_apy_after_cost

def _lst(lev=4.0):
    return LeverageStrategy("JitoSOL/SOL", 0.07, 0.06, lev, 0.90, 0.93, True, "lst_staking")

def test_round_trip_cost_sums_legs():
    # 10 bps entry swap + 5 bps flash + 10 bps exit swap + 2 bps gas = 0.0027
    c = round_trip_cost(entry_swap_bps=10, flash_fee_bps=5, exit_swap_bps=10, gas_bps=2)
    assert abs(c - 0.0027) < 1e-9

def test_min_hold_period_positive_yield():
    s = _lst(4.0)                 # net_apy = 0.07 + 0.01*3 = 0.10
    cost = 0.0027
    t = min_hold_period(s, principal=1000.0, cost=cost)
    # years to earn cost*principal at 10% APY = ln(1+0.0027)/ln(1.10)
    assert t is not None and abs(t - (math.log(1+cost)/math.log(1.10))) < 1e-6

def test_min_hold_period_none_when_no_yield():
    s = LeverageStrategy("bleeder", 0.04, 0.06, 4.0, 0.90, 0.93, True, "lst_staking")  # net<0
    assert min_hold_period(s, 1000.0, 0.0027) is None

def test_net_apy_after_cost_amortizes():
    s = _lst(4.0)                 # net 0.10
    # over 0.5y, subtract cost annualized: 0.10 - 0.0027/0.5 = 0.0946
    assert abs(net_apy_after_cost(s, cost=0.0027, horizon_years=0.5) - (0.10 - 0.0027/0.5)) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest contest_bot/tests/test_min_hold.py -v`
Expected: FAIL (ImportError: round_trip_cost).

- [ ] **Step 3: Append the implementation to `contest_bot/kamino/multiply.py`**

```python
def round_trip_cost(
    entry_swap_bps: float, flash_fee_bps: float, exit_swap_bps: float, gas_bps: float = 0.0
) -> float:
    """Total open+close cost as a FRACTION of equity. bps → fraction (/10_000)."""
    return (entry_swap_bps + flash_fee_bps + exit_swap_bps + gas_bps) / 10_000.0


def min_hold_period(strat: LeverageStrategy, principal: float, cost: float) -> float | None:
    """Years to hold before accrued net yield clears the round-trip `cost`
    (fraction of equity). The 'don't liquidate before this' number. None if the
    position never earns (net_apy <= 0). Reuses time_to_target."""
    return time_to_target(principal, strat.net_apy, cost * principal)


def net_apy_after_cost(strat: LeverageStrategy, cost: float, horizon_years: float) -> float:
    """net_apy with the round-trip cost amortized over `horizon_years` — the
    ranking metric. A high-APY position with a long break-even ranks below a
    modest one held past break-even."""
    if horizon_years <= 0:
        return strat.net_apy
    return strat.net_apy - (cost / horizon_years)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest contest_bot/tests/test_min_hold.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add contest_bot/kamino/multiply.py contest_bot/tests/test_min_hold.py
git commit -m "feat(s48-p2): round-trip cost + min-hold-period primitive"
```

### Task 9: Rename `moderate` → `Balanced` (Pattern A)

**Files:**
- Modify: `contest_bot/kamino/vault_orchestrator.py:PROFILE_BASKETS`
- Test: `contest_bot/tests/test_min_hold.py` (append an alias test)

- [ ] **Step 1: Find every consumer of the string `"moderate"`**

Run: `grep -rn '"moderate"\|'\''moderate'\''' contest_bot/ packages/ apps/ --include=*.py | grep -vi test`
Expected: a small list (PROFILE_BASKETS + any reader). Note each.

- [ ] **Step 2: Write the failing alias test**

```python
# append to contest_bot/tests/test_min_hold.py
from kamino.vault_orchestrator import PROFILE_BASKETS, normalize_profile

def test_balanced_is_canonical_moderate_is_alias():
    assert "Balanced" in PROFILE_BASKETS
    assert "moderate" not in PROFILE_BASKETS          # old key gone from the dict
    assert normalize_profile("moderate") == "Balanced"  # back-compat alias
    assert normalize_profile("Balanced") == "Balanced"
    assert normalize_profile("conservative") == "conservative"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest contest_bot/tests/test_min_hold.py -k balanced -v`
Expected: FAIL (KeyError / no normalize_profile).

- [ ] **Step 4: Rename the key + add the alias** in `vault_orchestrator.py`

```python
PROFILE_BASKETS: dict[str, list[tuple[LeverageStrategy, float]]] = {
    "conservative": [(_lend(), 1.0)],
    "Balanced": [(_lst(4.0), 0.6), (_lend(), 0.4)],     # was "moderate"
    "aggressive": [(_lst(8.0), 0.5), (_jlp(), 0.3), (_lend(), 0.2)],
}

_PROFILE_ALIASES = {"moderate": "Balanced"}

def normalize_profile(name: str) -> str:
    """Map any incoming profile label to its canonical key (back-compat for 'moderate')."""
    return _PROFILE_ALIASES.get(name, name)
```
Then update any consumer found in Step 1 to call `normalize_profile(...)` before indexing `PROFILE_BASKETS`.

- [ ] **Step 5: Run test + the existing vault tests**

Run: `uv run pytest contest_bot/tests/test_min_hold.py -k balanced -v && uv run pytest contest_bot/tests/ -k "vault or orchestrator" -v`
Expected: PASS; no regressions.

- [ ] **Step 6: Commit**

```bash
git add contest_bot/kamino/vault_orchestrator.py contest_bot/tests/test_min_hold.py
git commit -m "feat(s48-p2): rename moderate->Balanced profile + back-compat alias (Pattern A)"
```

### Task 10: Catalog loader — spike then implement

**Files:**
- Create: `contest_bot/kamino/catalog.py`
- Test: `contest_bot/tests/test_catalog.py`

- [ ] **Step 1: Spike the Kamino API** (confirm the live endpoint + JSON shape before coding the parser).

Run: `uv run python - <<'PY'
import httpx
for url in ("https://api.kamino.finance/v2/markets", "https://api.kamino.finance/markets"):
    try:
        r = httpx.get(url, timeout=10)
        print(url, r.status_code, str(r.json())[:300])
    except Exception as e:
        print(url, "ERR", e)
PY`
Expected: at least one 200 with a market list. **Record the working URL + the fields that map to `{collateral_yield, borrow_rate, max_ltv, liq_ltv}`.** If neither resolves, use the Kamino MCP (`mcp.kamino`/docs) or fall back to templates-only for this task and file a follow-up.

- [ ] **Step 2: Write the failing test** (parser + fallback are pure; the fetch is injected).

```python
# contest_bot/tests/test_catalog.py
from kamino.catalog import normalize_market, load_catalog, CURATED_FALLBACK
from kamino.multiply import LeverageStrategy

RAW = {  # shape recorded in Step 1 (adjust keys to the real ones)
    "name": "JitoSOL/SOL", "supplyApy": 0.07, "borrowApy": 0.06,
    "maxLtv": 0.90, "liquidationLtv": 0.93,
}

def test_normalize_market_to_leverage_strategy():
    s = normalize_market(RAW, leverage=4.0, correlated=True, yield_source="lst_staking")
    assert isinstance(s, LeverageStrategy)
    assert abs(s.collateral_yield - 0.07) < 1e-9 and abs(s.borrow_rate - 0.06) < 1e-9
    assert abs(s.max_ltv - 0.90) < 1e-9

def test_load_catalog_falls_back_when_fetch_fails():
    def boom():
        raise RuntimeError("api down")
    cat = load_catalog(fetch=boom)
    assert cat == CURATED_FALLBACK and len(cat) >= 3
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest contest_bot/tests/test_catalog.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 4: Implement `catalog.py`** (use the URL/keys recorded in Step 1).

```python
"""Live Kamino catalog → list[LeverageStrategy]. Fallback to curated templates."""
from __future__ import annotations
import logging
from typing import Callable
import httpx
from kamino.multiply import LeverageStrategy

logger = logging.getLogger("kamino.catalog")
_KAMINO_URL = "https://api.kamino.finance/v2/markets"   # confirmed in Task 10 Step 1

# Curated, vetted templates (mirror vault_orchestrator); LTV/source hand-set.
CURATED_FALLBACK: list[LeverageStrategy] = [
    LeverageStrategy("USDC lend", 0.058, 0.0, 1.0, 0.75, 0.80, True, "stable_spread"),
    LeverageStrategy("JitoSOL/SOL 4x", 0.07, 0.06, 4.0, 0.90, 0.93, True, "lst_staking"),
    LeverageStrategy("JLP/USDC 3.2x", 0.12, 0.06, 3.2, 0.69, 0.73, False, "jlp_fees"),
]

def normalize_market(raw: dict, *, leverage: float, correlated: bool, yield_source: str) -> LeverageStrategy:
    """Map one Kamino market JSON row → LeverageStrategy. Key names per Task 10 spike."""
    return LeverageStrategy(
        name=str(raw["name"]),
        collateral_yield=float(raw["supplyApy"]),
        borrow_rate=float(raw["borrowApy"]),
        leverage=leverage,
        max_ltv=float(raw["maxLtv"]),
        liquidation_ltv=float(raw["liquidationLtv"]),
        correlated=correlated,
        yield_source=yield_source,
    )

def _fetch_live() -> list[dict]:
    r = httpx.get(_KAMINO_URL, timeout=10)
    r.raise_for_status()
    return r.json()

def load_catalog(fetch: Callable[[], list[dict]] = _fetch_live) -> list[LeverageStrategy]:
    """Live catalog if reachable, else CURATED_FALLBACK. Never raises into the caller."""
    try:
        rows = fetch()
    except Exception as e:  # noqa: BLE001 — fail to the vetted set
        logger.warning("kamino catalog fetch failed (%s) — using curated fallback", e)
        return CURATED_FALLBACK
    out: list[LeverageStrategy] = []
    for raw in rows:
        try:
            # leverage/correlated/yield_source inferred per market-kind; minimal v0 mapping:
            out.append(normalize_market(raw, leverage=1.0, correlated=True, yield_source="stable_spread"))
        except (KeyError, ValueError, TypeError):
            continue
    return out or CURATED_FALLBACK
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest contest_bot/tests/test_catalog.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add contest_bot/kamino/catalog.py contest_bot/tests/test_catalog.py
git commit -m "feat(s48-p2): Kamino catalog loader (live + curated fallback)"
```

### Task 11: Selector — profile filter + rank + min-hold menu

**Files:**
- Create: `contest_bot/kamino/selector.py`
- Test: `contest_bot/tests/test_selector.py`

- [ ] **Step 1: Write the failing test**

```python
# contest_bot/tests/test_selector.py
from kamino.multiply import LeverageStrategy
from kamino.selector import PROFILE_RULES, rank_catalog

def _cat():
    return [
        LeverageStrategy("USDC lend", 0.058, 0.0, 1.0, 0.75, 0.80, True, "stable_spread"),
        LeverageStrategy("JitoSOL 4x", 0.07, 0.06, 4.0, 0.90, 0.93, True, "lst_staking"),
        LeverageStrategy("JLP 3.2x", 0.12, 0.06, 3.2, 0.69, 0.73, False, "jlp_fees"),
    ]

def test_conservative_filters_out_leverage_and_uncorrelated():
    menu = rank_catalog(_cat(), profile="conservative", principal=1000.0, cost=0.0027, horizon_years=0.5)
    assert [m["name"] for m in menu] == ["USDC lend"]   # only no-liquidation-surface

def test_aggressive_includes_all_ranked_by_net_after_cost():
    menu = rank_catalog(_cat(), profile="aggressive", principal=1000.0, cost=0.0027, horizon_years=0.5)
    assert len(menu) == 3
    # ranked descending by net_apy_after_cost; each row carries min_hold_days
    nets = [m["net_apy_after_cost"] for m in menu]
    assert nets == sorted(nets, reverse=True)
    assert all("min_hold_days" in m for m in menu)

def test_balanced_accepts_alias_moderate():
    a = rank_catalog(_cat(), profile="moderate", principal=1000.0, cost=0.0027, horizon_years=0.5)
    b = rank_catalog(_cat(), profile="Balanced", principal=1000.0, cost=0.0027, horizon_years=0.5)
    assert [m["name"] for m in a] == [m["name"] for m in b]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest contest_bot/tests/test_selector.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `selector.py`**

```python
"""Profile-filtered, cost-aware ranking of the Kamino catalog → a pick menu."""
from __future__ import annotations
from kamino.multiply import LeverageStrategy, min_hold_period, net_apy_after_cost
from kamino.vault_orchestrator import normalize_profile

# profile -> (allowed yield_sources, max_leverage, min_ltv_headroom)
PROFILE_RULES: dict[str, dict] = {
    "conservative": {"sources": {"stable_spread"}, "max_leverage": 1.0, "min_headroom": 0.0},
    "Balanced":     {"sources": {"stable_spread", "lst_staking"}, "max_leverage": 5.0, "min_headroom": 0.05},
    "aggressive":   {"sources": {"stable_spread", "lst_staking", "jlp_fees", "rwa_credit", "equity"},
                     "max_leverage": 10.0, "min_headroom": 0.0},
}

def _passes(s: LeverageStrategy, rule: dict) -> bool:
    return (
        s.yield_source in rule["sources"]
        and s.leverage <= rule["max_leverage"] + 1e-9
        and s.ltv_headroom >= rule["min_headroom"] - 1e-9
        and s.net_apy > 0
    )

def rank_catalog(catalog: list[LeverageStrategy], *, profile: str, principal: float,
                 cost: float, horizon_years: float) -> list[dict]:
    """Filter by profile, rank by net-APY-after-cost, attach min-hold. Returns the menu."""
    rule = PROFILE_RULES[normalize_profile(profile)]
    rows: list[dict] = []
    for s in catalog:
        if not _passes(s, rule):
            continue
        t = min_hold_period(s, principal, cost)
        rows.append({
            "name": s.name,
            "net_apy": round(s.net_apy, 4),
            "net_apy_after_cost": round(net_apy_after_cost(s, cost, horizon_years), 4),
            "leverage": s.leverage,
            "liquidation_drop_pct": round(s.liquidation_drop_pct, 4),
            "min_hold_days": round(t * 365.0, 1) if t is not None else None,
            "_strategy": s,
        })
    rows.sort(key=lambda r: r["net_apy_after_cost"], reverse=True)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest contest_bot/tests/test_selector.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add contest_bot/kamino/selector.py contest_bot/tests/test_selector.py
git commit -m "feat(s48-p2): selector — profile filter + cost-aware rank + min-hold menu"
```

### Task 12: Min-hold lock in the monitor (the guarantee)

**Files:**
- Modify: `contest_bot/kamino/monitor.py`
- Test: `contest_bot/tests/test_min_hold_lock.py`

- [ ] **Step 1: Read the current `evaluate` signature + verdict constants** so the lock wraps the existing decision without changing its safety behavior.

Run: `sed -n '1,60p' contest_bot/kamino/monitor.py && grep -n "def evaluate\|EXIT\|DELEVERAGE\|ROTATE\|HOLD" contest_bot/kamino/monitor.py`
Expected: note `evaluate(...)`'s params + the verdict string constants.

- [ ] **Step 2: Write the failing test** — optimization exits suppressed pre-breakeven; safety exits always fire.

```python
# contest_bot/tests/test_min_hold_lock.py
from kamino.monitor import apply_min_hold_lock, EXIT, DELEVERAGE, ROTATE, HOLD

def test_optimization_exit_suppressed_before_min_hold():
    # ROTATE for better yield must become HOLD while locked
    out = apply_min_hold_lock(ROTATE, reason="better_yield_elsewhere", locked=True, safety=False)
    assert out["action"] == HOLD and out["locked"] is True

def test_deleverage_for_yield_suppressed_before_min_hold():
    out = apply_min_hold_lock(DELEVERAGE, reason="spread_compression", locked=True, safety=False)
    assert out["action"] == HOLD

def test_safety_exit_overrides_lock():
    out = apply_min_hold_lock(EXIT, reason="pegana_depeg", locked=True, safety=True)
    assert out["action"] == EXIT and out["override"] == "pegana_depeg"

def test_no_suppression_after_min_hold():
    out = apply_min_hold_lock(ROTATE, reason="better_yield_elsewhere", locked=False, safety=False)
    assert out["action"] == ROTATE
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest contest_bot/tests/test_min_hold_lock.py -v`
Expected: FAIL (ImportError: apply_min_hold_lock).

- [ ] **Step 4: Add `apply_min_hold_lock` to `monitor.py`** (a pure wrapper over the verdict; safety classification stays with the caller).

```python
# constants EXIT/DELEVERAGE/ROTATE/HOLD already exist in monitor.py
# A verdict is a SAFETY exit when driven by depeg/liquidation/spread-inversion;
# OPTIMIZATION exits (ROTATE / yield-driven DELEVERAGE) are deferrable.

def apply_min_hold_lock(action: str, *, reason: str, locked: bool, safety: bool) -> dict:
    """Enforce the min-hold lock. Safety exits ALWAYS pass. Optimization exits
    (ROTATE, yield-driven DELEVERAGE) are downgraded to HOLD while `locked`.
    Returns {action, locked, override?, deferred_reason?}."""
    if safety:
        return {"action": action, "locked": locked, "override": reason}
    if locked and action in (ROTATE, DELEVERAGE):
        return {"action": HOLD, "locked": True, "deferred_reason": reason}
    return {"action": action, "locked": locked}
```

- [ ] **Step 5: Wire it at the `evaluate` call site** — in `vault_orchestrator.py` where the monitor verdict is acted on, compute `locked = now < min_hold_until` and `safety = verdict in {depeg, liquidation, spread_inverted}`, then pass the verdict through `apply_min_hold_lock` before acting. (Record `entry_ts` + `min_hold_until` on position open, using `min_hold_period`.)

- [ ] **Step 6: Run test + existing monitor tests**

Run: `uv run pytest contest_bot/tests/test_min_hold_lock.py -v && uv run pytest contest_bot/tests/ -k "monitor or vault" -v`
Expected: PASS; no regressions.

- [ ] **Step 7: Commit**

```bash
git add contest_bot/kamino/monitor.py contest_bot/kamino/vault_orchestrator.py contest_bot/tests/test_min_hold_lock.py
git commit -m "feat(s48-p2): min-hold lock — defer optimization exits, safety always overrides"
```

### Task 13: Paper Multiply walk-through (end-to-end, $0)

**Files:** none (verification + a small demo script optional).

- [ ] **Step 1: Run the full Phase-2 flow against live rates in paper** — load catalog, rank for a profile, pick #1, open a sim Multiply via the paper ledger, advance the monitor with the lock active, confirm an optimization ROTATE is deferred until `min_hold_until` and a simulated depeg forces EXIT immediately.

Run: `uv run python - <<'PY'
from kamino.catalog import load_catalog
from kamino.selector import rank_catalog
menu = rank_catalog(load_catalog(), profile="Balanced", principal=1000.0, cost=0.0027, horizon_years=0.5)
for m in menu: print(m["name"], "net%", m["net_apy_after_cost"], "min_hold_days", m["min_hold_days"])
print("PICK:", menu[0]["name"] if menu else "none")
PY`
Expected: a ranked menu with per-option `min_hold_days`; a non-empty pick.

- [ ] **Step 2: Record the menu output in the PR description.** No commit.

### Task 14: First Multiply on mainnet — GATED (founder-run)

**Files:** none here (rides A2/A3/A4, tasks #191/#192).

- [ ] **Step 1: Build + dry-run the Multiply tx** via `ts-sidecar` + OKX-TEE for the picked market + amount. Confirm the unsigned tx + simulation succeed (no broadcast).
- [ ] **Step 2: Run the pre-mainnet checklist** (#192): custody, contract test, fee sim, monitor-fires-before-liquidation.
- [ ] **Step 3: STOP. Explicit founder go + dollar amount required before any broadcast.** Real money. Devnet skipped (oracle-blocked).
- [ ] **Step 4: Broadcast small ($20–50); confirm the min-hold lock is active on the live position and the monitor's safety overrides are armed (Pegana wired).**

---

## Self-Review

**Spec coverage:** Phase 1 §topology→Task 5/6; container→Task 2; entrypoint safety→Task 1; SSM→Task 4; verification→Task 3/7. Phase 2 A→Task 10; B→Task 8; C→Task 11 (+ rename Task 9); D→Task 12; E→Task 14; paper walk-through→Task 13. All spec sections covered.

**Placeholder scan:** Task 10 uses real Kamino field names *recorded in its own Step 1 spike* before coding — the one legitimate "confirm at runtime" point, with a fallback path; not a placeholder. No TBDs elsewhere.

**Type consistency:** `min_hold_period`/`net_apy_after_cost`/`round_trip_cost` (Task 8) are consumed with the same signatures in Tasks 11/12/13. `normalize_profile` (Task 9) consumed in Task 11. `apply_min_hold_lock` returns `{action,...}` consumed in Task 12 Step 5. Verdict constants `EXIT/DELEVERAGE/ROTATE/HOLD` reused from existing `monitor.py`.

**Boundaries:** every AWS-deploy + real-money step is explicitly founder-gated; paper/stub baked; targeted pytest throughout.
