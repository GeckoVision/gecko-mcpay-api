#!/usr/bin/env bash
# One-command restart script — Sprint 17 (2026-05-28).
#
# Run this when you wake up. It will:
#   1. Verify zero open positions (never restart with open positions per memory)
#   2. Kill the existing bot on port 8265
#   3. Relaunch with the new launch_setup_c.sh (which sources .env now, adds
#      OBSERVATION_MODE=1, and raises caps)
#   4. Verify the dashboard comes back up
#
# After this runs:
#   - Bot logs to /tmp/scalp_observation.log
#   - OPENROUTER_API_KEY now propagates → panel decisions visible
#   - OBSERVATION_MODE=1 → no swap_execute calls, full telemetry only
#   - honest_decomposition + expectancy fields exposed in /api/state
#
# If WIF is still open: this script will refuse to restart (per memory rule).
# Wait for SL/timeout or close manually via the dashboard.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "=== Pre-flight check ==="
OPEN=$(python3 -c "
import json
s = json.load(open('bot_state.json'))
op = [p for p in s.get('positions', []) if p.get('status') == 'open']
print(len(op))
")
if [[ "$OPEN" -gt 0 ]]; then
    echo "  ✗ $OPEN open position(s) — REFUSING to restart"
    python3 -c "
import json
s = json.load(open('bot_state.json'))
for p in [p for p in s.get('positions', []) if p.get('status') == 'open']:
    print(f\"    {p.get('symbol')} entry={p.get('entry_price')} since={p.get('entry_ts')}\")
"
    echo "  Wait for close (SL/TP/timeout), then re-run."
    exit 1
fi
echo "  ✓ 0 open positions — safe to restart"

echo ""
echo "=== Stopping old bot (port 8265) ==="
fuser -k 8265/tcp 2>&1 || echo "  (no listener on 8265 — already down)"
sleep 2

echo ""
echo "=== Launching with Sprint 17 changes ==="
nohup ./launch_setup_c.sh > /tmp/scalp_observation.log 2>&1 &
LAUNCH_PID=$!
echo "  Launched PID $LAUNCH_PID"

echo ""
echo "=== Waiting for dashboard (up to 90s) ==="
for i in {1..30}; do
    if ss -tlnp 2>/dev/null | grep -q ":8265"; then
        echo "  ✓ Dashboard on http://localhost:8265 (poll #$i)"
        break
    fi
    sleep 3
done

echo ""
echo "=== Final state ==="
sleep 2
tail -20 /tmp/scalp_observation.log

echo ""
echo "=== Verify env propagation ==="
PID=$(pgrep -f "python3.*jto_breakout_gecko_gated_contest_bot.py" | head -1)
if [[ -n "$PID" ]]; then
    echo "  Bot PID: $PID"
    cat /proc/$PID/environ 2>/dev/null | tr '\0' '\n' | grep -E "^(OPENROUTER_API_KEY|OBSERVATION_MODE|GECKO_ENTRY|MAX_DAILY|MAX_CONCURRENT)=" | sed 's/=.*$/=<set>/'
fi

echo ""
echo "=== /api/state honest_decomposition check ==="
sleep 5
curl -s http://localhost:8265/api/state 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  has honest_decomposition: {\"honest_decomposition\" in d}')
print(f'  has expectancy_pct in stats: {\"expectancy_pct\" in d.get(\"stats\", {})}')
hd = d.get('honest_decomposition', {})
if hd:
    print(f'  n_closed: {hd.get(\"n_closed\", 0)}')
    print(f'  by_exit_reason keys: {list(hd.get(\"by_exit_reason\", {}).keys())}')
" 2>/dev/null || echo "  (curl/parse failed; check dashboard manually)"

echo ""
echo "=== Done ==="
echo "  Dashboard: http://localhost:8265"
echo "  Log:       /tmp/scalp_observation.log"
echo "  Progress:  uv run python ../scripts/analysis/setup_c_progress.py"
