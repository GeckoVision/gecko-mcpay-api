#!/bin/sh
# Entrypoint for the hosted gecko-agent task. Paper-only, Mongo-backed, HEADLESS.
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

# --- Venue: okx_spot = the HEADLESS PAPER path (2026-06-07 deploy fix) ---
# Public OKX market data via ccxt: NO onchainos CLI, NO wallet, NO login.
# preflight() skips the wallet/login check for okx_spot (paper signs nothing).
# The legacy "onchainos" venue CANNOT run headless — it shells out to the
# onchainos CLI (not in the image) and requires a logged-in session, which
# crash-looped the first deploy ("Not logged in → sys.exit(1)"). Entries are
# driven by the strategies/ registry (GECKO_STRATEGY), not the legacy gate.
# All three are overridable via task-def env without rebuilding the image.
export GECKO_VENUE="${GECKO_VENUE:-okx_spot}"
export GECKO_STRATEGY="${GECKO_STRATEGY:-trend_breakout}"
export GECKO_UNIVERSE="${GECKO_UNIVERSE:-BTC,ETH,SOL,DOGE}"
export MAX_DAILY_TRADES="${MAX_DAILY_TRADES:-20}"
export MAX_CONCURRENT="${MAX_CONCURRENT:-2}"
export DASHBOARD_PORT=8265          # localhost-only; used by the container healthcheck

cd /app/contest_bot
exec python -u jto_breakout_gecko_gated_contest_bot.py
