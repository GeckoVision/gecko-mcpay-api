#!/usr/bin/env bash
# Generalized per-strategy launcher — Sprint 31 (two-strategy alpha search).
#
#   bash launch_strategy.sh trend_breakout     # → port 8265
#   bash launch_strategy.sh mean_reversion      # → port 8266
#
# Each strategy runs as its OWN process: own port, own GECKO_STATE_DIR subdir
# (state/<id>/bot_state.json + artifact_*.jsonl), own strategy rules from
# contest_bot/strategies/. The memecoin Setup-C bot keeps running separately on
# 8267 (launch_setup_c.sh) — these three never collide.
#
# Venue is OKX spot (majors): PAPER mode needs only the public ccxt candle feed
# + simulated fills — NO live order routing, NO api keys.
#
# DO NOT launch a strategy the backtest §5 gate has KILLED. The backtest is the
# verdict authority (contest_bot/backtest_strategy.py); this launcher only
# validates plumbing on the live tape.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

STRATEGY="${1:-}"
case "$STRATEGY" in
    trend_breakout)  PORT=8265 ;;
    mean_reversion)  PORT=8266 ;;
    *)
        echo "usage: bash launch_strategy.sh {trend_breakout|mean_reversion}" >&2
        exit 2
        ;;
esac

# Load secrets (.env) so subprocesses inherit OPENROUTER_API_KEY etc.
# (set -a auto-exports every var sourced; the Sprint-16 panel-disabled bug was
# exactly a launcher that dropped this.) Harmless for the OKX path (no LLM in
# the deterministic coordinator), kept for parity + future voice use.
ENV_FILE="$(cd .. && pwd)/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    echo "Loaded env from $ENV_FILE"
else
    echo "WARN: no .env at $ENV_FILE"
fi

# ── Strategy / venue / universe ────────────────────────────────────
export GECKO_STRATEGY="$STRATEGY"
export GECKO_VENUE=okx_spot
export GECKO_UNIVERSE="${GECKO_UNIVERSE:-BTC,ETH,SOL,XRP,DOGE}"   # PI is probe-or-drop in ingest

# ── Per-process isolation (directory-keyed; never collide) ─────────
export DASHBOARD_PORT="$PORT"
export GECKO_STATE_DIR="$(pwd)/state/$STRATEGY"
mkdir -p "$GECKO_STATE_DIR"

# ── Safety rails (NEVER flip without explicit founder go-ahead) ────
export PAPER_TRADE=true
export X402_MODE=stub
export EXPERIMENT_TAG="s31-$STRATEGY"

# Deterministic coordinator (no LLM panel needed for the new strategies — the
# strategies/ rules ARE the decision). Leave the panel off unless a voice
# experiment is wired later.
export GECKO_KAMINO_PAPER_SINK=0   # the majors processes don't run the Kamino sink

echo "================================================================"
echo "Strategy launch — $STRATEGY (Sprint 31)"
echo "  GECKO_STRATEGY=${GECKO_STRATEGY}"
echo "  GECKO_VENUE=${GECKO_VENUE}"
echo "  GECKO_UNIVERSE=${GECKO_UNIVERSE}"
echo "  DASHBOARD_PORT=${DASHBOARD_PORT}"
echo "  GECKO_STATE_DIR=${GECKO_STATE_DIR}"
echo "  PAPER_TRADE=${PAPER_TRADE}   X402_MODE=${X402_MODE}"
echo "================================================================"

exec uv run --project .. python3 -u jto_breakout_gecko_gated_contest_bot.py
