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
export MAX_CONCURRENT=2         # 2026-05-31 founder: 4 → 2, "enough volume"
export SESSION_LOSS_PAUSE=5     # slightly relaxed from default 2

# Sprint 24-L (2026-05-30) — Variant E: drop the 1h-adverse modulator only.
# Per quant analysis: post-voice-fix, the coordinator's 1h-adverse floor at 0.92
# captures 100% of chart_analyst's hard-coded bullish-confidence-0.85 events,
# producing 0 fires in 12h. Discipline check ✓ — 17 historical Setup C wins were
# 100% TREND-UP or CHOP, never the unknown-1h-adverse case. Setting this to 0
# reverts to legacy fail-open on unknown 1h regime, projected 123-185 fires/24h.
# Treated as shadow-test: monitor first 20 fires for DSR ≥ 0.95 before declaring success.
export GECKO_TREAT_UNKNOWN_1H_AS_ADVERSE=0

# Sprint 24-M (2026-05-30) — Variant F: lower chart_analyst confidence floor.
# Post-Variant-E, 100% of 40 panel events declined via chart_below_threshold.
# The hard-coded 0.85 floor on chart_analyst.confidence captures the only
# "positive signal" voice the panel has — even bullish-leaning tuples can't
# fire. Lower to 0.75 as a single 0.10-step relaxation. Composes with E.
# Projected fires/day: 30-50 (between E's 0 and Variant-B's 240-318).
# Shadow-test: 20 fires + DSR ≥ 0.95 before promote.
export GECKO_CHART_MIN_CONF=0.75

# Sprint 24-O (2026-05-30) — Variant G: weighted_quorum coordinator mode.
# Founder explicit authorization 22:55 UTC. Post-Variant-E+F still 0 fires
# in 96 panel events because the LEGACY coordinator requires chart_analyst
# to be bullish (Rule 2 hard cut), and chart_analyst was 79% neutral/abstain
# today. Variant G replaces the sequential decline-chain with a weighted
# vote: bullish=+2, neutral=+1, bearish=-1, abstain=0; act if score ≥ 2;
# hard veto if ≥3 bearish votes; 1h-adverse adds +1 to act threshold.
# Risk_veto + chart_voice_missing safety paths preserved verbatim.
# Projection: ~30-40 fires/day on today's voice distribution.
# Shadow-test discipline: monitor first 20 fires for DSR ≥ 0.95 before
# treating as permanent. Set to "legacy" to revert.
export GECKO_COORDINATOR_MODE=weighted_quorum

# Sprint 24-X (2026-05-31) — Model A/B on chart_analyst only.
# Founder picked deepseek/deepseek-v4-flash from OpenRouter (verified
# live): $0.098/$0.197 per 1M tok, ~3x CHEAPER than gpt-4o-mini's
# $0.15/$0.60 baseline. Only the chart_analyst voice is swapped so the
# experiment isolates one variable. Other 3 voices stay on gpt-4o-mini
# (env unset → resolves to DEFAULT_MODEL).
# Falsifier (per ai-ml-engineer design doc §4): within first 50 polls
# chart_analyst should produce ≥5 unique confidence values AND ≥2
# distinct non-abstain verdicts. If unique_conf ≤ 3 OR bullish-rate
# 5x-explodes uncontrollably, revert by commenting out the line below
# and restarting.
export GECKO_CHART_ANALYST_MODEL=deepseek/deepseek-v4-flash

# Sprint 25 (2026-06-01) — Kamino paper-sink enabled.
# Best-effort auto-deposit of idle USDC into the SIMULATED Kamino main
# USDC vault when idle balance clears the threshold. Paper mode only —
# no real on-chain transactions; APY accrued via closed-form math
# against the live Kamino published APY (~4.22% as of 2026-05-31).
# Falsifier per S25-C ship-gate: if net APY < 2.0% sustained 7d on
# N≥30 deposits, revert (comment this out + restart).
# Watch: tail ~/.gecko/kamino_paper_ledger.jsonl + terminal for
# [PAPER] KAMINO {DEPOSIT|ACCRUE|WITHDRAW|SKIP|STALE|ERROR} events.
export GECKO_KAMINO_PAPER_SINK=1

# Sprint 30 (2026-06-01) — flat_stall_exit refinement, all default OFF
# (shadow-log only). 3-agent autopsy (quant + strategist + ai-ml) verdict:
# stall is correctly catching real losers (-0.366% mean, p=0.002, N=27)
# but the +0.5% upper-band ceiling snips ~50% of would-be take_profit moves.
# Three falsifiers stacked, each gated:
#   A — peak_pnl_pct / peak_pnl_ts on position_close (ALWAYS on; pure data)
#   B — GECKO_STALL_TRIGGER_MODE=below_entry switches the trigger from
#       "no new high for 30min" to "price below entry for 45min". Default
#       "no_new_high" (current behavior). Flip to "below_entry" after
#       Founder reads the autopsy doc.
#   C — GECKO_MFI_HARD_GATE=1 declines candidate entries with MFI ≥ 70
#       (74% of stall bleed per ai-ml). Default OFF → shadow-log only.
# Falsifier review at N≥15 closes post-flip per Sprint 30 plan.
export GECKO_STALL_TRIGGER_MODE=no_new_high
export GECKO_STALL_BELOW_ENTRY_MIN=45
export GECKO_MFI_SHADOW_THRESHOLD=70
export GECKO_MFI_HARD_GATE=0

echo "================================================================"
echo "Setup C launch — 2026-05-28"
echo "  GECKO_ENTRY_REQUIRE_BREAKOUT=${GECKO_ENTRY_REQUIRE_BREAKOUT}"
echo "  PAPER_TRADE=${PAPER_TRADE}"
echo "  X402_MODE=${X402_MODE}"
echo "  Universe (in code): PYTH, WIF, RAY  (dropped JTO + JUP)"
echo "  TRAIL_STOP_PCT (in code): 0.3  (was 0.5)"
echo "================================================================"

exec uv run --project .. python3 -u jto_breakout_gecko_gated_contest_bot.py
