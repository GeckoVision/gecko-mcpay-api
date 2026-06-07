#!/usr/bin/env bash
# Bot contest — each strategy runs as its OWN paper bot (own port + own
# GECKO_STATE_DIR), concurrently, until tomorrow. Best PnL/survival wins.
# This is the "user picks one OR MORE strategies" model: each strategy = a
# deployable agent. PAPER + stub only — no real money, no order routing.
#
# The 30h-stuck lesson (S31): bots that sit at 0 trades for hours look "broken."
# contest_watchdog.py flags any contestant that crashes, freezes, or sits with
# 0 entries past a grace window. Rank live with contest_scoreboard.py.
#
#   bash launch_contest.sh           # launch all contestants (skips any already up)
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

ENV_FILE="$(cd .. && pwd)/.env"
if [[ -f "$ENV_FILE" ]]; then set -a; source "$ENV_FILE"; set +a; echo "Loaded env"; fi

UNIVERSE="${GECKO_UNIVERSE:-BTC,ETH,SOL,XRP,DOGE}"

# contestant -> port. Legacy gated breakout (Setup C) runs separately on 8267
# (launch_setup_c.sh) and is included in the scoreboard as the control.
CONTESTANTS=("trend_breakout:8265" "mean_reversion:8266" "range_fade:8268")

for entry in "${CONTESTANTS[@]}"; do
  STRAT="${entry%%:*}"; PORT="${entry##*:}"
  SD="$(pwd)/state/contest/$STRAT"
  mkdir -p "$SD"
  if curl -s -o /dev/null --max-time 2 "localhost:$PORT/healthz" 2>/dev/null; then
    echo "[$STRAT] already up on :$PORT — skip"; continue
  fi
  echo "[$STRAT] launching on :$PORT (state $SD)"
  env GECKO_STRATEGY="$STRAT" GECKO_VENUE=okx_spot GECKO_UNIVERSE="$UNIVERSE" \
      DASHBOARD_PORT="$PORT" GECKO_STATE_DIR="$SD" \
      PAPER_TRADE=true X402_MODE=stub GECKO_KAMINO_PAPER_SINK=0 \
      EXPERIMENT_TAG="contest-$STRAT" \
      setsid uv run --project .. python3 -u jto_breakout_gecko_gated_contest_bot.py \
      > "$SD/run.log" 2>&1 < /dev/null &
  echo "  pid $! → log $SD/run.log"
done
echo "----"
echo "contestants launching. Rank:  uv run python contest_scoreboard.py"
echo "Watchdog (anti-stuck):        uv run python contest_watchdog.py"
