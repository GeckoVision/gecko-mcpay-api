#!/usr/bin/env bash
# Setup C experiment launcher — 2026-05-28
#
# Synthesis of founder's Phase 2 finding (legacy beats strict on contest
# slice, single-trade noise per window) + Sprint 8 shadow harness finding
# (99% of damage = 3 catastrophic SL trades on JTO/JUP, WIF/PYTH/RAY are
# safe).
#
# Three changes vs the prior production config:
#   GECKO_ENTRY_REQUIRE_BREAKOUT=0        (was implicitly 1)  — legacy mode
#   INSTRUMENTS drops JTO + JUP            (was 5 symbols)     — symbol surgery
#   TRAIL_STOP_PCT 0.5 → 0.3              (was 0.5)            — tight trail
#
# Reversion path:
#   cp jto_breakout_gecko_gated_contest_bot.py.bak-pre-setup-c \
#       jto_breakout_gecko_gated_contest_bot.py
#   fuser -k 8265/tcp
#   <relaunch with old command>

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# Setup C — env overrides
export GECKO_ENTRY_REQUIRE_BREAKOUT=0     # legacy mode (Phase 2 path)
export PAPER_TRADE=true                    # NEVER flip without explicit founder go-ahead
export X402_MODE=stub                      # NEVER flip without explicit founder go-ahead
export EXPERIMENT_TAG=setup-c-2026-05-28   # propagated to artifact log for filtering

# Sprint 16 halt (2026-05-28): two-specialist joint review (quant + strategist)
# verdict — the 5m/12h scalp class is FALSIFIED across 25 trades. Stop opening
# new positions; keep bot alive for telemetry-only mode while we build the
# swing executor (Sprint 9 trend_adx_30 transplant, 4h cadence).
#
# OBSERVATION_MODE=1 makes open_position() early-return BEFORE swap_execute.
# Voices, Oracle, dashboard, artifact log all keep firing — only the actual
# swap call is skipped. Use for full-stack telemetry without capital risk.
export OBSERVATION_MODE=1

echo "================================================================"
echo "Setup C launch — 2026-05-28"
echo "  GECKO_ENTRY_REQUIRE_BREAKOUT=${GECKO_ENTRY_REQUIRE_BREAKOUT}"
echo "  PAPER_TRADE=${PAPER_TRADE}"
echo "  X402_MODE=${X402_MODE}"
echo "  Universe (in code): PYTH, WIF, RAY  (dropped JTO + JUP)"
echo "  TRAIL_STOP_PCT (in code): 0.3  (was 0.5)"
echo "================================================================"

exec uv run --project .. python3 -u jto_breakout_gecko_gated_contest_bot.py
