"""Mock token + two-vault "pool" on the surfpool mainnet-FORK (or localnet).

ETHICS / SCOPE — surfpool mainnet-FORK or solana-test-validator localnet ONLY.
Our OWN throwaway mint + funded test keypairs. NEVER a mainnet send, NEVER a
third-party token. The RPC URL must be local (127.0.0.1); this module refuses to
run against any non-local endpoint (a hard guard, see ``_assert_local``).

------------------------------------------------------------------------------
Why a hand-built two-vault pool instead of deploying Raydium CPMM?

The Launch-Firewall detectors are *footprint* readers, not layout decoders:

* ``swap_parser.parse_vault_balance`` reads a standard ``jsonParsed`` SPL-token
  account's ``tokenAmount`` — it does NOT decode any AMM's pool layout. It infers
  a swap from the *change in a vault's balance*.
* ``tx_parser.parse_swap_tx`` reads ``accountKeys`` (signer), the slot,
  ``preBalances``/``postBalances`` (SOL delta), inner System transfers (the Jito
  tip), ``addressTableLookups`` (the ALT), and the instruction ``programId`` set.

So the minimal object that produces the EXACT observable footprint of a launch
pool is: a launch-token mint, two SPL token accounts acting as the base + quote
vaults, and "swaps" that move those vault balances. A buy = base token leaves the
base vault to the buyer + the buyer sends quote (wSOL) into the quote vault. That
is byte-for-byte what the detectors read off a real Raydium pool's vaults.

This is footprint-faithful. The one thing it is NOT is *program-faithful*: our
swaps are SPL ``transfer`` instructions, not a Raydium ``swap`` CPI. For the
firewall that is strictly MORE adversarial — a real Raydium swap routes through an
``established`` program id (no ``unknown_program`` tell), whereas our mock route
would look "unknown". The attack bot therefore does NOT lean on the
``unknown_program`` signal for its block; see ``attack_bot.py``.

------------------------------------------------------------------------------
Run (after ``run_fork_demo.sh`` has surfpool up on 127.0.0.1:8899):

    uv run python sandbox/launch_firewall/fork_pool.py --rpc http://127.0.0.1:8899

Writes the pool descriptor to ``/tmp/gecko-lf-fork-pool.json`` for the attack bot
and the adapter to read.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

# solders / solana-py are dev-only deps already present in the uv env.
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import (
    CreateAccountParams,
    create_account,
)
from solders.transaction import Transaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    InitializeMintParams,
    MintToParams,
    create_associated_token_account,
    get_associated_token_address,
    initialize_mint,
    mint_to,
)

POOL_DESCRIPTOR_PATH = Path("/tmp/gecko-lf-fork-pool.json")
KEYS_PATH = Path("/tmp/gecko-lf-fork-keys.json")
DEFAULT_RPC = "http://127.0.0.1:8899"
MINT_DECIMALS = 6
# How much base token to seed into the pool's base vault (the launch supply).
POOL_BASE_SUPPLY = 1_000_000


@dataclass(slots=True)
class ForkPool:
    """Everything the attack bot + adapter need to drive and observe the pool."""

    mint: str
    pool_addr: str  # the pool authority pubkey (a stand-in for the AMM pool id)
    base_vault: str  # SPL token account holding the launch token
    quote_vault: str  # SPL token account holding the quote (wSOL stand-in)
    quote_mint: str  # the quote-token mint (snipers' quote ATAs are derived from it)
    pool_authority_secret: list[int]  # keypair that signs vault-out transfers
    created_unix: int
    rpc: str


def _assert_local(rpc: str) -> None:
    """Hard ethics guard: refuse to touch anything that is not a local endpoint."""
    ok = rpc.startswith("http://127.0.0.1") or rpc.startswith("http://localhost")
    if not ok:
        raise SystemExit(
            f"REFUSING to run against non-local RPC {rpc!r}. The Launch-Firewall "
            "sandbox is surfpool-fork / localnet ONLY (127.0.0.1). Never mainnet."
        )


def _airdrop(client: Client, pubkey: Pubkey, sol: float) -> None:
    """Fund a keypair on the fork (free — fork lamports are not real)."""
    lamports = int(sol * 1_000_000_000)
    sig = client.request_airdrop(pubkey, lamports).value
    client.confirm_transaction(sig, commitment=Confirmed)


def _send(client: Client, ixs: list[Instruction], signers: list[Keypair]) -> None:
    """Build, sign, and confirm a legacy transaction from instructions."""
    bh = client.get_latest_blockhash().value.blockhash
    msg = Message.new_with_blockhash(ixs, signers[0].pubkey(), bh)
    tx = Transaction(signers, msg, bh)
    client.send_transaction(
        tx, opts=TxOpts(skip_confirmation=False, preflight_commitment=Confirmed)
    )


def build_fork_pool(rpc: str = DEFAULT_RPC) -> ForkPool:
    """Create the mock launch token + a two-vault pool on the fork.

    Steps (all on the local fork, $0):
      1. fund a payer/pool-authority keypair (airdrop),
      2. create + initialise the launch-token mint,
      3. create the base vault (ATA of the pool authority for the launch mint) and
         the quote vault (ATA of the pool authority for wSOL — represented here by
         a second throwaway mint so the fork needn't clone the real wSOL mint),
      4. mint the launch supply into the base vault.

    The vaults are ordinary SPL token accounts — exactly what the firewall reads.
    """
    _assert_local(rpc)
    client = Client(rpc, commitment=Confirmed)

    payer = Keypair()  # also the pool authority that owns both vaults
    _airdrop(client, payer.pubkey(), 50.0)

    # --- launch-token mint ------------------------------------------------- #
    mint_kp = Keypair()
    rent = client.get_minimum_balance_for_rent_exemption(82).value  # Mint = 82 bytes
    create_mint_ix = create_account(
        CreateAccountParams(
            from_pubkey=payer.pubkey(),
            to_pubkey=mint_kp.pubkey(),
            lamports=rent,
            space=82,
            owner=TOKEN_PROGRAM_ID,
        )
    )
    init_mint_ix = initialize_mint(
        InitializeMintParams(
            program_id=TOKEN_PROGRAM_ID,
            mint=mint_kp.pubkey(),
            decimals=MINT_DECIMALS,
            mint_authority=payer.pubkey(),
            freeze_authority=None,
        )
    )
    _send(client, [create_mint_ix, init_mint_ix], [payer, mint_kp])

    # --- quote mint (stand-in for wSOL so the fork needn't clone it) -------- #
    quote_mint_kp = Keypair()
    create_qmint_ix = create_account(
        CreateAccountParams(
            from_pubkey=payer.pubkey(),
            to_pubkey=quote_mint_kp.pubkey(),
            lamports=rent,
            space=82,
            owner=TOKEN_PROGRAM_ID,
        )
    )
    init_qmint_ix = initialize_mint(
        InitializeMintParams(
            program_id=TOKEN_PROGRAM_ID,
            mint=quote_mint_kp.pubkey(),
            decimals=9,
            mint_authority=payer.pubkey(),
            freeze_authority=None,
        )
    )
    _send(client, [create_qmint_ix, init_qmint_ix], [payer, quote_mint_kp])

    # --- the two pool vaults (ATAs owned by the pool authority) ------------- #
    base_vault = get_associated_token_address(payer.pubkey(), mint_kp.pubkey())
    quote_vault = get_associated_token_address(payer.pubkey(), quote_mint_kp.pubkey())
    create_base_ata = create_associated_token_account(
        payer=payer.pubkey(), owner=payer.pubkey(), mint=mint_kp.pubkey()
    )
    create_quote_ata = create_associated_token_account(
        payer=payer.pubkey(), owner=payer.pubkey(), mint=quote_mint_kp.pubkey()
    )
    _send(client, [create_base_ata, create_quote_ata], [payer])

    # --- seed the pool: mint launch supply into the base vault + some quote - #
    mint_base_ix = mint_to(
        MintToParams(
            program_id=TOKEN_PROGRAM_ID,
            mint=mint_kp.pubkey(),
            dest=base_vault,
            mint_authority=payer.pubkey(),
            amount=POOL_BASE_SUPPLY * (10**MINT_DECIMALS),
        )
    )
    # seed a small quote reserve so spot price = quote/base is well-defined
    mint_quote_ix = mint_to(
        MintToParams(
            program_id=TOKEN_PROGRAM_ID,
            mint=quote_mint_kp.pubkey(),
            dest=quote_vault,
            mint_authority=payer.pubkey(),
            amount=50 * (10**9),  # 50 "wSOL" of quote liquidity
        )
    )
    _send(client, [mint_base_ix, mint_quote_ix], [payer])

    fp = ForkPool(
        mint=str(mint_kp.pubkey()),
        pool_addr=str(payer.pubkey()),
        base_vault=str(base_vault),
        quote_vault=str(quote_vault),
        quote_mint=str(quote_mint_kp.pubkey()),
        pool_authority_secret=list(payer.to_bytes()),
        created_unix=int(time.time()),
        rpc=rpc,
    )
    POOL_DESCRIPTOR_PATH.write_text(json.dumps(asdict(fp), indent=2))
    return fp


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch-Firewall fork pool setup")
    ap.add_argument("--rpc", default=DEFAULT_RPC, help="local fork RPC (127.0.0.1 only)")
    args = ap.parse_args()
    try:
        fp = build_fork_pool(args.rpc)
    except Exception as exc:  # surface the cause; never leave the operator guessing
        print(f"  fork_pool setup FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("\n  mock launch pool created on the fork:\n")
    print(f"    mint        {fp.mint}")
    print(f"    pool_addr   {fp.pool_addr}")
    print(f"    base_vault  {fp.base_vault}")
    print(f"    quote_vault {fp.quote_vault}")
    print(f"\n  descriptor -> {POOL_DESCRIPTOR_PATH}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
