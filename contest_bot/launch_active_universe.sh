#!/usr/bin/env bash
# Active-Universe Paper Agent launcher — 2026-06-16
#
# Spec: docs/strategy/2026-06-16-active-universe-paper-agent-spec.md
#
# Goal: an OBSERVABLE paper agent on a volatile memecoin universe whose
# entries ACTUALLY FIRE, gated live by Gecko's two-tier decision flow:
#   TIER 1 — POST /safety (fast deterministic veto, PR #140)
#   TIER 2 — the local panel + cached oracle verdict (already wired)
#
# This is for DEMONSTRATION + E2E validation, NOT alpha. The memecoin scalp
# class is a documented null ([[project_sprint_17_strategy_class_dead]]) — the
# deliverable is the visible gated loop (entry → position → exit → PnL), not
# returns.
#
# ADDITIVE — does NOT touch the majors agent. Runs as a PARALLEL process via:
#   - own GECKO_STATE_DIR  (no state collision with the majors agent)
#   - own DASHBOARD_PORT 8267  (majors trend_breakout=8265 / mean_reversion=8266)
#
# Boundaries (hard): PAPER + stub only. No live flip, no real money, no x402
# live. Never restart a bot with an open position.
#
# Reversion: just stop this process (fuser -k 8267/tcp). The majors agent is
# untouched. State lives under GECKO_STATE_DIR, so nothing leaks into the
# legacy contest_bot/bot_state.json.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# Load secrets from repo-root .env (OPENROUTER_API_KEY for the local panel,
# MONGO_URI for the behavior sink, etc). `set -a` auto-exports every var
# defined while it's on — propagates to the python child. See the Setup C
# launcher for the panel-disabled-regression backstory.
ENV_FILE="$(cd .. && pwd)/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    echo "Loaded env from $ENV_FILE"
else
    echo "WARN: no .env at $ENV_FILE — local panel will be disabled (OPENROUTER_API_KEY missing)"
fi

# ── Mode (hard boundaries) ─────────────────────────────────────────
export PAPER_TRADE=true                          # NEVER flip without explicit founder go-ahead
export X402_MODE=stub                            # NEVER flip without explicit founder go-ahead
export EXPERIMENT_TAG=active-universe-2026-06-16  # propagated to artifact log for filtering
export UNIVERSE_LABEL=active-memecoin

# ── Universe: the active memecoin set (fires often) ────────────────
# High volatility → frequent breakout signals → the loop is visible. The
# bot resolves these symbols to their Solana mints from its INSTRUMENTS
# table (PYTH/WIF in-table) — POPCAT/BOME are added via GECKO_UNIVERSE.
# NOTE: GECKO_UNIVERSE filters the in-code INSTRUMENTS list by symbol, so a
# symbol only takes effect if its mint exists in INSTRUMENTS. PYTH + WIF are
# present today; POPCAT/BOME are commented out in-code (need mint re-add to
# activate). Leaving them in the list is harmless (silently dropped) and
# documents the intended universe.
export GECKO_UNIVERSE="PYTH,WIF,POPCAT,BOME"

# ── Isolated state (parallel-process safety) ───────────────────────
# Own state dir so open/close/daily-reset never collide with the majors
# agent's bot_state.json. Created if missing.
export GECKO_STATE_DIR="${GECKO_STATE_DIR:-$HOME/.gecko/active-universe}"
mkdir -p "$GECKO_STATE_DIR"
export DASHBOARD_PORT=8267

# ── gecko-api base URL for the TIER-1 /safety call ─────────────────
# Local-first default. For the parallel-ECS deploy (P3), point this at the
# deployed gecko-api (e.g. https://api.geckovision.tech).
export GECKO_API_URL="${GECKO_API_URL:-http://127.0.0.1:8000}"
export GECKO_SAFETY_GATE="${GECKO_SAFETY_GATE:-1}"   # tier-1 on; set 0 to bypass (offline smoke)

# ── Observation gate profile (clearly-labeled, slightly loosened) ──
# Per spec open-question #3: loosen the considered (tier-2) gate so MORE
# entries fire and the loop is visibly demonstrated. This is a DEMO profile,
# NOT the prod-strict gate. Each loosening is one env flip vs Setup C.
#
#   - legacy OR-semantics entry (breakout OR volume) so candidates fire more
#   - weighted_quorum coordinator (doesn't hard-require chart_analyst bullish)
#   - lower chart_analyst confidence floor
#   - MFI hard-gate OFF (shadow-log only) so overbought entries still fire
#   - real-trading mode (OBSERVATION_MODE off) so paper FILLS actually happen
export GECKO_ENTRY_REQUIRE_BREAKOUT=0
export GECKO_COORDINATOR_MODE=weighted_quorum
export GECKO_CHART_MIN_CONF=0.70
export GECKO_TREAT_UNKNOWN_1H_AS_ADVERSE=0
export GECKO_MFI_HARD_GATE=0
export GECKO_MFI_SHADOW_THRESHOLD=70
# OBSERVATION_MODE stays OFF (default) — we WANT paper fills to observe the
# full entry→exit→PnL loop. Paper-fills are against real tape, not real money.

# ── Volume / caps for an observable cadence ────────────────────────
export MAX_DAILY_TRADES="${MAX_DAILY_TRADES:-20}"
export MAX_CONCURRENT="${MAX_CONCURRENT:-2}"
export SESSION_LOSS_PAUSE="${SESSION_LOSS_PAUSE:-5}"

echo "================================================================"
echo "Active-Universe Paper Agent — 2026-06-16"
echo "  PAPER_TRADE=${PAPER_TRADE}   X402_MODE=${X402_MODE}"
echo "  GECKO_UNIVERSE=${GECKO_UNIVERSE}  (resolved against in-code mints)"
echo "  GECKO_STATE_DIR=${GECKO_STATE_DIR}"
echo "  DASHBOARD_PORT=${DASHBOARD_PORT}"
echo "  GECKO_API_URL=${GECKO_API_URL}  (tier-1 /safety: ${GECKO_SAFETY_GATE})"
echo "  Gate profile: OBSERVATION (loosened) — coordinator=${GECKO_COORDINATOR_MODE}"
echo "  ADDITIVE — does NOT touch the majors agent (ports 8265/8266)"
echo "================================================================"

exec uv run --project .. python3 -u jto_breakout_gecko_gated_contest_bot.py
