#!/usr/bin/env bash
# S41 — refresh the market-temperature snapshot on a cadence.
#
# The bot's risk-off gate (GECKO_MARKET_TEMP_GATE=1) reads market_temp.json and
# fails-open when it's older than GECKO_MARKET_TEMP_MAX_AGE_S (default 6h). So
# this must run at least every few hours to stay live. A crontab line like:
#
#   0 */2 * * *  cd /path/to/gecko-mcpay-api && contest_bot/refresh_market_temp_cron.sh >> /tmp/mkt-temp.log 2>&1
#
# Data source for the OKX coin-sentiment + headlines is the okx-agent-trade-kit
# MCP (`news_get_coin_sentiment` / `news_get_latest`), which a plain cron can't
# call. Two supported modes:
#   • FED MODE (preferred): a Claude/MCP step writes the parsed OKX response to
#     $GECKO_MKT_SENTIMENT_JSON (+ optional $GECKO_MKT_HEADLINES_TXT /
#     $GECKO_MKT_MOVES_JSON); this wrapper feeds them to refresh_market_temp.py.
#   • DEMO FALLBACK: if no sentiment file is present, refresh with --demo so the
#     snapshot is never missing (the gate then reads a known risk-off baseline).
# Either way the snapshot stays fresh enough that the gate never silently goes
# stale-open in the middle of a live macro event.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && source .env; set +a

SENT="${GECKO_MKT_SENTIMENT_JSON:-}"
HEAD="${GECKO_MKT_HEADLINES_TXT:-}"
MOVES="${GECKO_MKT_MOVES_JSON:-}"

if [ -n "$SENT" ] && [ -f "$SENT" ]; then
  ARGS=(--sentiment "$SENT")
  [ -n "$HEAD" ] && [ -f "$HEAD" ] && ARGS+=(--headlines "$HEAD")
  [ -n "$MOVES" ] && [ -f "$MOVES" ] && ARGS+=(--moves "$MOVES")
  echo "[refresh] FED mode: $SENT"
  uv run python contest_bot/refresh_market_temp.py "${ARGS[@]}"
else
  echo "[refresh] no sentiment file ($SENT) — DEMO fallback (snapshot stays fresh, not missing)"
  uv run python contest_bot/refresh_market_temp.py --demo
fi
