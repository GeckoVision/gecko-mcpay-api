# Launch Firewall — Attack vs Defense sandbox

Free, mainnet-spend-free proving ground for the Launch Firewall. Two layers:

1. **Fixture sandbox** (runs now, no validator) — replays scripted manipulation
   attacks through the **real** detection engine (`gecko_core.trade_agent.hotpath`)
   and shows the verdict it would serve. Pattern B: falsify before any wire.
2. **Mainnet-FORK demo** (founder-run) — boots surfpool as a lazy mainnet fork,
   creates OUR OWN mock launch pool, runs a real on-chain attacker bot against it,
   and feeds the result through the **shipped** ingest stack to prove a live
   `block`. This is the Demo-Day "watch the bot lose" proof.

## ETHICS / SCOPE (non-negotiable)

surfpool mainnet-**FORK** or `solana-test-validator` localnet ONLY. Everything runs
on `127.0.0.1` against our OWN throwaway mint + funded test keypairs. The on-chain
scripts hard-refuse any non-local RPC. NEVER a mainnet send, NEVER a third-party
token, NEVER for profit. This is defensive validation only.

## Layout

| File | What |
|---|---|
| `scenarios.py` | Pure fixture generators (BrCA inflate-then-drain, organic fair launch). |
| `defense_harness.py` | The 2x2 PASS/FAIL assertion. `--mode fixture` (default) replays scenarios through the real engine; `--mode fork` asserts the LIVE verdict the adapter wrote. |
| `attack_bot.py` | Fixture-fed attack driver (latency / detection-in-N-events). |
| `latency_harness.py` | warm-serve / cold-overhead / detection latency. |
| **`run_fork_demo.sh`** | **Fork bring-up.** surfpool mainnet fork (primary) or solana-test-validator (fallback). Documents the exact command. |
| **`fork_pool.py`** | Creates the mock launch token + a two-vault pool on the fork. |
| **`fork_attack.py`** | The on-chain 4-in-1 attacker (sybil-fund → shared-ALT → same-slot co-buy + Jito tip → wash loop → drain) + an `organic` control. Emits real signed txs. |
| **`fork_adapter.py`** | The ONE real live wire: fork ws → `ParsedSwap`/`SwapEvent` → `LaunchMonitor`. Reuses the shipped `LaunchRunner`. |
| **`fork_selftest.py`** | Offline self-test — falsifies the adapter + harness logic with NO validator. Run this first. |

## Run the free offline proofs (no validator, $0)

```bash
uv run python sandbox/launch_firewall/defense_harness.py    # fixture 2x2: attack→block, organic→not
uv run python sandbox/launch_firewall/fork_selftest.py      # adapter parse + ingest→block + harness logic
```

## Run the mainnet-FORK demo (founder-executed)

`run_fork_demo.sh` starts the fork in the foreground (Ctrl-C to stop) — it does NOT
leave a background validator running. The attack/observe/block steps run in a
second terminal.

```bash
# Terminal 1 — bring up the fork (reads HELIUS_API_KEY from .env, $0 free tier):
bash sandbox/launch_firewall/run_fork_demo.sh up
#   exact command it runs:
#     surfpool start --rpc-url https://mainnet.helius-rpc.com/?api-key=<key> \
#       --host 127.0.0.1 --port 8899 --ws-port 8900 --slot-time 400 --no-tui
#   fallback (no Helius / no surfpool):
#     bash sandbox/launch_firewall/run_fork_demo.sh up-validator

# Terminal 2 — ATTACK → OBSERVE → BLOCK:
RPC=http://127.0.0.1:8899
uv run python sandbox/launch_firewall/fork_pool.py    --rpc $RPC          # mock token + pool
uv run python sandbox/launch_firewall/fork_adapter.py --seconds 120 &     # LIVE WIRE: watch the stream
uv run python sandbox/launch_firewall/fork_attack.py  --scenario attack   # drive the 4-in-1 attack
# the adapter prints gate=block live; then assert the 2x2:
uv run python sandbox/launch_firewall/defense_harness.py --mode fork       # PASS if attack→block

# Control (must NOT block) — fresh pool, then organic flow:
uv run python sandbox/launch_firewall/fork_pool.py    --rpc $RPC
uv run python sandbox/launch_firewall/fork_adapter.py --seconds 90 &
uv run python sandbox/launch_firewall/fork_attack.py  --scenario organic
uv run python sandbox/launch_firewall/defense_harness.py --mode fork
```

