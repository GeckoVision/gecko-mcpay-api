#!/usr/bin/env bash
# Local-first control plane (B2) — the single server the user runs locally.
#
# Serves the whole agent surface on one port so the App (or Claude Code) can drive
# everything via GECKO_AGENT_CONTROL_URL=http://localhost:8271 :
#   GET  /healthz       liveness + data coverage
#   POST /backtest      rigor verdict (run_backtest)
#   GET/POST /agents …  deploy / list / start / stop hosted paper agents
#   GET  /market-temp   the risk-on/off read
#   GET  /vault         profit-vault state + per-lot monitor verdicts
#
# Usage:  bash contest_bot/launch_control_plane.sh            # foreground
#         PORT=8271 bash contest_bot/launch_control_plane.sh
#
# PAPER/stub by default — real-money vault ops go through the founder-gated
# live-executor (kamino/live_executor.py), never auto-fired by this server.
set -euo pipefail
cd "$(dirname "$0")"
set -a; [ -f ../.env ] && source ../.env; set +a

PORT="${PORT:-8271}"
echo "================================================================"
echo "Gecko control plane → http://localhost:${PORT}"
echo "  App env: GECKO_AGENT_CONTROL_URL=http://localhost:${PORT}"
echo "  Endpoints: /healthz /backtest /agents /market-temp /vault"
echo "  PAPER + x402 stub. Real-money vault = founder-gated live-executor only."
echo "================================================================"
exec uv run --project .. uvicorn agent_api:app --host 0.0.0.0 --port "${PORT}"
