#!/usr/bin/env bash
# S10-LIVE-01 — pre-flight gate for the first paid mainnet `bb research` call.
#
# What this DOES:
#   1. Sources `.env` from cwd so subsequent checks see the same env the
#      operator's shell will see.
#   2. Asserts `bb doctor` returns exit 0 (nothing red).
#   3. Resolves the client wallet pubkey: prefers `bb wallet info` if it
#      exists, otherwise calls frames.ag REST API with `FRAMES_API_TOKEN`.
#      If neither is available, surfaces a Sprint 11 ticket and aborts.
#   4. Queries Helius RPC for SOL + USDC balances on Solana mainnet. Aborts
#      if SOL < 0.005 (≈ $1) or USDC < 5.0.
#   5. Echos `GECKO_WALLET_ADDRESS` and prompts for interactive Y/N
#      confirmation that this is the operator's own treasury.
#   6. Prints estimated cost ($0.15 USDC + ~$0.001 SOL gas + ~$0.05
#      OpenRouter ≈ $0.20 total).
#   7. Prints the exact `bb` command to run live and exits 0.
#
# What this DOES NOT DO:
#   - Run the live charge. Manual step. The operator copy-pastes the printed
#     command after reviewing it.
#   - Flip `X402_MODE=live` in `.env`. The mainnet flag is per-call only.
#
# Usage:
#   bash scripts/live_preflight.sh
#
# See: docs/runbooks/live-mainnet-smoke.md

set -euo pipefail

# --- styling --------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { printf "  ${GREEN}OK${RESET}    %s\n"   "$*"; }
warn() { printf "  ${YELLOW}WARN${RESET}  %s\n" "$*"; }
fail() { printf "  ${RED}FAIL${RESET}  %s\n"  "$*"; exit 1; }
step() { printf "\n${BOLD}%s${RESET}\n" "$*"; }

# Mainnet USDC mint — keep in sync with packages/gecko-core/src/gecko_core/payments/x402_client.py
USDC_MAINNET_MINT="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Min balances to proceed.
MIN_SOL="0.005"       # ≈ $1 at $200/SOL — covers gas comfortably
MIN_USDC="5.0"        # 25× a single $0.20 round-trip

# --- 1. source .env -------------------------------------------------------
step "[1/7] Loading .env from cwd"
if [[ ! -f .env ]]; then
  fail ".env not found in $(pwd). Run from repo root with .env present."
fi
# shellcheck disable=SC1091
set -a; . ./.env; set +a
ok ".env sourced"

# --- 2. bb doctor ---------------------------------------------------------
step "[2/7] bb doctor"
if ! command -v bb >/dev/null 2>&1; then
  fail "'bb' not on PATH. Run: uv sync && source .venv/bin/activate"
fi
if bb doctor >/tmp/bb-doctor.log 2>&1; then
  ok "bb doctor passed (log: /tmp/bb-doctor.log)"
else
  printf "${RED}--- bb doctor output ---${RESET}\n"
  tail -40 /tmp/bb-doctor.log || true
  fail "bb doctor returned non-zero. Fix red checks before going live."
fi

# --- 3. resolve client wallet pubkey -------------------------------------
step "[3/7] Resolve client wallet pubkey"
WALLET_PUBKEY=""
if bb wallet info --help >/dev/null 2>&1; then
  WALLET_PUBKEY="$(bb wallet info --format=pubkey 2>/dev/null || true)"
  if [[ -z "$WALLET_PUBKEY" ]]; then
    warn "'bb wallet info' exists but returned nothing — falling back to frames REST."
  else
    ok "wallet pubkey via bb wallet info: $WALLET_PUBKEY"
  fi
fi

if [[ -z "$WALLET_PUBKEY" ]]; then
  if [[ -z "${FRAMES_API_TOKEN:-}" && -f "$HOME/.agentwallet/config.json" ]]; then
    if command -v jq >/dev/null 2>&1; then
      FRAMES_API_TOKEN="$(jq -r '.apiToken // empty' "$HOME/.agentwallet/config.json")"
      FRAMES_USERNAME="$(jq -r '.username // empty'  "$HOME/.agentwallet/config.json")"
      WALLET_PUBKEY="$(jq -r '.solanaAddress // empty' "$HOME/.agentwallet/config.json")"
    fi
  fi
  if [[ -n "$WALLET_PUBKEY" ]]; then
    ok "wallet pubkey via ~/.agentwallet/config.json: $WALLET_PUBKEY"
  elif [[ -n "${FRAMES_API_TOKEN:-}" ]]; then
    if ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
      fail "curl + jq required to query frames.ag REST. Install both and retry."
    fi
    FRAMES_BASE="${FRAMES_AG_BASE_URL:-https://frames.ag/api}"
    WALLET_PUBKEY="$(curl -fsS -H "Authorization: Bearer ${FRAMES_API_TOKEN}" \
        "${FRAMES_BASE}/wallets/me" | jq -r '.solanaAddress // empty')"
    [[ -n "$WALLET_PUBKEY" ]] && ok "wallet pubkey via frames REST: $WALLET_PUBKEY" \
                              || fail "frames REST returned no solanaAddress"
  else
    warn "neither 'bb wallet info' nor FRAMES_API_TOKEN/agentwallet config available."
    warn "Sprint 11 ticket: implement 'bb wallet info' subcommand for offline preflight."
    fail "cannot resolve client wallet pubkey"
  fi
