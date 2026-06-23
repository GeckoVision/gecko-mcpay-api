#!/usr/bin/env bash
# Launch-Firewall mainnet-FORK attack→block demo — fork bring-up.
#
# ETHICS / SCOPE: surfpool mainnet-FORK or solana-test-validator localnet ONLY.
# Everything runs on 127.0.0.1 against OUR OWN mock token + funded throwaway
# keypairs. The fork's lamports/state are local; NOTHING is ever sent to mainnet,
# and we never touch a third-party token. This is defensive validation: we
# reproduce the attack footprint locally to PROVE the firewall blocks it.
#
# ---------------------------------------------------------------------------
# WHAT THIS SCRIPT DOES
#   `bash run_fork_demo.sh up`         — start surfpool as a mainnet fork (foreground)
#   `bash run_fork_demo.sh up-validator` — fallback: solana-test-validator (no Helius)
#   (the attack/observe/block steps run in a SECOND terminal — see "DEMO FLOW")
#
# This script does NOT auto-run the attack or leave a background validator: the
# live fork run is a deliberate, founder-executed step. `up` runs in the
# foreground; Ctrl-C stops it.
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
RPC_PORT="${GECKO_LF_RPC_PORT:-8899}"
WS_PORT="${GECKO_LF_WS_PORT:-8900}"
HOST="127.0.0.1"

# Load HELIUS_API_KEY from .env (the fork's mainnet datasource, $0 on the free tier).
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi

_have() { command -v "$1" >/dev/null 2>&1; }

cmd_up() {
  _have surfpool || { echo "surfpool not on PATH (expected: ~/.local/bin/surfpool)"; exit 1; }
  if [[ -z "${HELIUS_API_KEY:-}" || "${HELIUS_API_KEY}" == "__unset__" ]]; then
    echo "WARNING: HELIUS_API_KEY unset — surfpool can still fork via the public RPC,"
    echo "         but the free Helius endpoint is faster + higher-limit. Continuing."
    DATASOURCE="https://api.mainnet-beta.solana.com"
  else
    DATASOURCE="https://mainnet.helius-rpc.com/?api-key=${HELIUS_API_KEY}"
  fi

  echo "==> starting surfpool as a MAINNET FORK"
  echo "    rpc = http://${HOST}:${RPC_PORT}   ws = ws://${HOST}:${WS_PORT}"
  echo "    datasource (lazy clone, copy-on-read) = <helius mainnet> (key redacted)"
  echo
  # --slot-time 400  : realistic ~400ms slots so the same-slot co-buy is meaningful.
  # block-production-mode = clock (DEFAULT): time-based slots → multiple txs CAN land
  #   in ONE slot. Do NOT use `transaction` mode here — it lands one tx per block,
  #   which would destroy the same-slot co-buy footprint the firewall keys on.
  # --no-tui         : stream logs (CI/headless friendly) instead of the dashboard.
  exec surfpool start \
    --rpc-url "$DATASOURCE" \
    --host "$HOST" \
    --port "$RPC_PORT" \
    --ws-port "$WS_PORT" \
    --slot-time 400 \
    --no-tui
}

cmd_up_validator() {
  # Fallback when surfpool is unavailable. solana-test-validator is a clean
  # localnet (NOT a mainnet fork) — our mock token + vaults are created locally
  # anyway, so the footprint demo is identical; the only difference is no real
  # mainnet accounts are cloneable. SPL Token + ATA programs are built in.
  _have solana-test-validator || { echo "solana-test-validator not on PATH"; exit 1; }
  LEDGER="${GECKO_LF_LEDGER:-/tmp/gecko-lf-ledger}"
  echo "==> starting solana-test-validator (localnet fallback, NOT a fork)"
  echo "    rpc = http://${HOST}:${RPC_PORT}   ws = ws://${HOST}:${WS_PORT}"
  rm -rf "$LEDGER"
  # To additionally CLONE a real Raydium program + a live pool's accounts from
  # mainnet onto the localnet (program-faithful, optional), add e.g.:
  #   --url https://mainnet.helius-rpc.com/?api-key=$HELIUS_API_KEY \
  #   --clone CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C \
  #   --clone <pool> --clone <base_vault> --clone <quote_vault>
  # Our demo does NOT need this — the firewall reads vault FOOTPRINTS, not layouts.
  exec solana-test-validator \
    --reset --quiet --ledger "$LEDGER" \
    --rpc-port "$RPC_PORT" \
    --bind-address "$HOST"
}

cmd_help() {
  cat <<EOF
Launch-Firewall fork demo — bring-up

  bash run_fork_demo.sh up             start surfpool mainnet fork (foreground; Ctrl-C to stop)
  bash run_fork_demo.sh up-validator   fallback: solana-test-validator localnet
  bash run_fork_demo.sh help           this message

DEMO FLOW (two terminals):

  Terminal 1:  bash sandbox/launch_firewall/run_fork_demo.sh up

  Terminal 2 (once the fork is up):
     RPC=http://127.0.0.1:${RPC_PORT}
     uv run python sandbox/launch_firewall/fork_pool.py   --rpc \$RPC   # mock token + pool
     uv run python sandbox/launch_firewall/fork_adapter.py --seconds 120 &   # LIVE WIRE: watch
     uv run python sandbox/launch_firewall/fork_attack.py --scenario attack  # ATTACK
     # watch the adapter print gate=block; then assert:
     uv run python sandbox/launch_firewall/defense_harness.py --mode fork

  Control (must NOT block) — reset the pool, then:
     uv run python sandbox/launch_firewall/fork_pool.py   --rpc \$RPC
     uv run python sandbox/launch_firewall/fork_adapter.py --seconds 90 &
     uv run python sandbox/launch_firewall/fork_attack.py --scenario organic
     uv run python sandbox/launch_firewall/defense_harness.py --mode fork

FREE OFFLINE PROOF (no fork, runs now):
     uv run python sandbox/launch_firewall/defense_harness.py            # fixture 2x2
     uv run python sandbox/launch_firewall/fork_selftest.py              # adapter+harness logic
EOF
}

case "${1:-help}" in
  up)            cmd_up ;;
  up-validator)  cmd_up_validator ;;
  *)             cmd_help ;;
esac
