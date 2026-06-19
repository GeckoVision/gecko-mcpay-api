#!/usr/bin/env bash
# Launch-Firewall sandbox — local Solana test-validator + a mock token (step 6).
#
# Boots a throwaway solana-test-validator and mints an SPL token to a local
# keypair, giving a controllable Block-Zero environment with ZERO mainnet spend.
# This is the live-fidelity path: the monitor (step 6 wiring) subscribes to the
# validator's websocket (ws://127.0.0.1:8900) instead of recorded fixtures.
#
# Scope of THIS script: the deterministic, safe part — boot + mint. Seeding a
# real AMM pool + the on-chain attacker live in attack_bot.py's --onchain path,
# which is the remaining live-fidelity build (deliberately not auto-run; it
# deploys a program and signs transactions).
#
# Usage:
#   bash sandbox/launch_firewall/validator.sh            # boot + mint, stay up
#   bash sandbox/launch_firewall/validator.sh --smoke    # boot + mint + tear down
#
# Honesty: everything here is a LOCAL test validator (free, resettable). Nothing
# touches mainnet. Kill with Ctrl-C; the ledger lives under /tmp and is reset on
# each run.
set -euo pipefail

LEDGER="${GECKO_LF_LEDGER:-/tmp/gecko-lf-ledger}"
RPC_URL="http://127.0.0.1:8899"
SMOKE=0
[[ "${1:-}" == "--smoke" ]] && SMOKE=1

command -v solana-test-validator >/dev/null || { echo "solana-test-validator not on PATH"; exit 1; }
command -v spl-token >/dev/null || { echo "spl-token not on PATH"; exit 1; }

echo "==> booting solana-test-validator (reset ledger: $LEDGER)"
rm -rf "$LEDGER"
solana-test-validator --reset --quiet --ledger "$LEDGER" >/tmp/gecko-lf-validator.log 2>&1 &
VALIDATOR_PID=$!
trap 'kill "$VALIDATOR_PID" 2>/dev/null || true' EXIT

solana config set --url "$RPC_URL" >/dev/null

echo "==> waiting for RPC to come up"
for _ in $(seq 1 30); do
  if solana cluster-version >/dev/null 2>&1; then break; fi
  sleep 1
done
solana cluster-version

echo "==> funding a local keypair"
solana airdrop 100 >/dev/null

echo "==> creating the mock token (the 'victim' launch)"
MINT=$(spl-token create-token --decimals 6 | awk '/Creating token/ {print $3}')
echo "    mint: $MINT"
spl-token create-account "$MINT" >/dev/null
spl-token mint "$MINT" 1000000 >/dev/null
echo "    minted 1,000,000 to local account"
echo "$MINT" > /tmp/gecko-lf-mint.txt

echo
echo "==> ready. mint=$MINT  ws=ws://127.0.0.1:8900  rpc=$RPC_URL"
echo "    next: attack_bot.py --onchain (seed pool + drive the attack) — see README"

if [[ "$SMOKE" == "1" ]]; then
  echo "==> --smoke: tearing down"
  exit 0
fi

echo "==> validator running (Ctrl-C to stop)"
wait "$VALIDATOR_PID"