## How the attack footprint maps to the firewall signals

The detectors are footprint readers, not layout decoders — so a hand-built
two-vault pool is byte-for-byte what they consume off a real Raydium pool.

| Attack step | On-chain footprint | Signal that catches it | Data source |
|---|---|---|---|
| same-slot co-buy | 4 buyers, one slot | `same_slot_co_buy` | parsed tx slot + signer |
| Jito tip | System transfer → tip account | `jito_bundle_snipe` | inner System transfer (`tx_parser`) |
| sybil-fund | 4 fresh wallets, one funder | `fresh_wallet_swarm` | wallet age (see gap below) |
| shared ALT | all snipers reference one ALT | `shared_alt_rig` | `addressTableLookups` |
| inflate | one-sided buys, price climbing, tiny uniform notional | `thin_pool_buy_loop` (wash F1) | base-vault reserve deltas |
| drain | reserves recover after a dip + buyers exit | `lp_drain` | reserve series + `DrainWatcher` |

The `block` is a **fusion** — the snipe gate sums weights to `likely_sniped` /
`confirmed_wash` and `safety_gate` turns that into `block`. No single signal needs
to fire; that is the wedge (Jito sees one bundle, scanners see one snapshot — only
this fuses across wallets, slots, and pools).

## Honesty guardrails — VALIDATED vs NEEDS-LIVE-RUN

- **DEVNET-PROVEN-OFFLINE (validated now):** attacker-tx parsing against a
  recorded fork-shaped `getTransaction`; the full ingest→`block` path through the
  real engine; the 2x2 harness assertion logic. (`fork_selftest.py`, all PASS.)
- **DESIGNED, NEEDS-LIVE-RUN:** the actual signed-tx submission + the websocket
  round-trip on a running surfpool fork. The send/subscribe code is written and
  type-clean but has not executed against a live fork in this session — that is
  the deliberate founder-executed step (`run_fork_demo.sh`).

### Fidelity gaps (read before the demo)

1. **Wallet age is real-but-trivial on a fork.** The fresh-wallet swarm fires
   because the sniper keypairs ARE seconds old (just funded) — genuinely fresh.
   But the *prod* mechanism (a creation-slot lookup over mainnet history) is not
   what proves it on a fork; the swarm is fresh by construction. So the signal is
   footprint-real but the freshness *evidence* is a harness property, not the
   prod enrichment path. The organic control uses `wallet_age_s=None` (unknown)
   so it does not borrow the swarm tell.
2. **The Jito tip is footprint-faithful, NOT placement-faithful.** On a fork there
   is no block engine / auction. The tip is a real System transfer to a real Jito
   tip-account pubkey — exactly what `tx_parser._tip_lamports` reads — but no
   bundle is actually built or front-run-protected. The signal (`tip account paid
   = automated`) fires correctly; the MEV *placement* is simulated.
3. **The swap is an SPL transfer, not a Raydium CPI.** Footprint-faithful for the
   vault deltas the wash signals read; the `unknown_program` tell is therefore NOT
   relied on (our route looks unknown anyway — a real Raydium swap would not). The
   block stands on the other five signals.
4. **The claim is "detect-and-veto within N events of the pattern forming,"** not
   "block the tx in-block." The fail-OPEN rule holds: `unknown` is never reported
   as safe.

## CI gate

The shipped engine's gate is
`packages/gecko-core/tests/trade_agent/hotpath/test_launch_monitor.py`
(`test_brca_attack_reaches_cache_as_block`). The sandbox is the human-facing demo
of the same path; `fork_selftest.py` is the additional offline gate for the
fork-demo wiring.
