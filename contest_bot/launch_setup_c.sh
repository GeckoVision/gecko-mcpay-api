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

# Load secrets from repo-root .env (OPENROUTER_API_KEY, MONGO_URI, etc).
# This is the FIX for the panel-disabled regression introduced in the
# initial Setup C launcher (2026-05-28): I set a clean env that dropped
# OPENROUTER_API_KEY from inheritance → local panel disabled silently →
# no voice decisions visible on dashboard.
#
# Pattern: `set -a` auto-exports every var defined while it's on; source
# the .env file; `set +a` turn it back off. This makes the .env values
# available to all subprocess (uv run, python child, etc).
ENV_FILE="$(cd .. && pwd)/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    echo "Loaded env from $ENV_FILE"
else
    echo "WARN: no .env at $ENV_FILE — panel will be disabled (OPENROUTER_API_KEY missing)"
fi

# Setup C — env overrides (these win over .env if both define them)
export GECKO_ENTRY_REQUIRE_BREAKOUT=0     # legacy mode (Phase 2 path)
export PAPER_TRADE=true                    # NEVER flip without explicit founder go-ahead
export X402_MODE=stub                      # NEVER flip without explicit founder go-ahead
export EXPERIMENT_TAG=setup-c-2026-05-28   # propagated to artifact log for filtering

# 2026-05-28 founder override (03:30 UTC): "Restart and increase the trades
# number - otherwise we will lost the window until 9PM".
#
# Restoring real-trading mode (OBSERVATION_MODE OFF) per founder's "lose the
# window" framing. This OVERRIDES the Sprint 16 OBSERVATION_MODE plan and
# the Sprint 17 verdict that the strategy class is falsified — founder's
# explicit call. PAPER_TRADE=true still in force, so trades are paper-fills
# against real-tape price, not real money. Sprint 17 -EV finding stands as
# documentation; founder accepts the data-collection cost.
#
# To restore Sprint 17 OBSERVATION_MODE: uncomment the line below.
# export OBSERVATION_MODE=1

# Raised caps for the window
export MAX_DAILY_TRADES=20      # was 3, then 10; founder bumped to 20 for window
export MAX_CONCURRENT=4         # founder's pick from earlier session
export SESSION_LOSS_PAUSE=5     # slightly relaxed from default 2

# Sprint 24-L (2026-05-30) — Variant E: drop the 1h-adverse modulator only.
# Per quant analysis: post-voice-fix, the coordinator's 1h-adverse floor at 0.92
# captures 100% of chart_analyst's hard-coded bullish-confidence-0.85 events,
# producing 0 fires in 12h. Discipline check ✓ — 17 historical Setup C wins were
# 100% TREND-UP or CHOP, never the unknown-1h-adverse case. Setting this to 0
# reverts to legacy fail-open on unknown 1h regime, projected 123-185 fires/24h.
# Treated as shadow-test: monitor first 20 fires for DSR ≥ 0.95 before declaring success.
export GECKO_TREAT_UNKNOWN_1H_AS_ADVERSE=0

echo "================================================================"
echo "Setup C launch — 2026-05-28"
echo "  GECKO_ENTRY_REQUIRE_BREAKOUT=${GECKO_ENTRY_REQUIRE_BREAKOUT}"
echo "  PAPER_TRADE=${PAPER_TRADE}"
echo "  X402_MODE=${X402_MODE}"
echo "  Universe (in code): PYTH, WIF, RAY  (dropped JTO + JUP)"
echo "  TRAIL_STOP_PCT (in code): 0.3  (was 0.5)"
echo "================================================================"

exec uv run --project .. python3 -u jto_breakout_gecko_gated_contest_bot.py
