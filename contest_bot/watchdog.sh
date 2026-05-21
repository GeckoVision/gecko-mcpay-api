#!/bin/bash
# Overnight watchdog (2026-05-21) — keeps the live contest bot alive.
# The bot crashed several times tonight from process/port issues; this
# auto-restarts it (carefully, avoiding port collisions) so it doesn't miss
# the remaining entry opportunity while the founder sleeps.
#
# Restart is conservative: only when NO python bot is running AND port 8265
# is free (prevents the duplicate-process collisions we hit tonight).
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/contest_bot || exit 1
LOG=watchdog.log
echo "$(date -u +%FT%TZ) [watchdog] started" >> "$LOG"
while true; do
  if ! pgrep -f "python3 -u jto_breakout" >/dev/null 2>&1; then
    if ! ss -tlnp 2>/dev/null | grep -q ':8265'; then
      echo "$(date -u +%FT%TZ) [watchdog] bot DOWN, port free — restarting" >> "$LOG"
      set -a; . ../.env; set +a
      nohup bash -c 'echo CONFIRM | python3 -u jto_breakout_gecko_gated_contest_bot.py' >> bot_live.log 2>&1 &
      sleep 25
      if pgrep -f "python3 -u jto_breakout" >/dev/null 2>&1; then
        echo "$(date -u +%FT%TZ) [watchdog] restart OK" >> "$LOG"
      else
        echo "$(date -u +%FT%TZ) [watchdog] restart FAILED — will retry" >> "$LOG"
      fi
    else
      echo "$(date -u +%FT%TZ) [watchdog] proc down but port 8265 bound — waiting" >> "$LOG"
    fi
  fi
  sleep 60
done
