#!/bin/sh
# Entrypoint for the hosted gecko-agent task. Paper-only, Mongo-backed.
# Safety env is BAKED here so it cannot be flipped by SSM / task-def env.
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
export DASHBOARD_PORT=8265          # localhost-only; used by the container healthcheck

cd /app/contest_bot
exec python -u jto_breakout_gecko_gated_contest_bot.py