fi

# --- 4. balance checks (Helius mainnet) ----------------------------------
step "[4/7] Helius RPC balance check (mainnet)"
if [[ -z "${HELIUS_API_KEY:-}" ]]; then
  warn "HELIUS_API_KEY not set — using public mainnet RPC (rate-limited)."
  RPC_URL="https://api.mainnet-beta.solana.com"
else
  RPC_URL="https://mainnet.helius-rpc.com/?api-key=${HELIUS_API_KEY}"
fi

# SOL balance (lamports → SOL)
SOL_LAMPORTS="$(curl -fsS "$RPC_URL" \
  -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"getBalance\",\"params\":[\"${WALLET_PUBKEY}\"]}" \
  | jq -r '.result.value // 0')"
SOL_BAL="$(awk "BEGIN { printf \"%.6f\", ${SOL_LAMPORTS} / 1000000000 }")"
ok "SOL balance: ${SOL_BAL} SOL (lamports=${SOL_LAMPORTS})"

if awk "BEGIN { exit !(${SOL_BAL} < ${MIN_SOL}) }"; then
  fail "SOL balance ${SOL_BAL} < required ${MIN_SOL}. Fund the wallet for gas."
fi

# USDC balance via getTokenAccountsByOwner filtered by mint.
USDC_RAW="$(curl -fsS "$RPC_URL" \
  -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"getTokenAccountsByOwner\",\"params\":[\"${WALLET_PUBKEY}\",{\"mint\":\"${USDC_MAINNET_MINT}\"},{\"encoding\":\"jsonParsed\"}]}")"

USDC_BAL="$(echo "$USDC_RAW" \
  | jq -r '[.result.value[]?.account.data.parsed.info.tokenAmount.uiAmount // 0] | add // 0')"
ok "USDC balance: ${USDC_BAL} USDC (mint=${USDC_MAINNET_MINT})"

if awk "BEGIN { exit !(${USDC_BAL} < ${MIN_USDC}) }"; then
  fail "USDC balance ${USDC_BAL} < required ${MIN_USDC}. Fund the wallet."
fi

# --- 5. confirm GECKO_WALLET_ADDRESS is the operator's treasury ----------
step "[5/7] Treasury sanity check"
if [[ -z "${GECKO_WALLET_ADDRESS:-}" ]]; then
  fail "GECKO_WALLET_ADDRESS not set in .env. Set it to a Solana pubkey YOU control."
fi
echo "  GECKO_WALLET_ADDRESS = ${GECKO_WALLET_ADDRESS}"
read -rp "  Is this YOUR treasury (the recipient of the charge)? [y/N] " ans
case "${ans:-N}" in
  y|Y|yes|YES) ok "treasury confirmed" ;;
  *) fail "aborted — set GECKO_WALLET_ADDRESS to a wallet you control before retrying" ;;
esac

# --- 6. estimated cost ---------------------------------------------------
step "[6/7] Estimated round-trip cost"
cat <<EOF
  - x402 charge:    \$0.15 USDC (\$0.05 plan + \$0.10 research)
  - Solana gas:     ~\$0.001 SOL (priority + base fee)
  - OpenRouter LLM: ~\$0.05 (basic tier, gpt-4o-mini)
  ----------------------------------------------------
  TOTAL:            ~\$0.20 USD
EOF

# --- 7. ready ------------------------------------------------------------
step "[7/7] READY"
cat <<EOF

Run the live smoke from this same shell:

  X402_MODE=live \\
  X402_NETWORK=solana:${USDC_MAINNET_MINT} \\
    bb --yes research --idea "Live mainnet smoke from Gecko"

After it returns, verify the receipt:

  bb economics <session_id> --verify

EOF
exit 0
