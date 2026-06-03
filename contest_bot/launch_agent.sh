#!/usr/bin/env bash
# launch_agent.sh <agent_id> — orchestrator for a hosted single-tenant paper agent
# (Phase 2). Reads the DEPLOYED StrategySpec from the registry, translates it to
# env (strategy/universe/venue), and starts the monolith with GECKO_AGENT_ID + a
# Mongo state backend so its state lands in the DB for the app dashboard.
#
#   POST /agents (control plane) → agent_id → bash launch_agent.sh <agent_id>
#
# Paper-only. PAPER_TRADE/X402_MODE never flip here.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

AGENT_ID="${1:?usage: bash launch_agent.sh <agent_id> [port]}"
PORT="${2:-8280}"

ENV_FILE="$(cd .. && pwd)/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# Translate the registry spec → env (strategy_id / universe / venue).
ENV_EXPORTS="$(uv run --project .. python3 - "$AGENT_ID" <<'PY'
import sys
from agent_store import AgentRegistry

doc = AgentRegistry().get(sys.argv[1])
if not doc or not doc.get("spec"):
    sys.stderr.write(f"no deployed agent: {sys.argv[1]}\n")
    sys.exit(3)
spec = doc["spec"]
uni = ",".join(spec.get("universe") or [])
print(f"export GECKO_STRATEGY={spec.get('strategy_id', 'trend_breakout')}")
print(f"export GECKO_UNIVERSE={uni}")
print(f"export GECKO_VENUE={spec.get('venue', 'okx_spot')}")
PY
)" || { echo "launch_agent: could not resolve agent $AGENT_ID" >&2; exit 3; }
eval "$ENV_EXPORTS"

export GECKO_AGENT_ID="$AGENT_ID"
export GECKO_STATE_BACKEND=mongo
export GECKO_STATE_DIR="$(pwd)/state/agent_$AGENT_ID"   # file fallback if Mongo is down
mkdir -p "$GECKO_STATE_DIR"
export DASHBOARD_PORT="$PORT"
export PAPER_TRADE=true
export X402_MODE=stub
export GECKO_KAMINO_PAPER_SINK=0

echo "================================================================"
echo "Hosted agent $AGENT_ID (Phase 2)"
echo "  GECKO_STRATEGY=${GECKO_STRATEGY}  GECKO_VENUE=${GECKO_VENUE}"
echo "  GECKO_UNIVERSE=${GECKO_UNIVERSE}"
echo "  state=mongo(agent_state)  port=${DASHBOARD_PORT}  PAPER_TRADE=true"
echo "================================================================"

exec uv run --project .. python3 -u jto_breakout_gecko_gated_contest_bot.py
