"""On-chain attacker + organic control against the fork pool (real signed txs).

ETHICS / SCOPE — surfpool mainnet-FORK / localnet ONLY (127.0.0.1), our OWN mock
token from ``fork_pool.py``, funded throwaway test keypairs. This script signs and
submits REAL transactions, so it is hard-guarded to a local RPC and refuses any
non-local endpoint. It is defensive validation: it manufactures the exact attack
*footprint* so we can prove the firewall blocks it. NEVER a mainnet send, NEVER a
third-party token, NEVER for profit.

------------------------------------------------------------------------------
The minimal 4-in-1 attack (one run, all the launch-manipulation tells fused):

  1. SYBIL FUND   — 1 funder keypair airdrops + funds 4 fresh sniper keypairs.
                    (footprint: a common-funder graph; the wallets are seconds old.)
  2. SHARED ALT   — the funder creates ONE address-lookup-table and all 4 snipers
                    reference it in their buy txs (footprint: shared execution rig
                    — survives funder-graph laundering; the deep ALT-identity vein).
  3. SAME-SLOT CO-BUY + JITO TIP — the 4 snipers each send a buy of the pool inside
                    ONE ~400ms slot window; ONE of them adds a System transfer to a
                    real Jito tip account (footprint: a bundle submission — the
                    highest-precision "bot, not human" tell).
  4. WASH LOOP    — one sniper round-trips (buy↔sell) the pool several times with no
                    net fresh capital (footprint: recirculation, not discovery).
  5. DRAIN        — the snipers dump their base tokens back; reserves fall + early
                    buyers exit (footprint: the inflate-then-drain tail → lp_drain).

A "buy" here moves BOTH vault balances exactly as a real AMM swap would (which is
what the firewall reads): base token OUT of the base vault → sniper, quote token IN
from the sniper → quote vault (so spot = quote/base climbs), plus a small SOL spend
so the parsed-tx path marks the sniper as the buyer. A "sell"/"drain" reverses it
(base in, quote out → price falls).

The ORGANIC control: distinct payers, spread over many slots, fat-tailed sizes,
real two-sided flow, NO Jito tip, NO shared ALT, NO common funder. It must NOT
block.

------------------------------------------------------------------------------
Run (after run_fork_demo.sh + fork_pool.py):

    uv run python sandbox/launch_firewall/fork_attack.py --scenario attack
    uv run python sandbox/launch_firewall/fork_attack.py --scenario organic
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fork_pool import POOL_DESCRIPTOR_PATH, ForkPool
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed, Processed
from solana.rpc.types import TxOpts
from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message, MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction, VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    TransferParams,
    create_associated_token_account,
    get_associated_token_address,
    transfer,
)

# One of the 8 canonical Jito tip accounts (hotpath.jito.JITO_TIP_ACCOUNTS). On a
# fork there is no Jito block engine, so this is a real System transfer to a real
# tip-account pubkey — FOOTPRINT-faithful (the tx carries the tip transfer that
# tx_parser._tip_lamports reads), NOT placement-faithful (no bundle/auction).
JITO_TIP_ACCOUNT = Pubkey.from_string("96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5")
JITO_TIP_LAMPORTS = 2_000_000  # 0.002 SOL — a plausible launch-snipe tip

ALT_PROGRAM_ID = Pubkey.from_string("AddressLookupTab1e1111111111111111111111111")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")

N_SNIPERS = 4
LAMPORTS_PER_SOL = 1_000_000_000


@dataclass(slots=True)
class _Loaded:
    client: Client
    pool: ForkPool
    authority: Keypair


def _assert_local(rpc: str) -> None:
    if not (rpc.startswith("http://127.0.0.1") or rpc.startswith("http://localhost")):
        raise SystemExit(f"REFUSING to submit txs to non-local RPC {rpc!r}. Fork/localnet ONLY.")


def _load() -> _Loaded:
    if not POOL_DESCRIPTOR_PATH.exists():
        raise SystemExit(f"no pool descriptor at {POOL_DESCRIPTOR_PATH} — run fork_pool.py first.")
    raw = json.loads(POOL_DESCRIPTOR_PATH.read_text())
    pool = ForkPool(**raw)
    _assert_local(pool.rpc)
    authority = Keypair.from_bytes(bytes(pool.pool_authority_secret))
    return _Loaded(Client(pool.rpc, commitment=Confirmed), pool, authority)


def _airdrop(client: Client, pk: Pubkey, sol: float) -> None:
    sig = client.request_airdrop(pk, int(sol * LAMPORTS_PER_SOL)).value
    client.confirm_transaction(sig, commitment=Confirmed)


def _blockhash(client: Client) -> Hash:
    return client.get_latest_blockhash().value.blockhash


def _send_legacy(client: Client, ixs: list[Instruction], signers: list[Keypair]) -> Signature:
    bh = _blockhash(client)
    msg = Message.new_with_blockhash(ixs, signers[0].pubkey(), bh)
    tx = Transaction(signers, msg, bh)
    resp = client.send_transaction(
        tx, opts=TxOpts(skip_confirmation=False, preflight_commitment=Confirmed)
    )
    return resp.value


def _send_v0(
    client: Client,
    ixs: list[Instruction],
    signers: list[Keypair],
    alts: list[AddressLookupTableAccount],
    *,
    confirm: bool = True,
) -> Signature:
    """Submit a versioned (v0) tx that references the shared ALT(s)."""
    bh = _blockhash(client)
    msg = MessageV0.try_compile(signers[0].pubkey(), ixs, alts, bh)
    vtx = VersionedTransaction(msg, signers)
    resp = client.send_transaction(
        vtx,
        opts=TxOpts(
            skip_confirmation=not confirm,
            preflight_commitment=Processed,
            skip_preflight=True,  # co-buys race the slot; let them land together
        ),
    )
    return resp.value


# --------------------------------------------------------------------------- #
# Address-lookup-table program (hand-built — solders has no ix builder here)   #
# --------------------------------------------------------------------------- #


def _create_alt_ix(
    authority: Pubkey, payer: Pubkey, recent_slot: int
) -> tuple[Instruction, Pubkey]:
    """CreateLookupTable: derive the ALT PDA from (authority, recent_slot) + bump."""
    pda, bump = Pubkey.find_program_address(
        [bytes(authority), recent_slot.to_bytes(8, "little")], ALT_PROGRAM_ID
    )
    # bincode: u32 instruction index (0 = Create), u64 recent_slot, u8 bump_seed
    data = struct.pack("<IQB", 0, recent_slot, bump)
    metas = [
        AccountMeta(pubkey=pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=False),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(ALT_PROGRAM_ID, data, metas), pda


def _extend_alt_ix(
    table: Pubkey, authority: Pubkey, payer: Pubkey, addresses: list[Pubkey]
) -> Instruction:
    """ExtendLookupTable: append addresses to the table so a v0 tx can reference it."""
    # bincode: u32 instruction index (2 = Extend), u64 num_addresses, then 32B each
    data = struct.pack("<IQ", 2, len(addresses)) + b"".join(bytes(a) for a in addresses)
    metas = [
        AccountMeta(pubkey=table, is_signer=False, is_writable=True),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=False),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(ALT_PROGRAM_ID, data, metas)


def _build_shared_alt(
    client: Client, authority: Keypair, members: list[Pubkey]
) -> AddressLookupTableAccount:
    """Create + populate ONE ALT all snipers will reference (the shared rig)."""
    recent_slot = client.get_slot(commitment=Confirmed).value
    create_ix, table_addr = _create_alt_ix(authority.pubkey(), authority.pubkey(), recent_slot)
    _send_legacy(client, [create_ix], [authority])
    # Extend with the pool + vaults + members so a referencing tx resolves.
    extend_ix = _extend_alt_ix(table_addr, authority.pubkey(), authority.pubkey(), members)
    _send_legacy(client, [extend_ix], [authority])
    # warm-up: ALT must be active (one slot old) before a tx can use it
    time.sleep(1.0)
    return AddressLookupTableAccount(key=table_addr, addresses=members)


# --------------------------------------------------------------------------- #
# Swap primitives (a "swap" = move both vault balances)                        #
# --------------------------------------------------------------------------- #


def _ensure_atas(client: Client, payer: Keypair, owner: Pubkey, mints: list[Pubkey]) -> None:
    ixs: list[Instruction] = []
    for m in mints:
        ata = get_associated_token_address(owner, m)
        info = client.get_account_info(ata).value
        if info is None:
            ixs.append(create_associated_token_account(payer=payer.pubkey(), owner=owner, mint=m))
    if ixs:
        _send_legacy(client, ixs, [payer])


def _provision_buyer(ld: _Loaded, buyer: Keypair, *, quote_amount: int) -> None:
    """Give a buyer a base ATA + a quote ATA pre-funded with quote tokens.

    The pool authority is the quote-mint authority, so it can mint the quote the
    buyer will push into the quote vault on each buy. (On mainnet the buyer would
    wrap SOL; here we mint the wSOL stand-in — same vault footprint.)
    """
    from spl.token.instructions import MintToParams, mint_to

    base_mint = Pubkey.from_string(ld.pool.mint)
    quote_mint = Pubkey.from_string(ld.pool.quote_mint)
    _ensure_atas(ld.client, buyer, buyer.pubkey(), [base_mint, quote_mint])
    buyer_quote_ata = get_associated_token_address(buyer.pubkey(), quote_mint)
    _send_legacy(
        ld.client,
        [
            mint_to(
                MintToParams(
                    program_id=TOKEN_PROGRAM_ID,
                    mint=quote_mint,
                    dest=buyer_quote_ata,
                    mint_authority=ld.authority.pubkey(),
                    amount=quote_amount,
                )
            )
        ],
        [ld.authority],
    )


def _buy_ixs(ld: _Loaded, buyer: Keypair, base_amt: int, quote_amt: int) -> list[Instruction]:
    """A buy: base OUT base_vault→buyer; quote IN buyer→quote_vault; + SOL spend.

    THREE legs, each load-bearing for a different detector:

    * base-out  (SPL transfer, pool authority signs): the base vault FALLS — the
      reserve event ``swap_parser`` keys on (``side=buy``).
    * quote-in  (SPL transfer, buyer signs): the quote vault RISES, so the tracker's
      ``spot = quote/base`` CLIMBS on each buy — without this leg the price never
      rises and the wash F1 ``rising`` precondition can't fire on the fork. (This
      is the fork-fidelity fix: the quote vault must actually move.)
    * SOL spend (System transfer, buyer → pool authority): makes the buyer's signer
      SOL delta NEGATIVE so ``tx_parser`` marks ``is_buy`` on the parsed-tx path
      (the snipe gate's notion of a buy). Snipers' quote ATAs are pre-funded in the
      sybil-fund step.
    """
    base_mint = Pubkey.from_string(ld.pool.mint)
    quote_mint = Pubkey.from_string(ld.pool.quote_mint)
    buyer_base_ata = get_associated_token_address(buyer.pubkey(), base_mint)
    buyer_quote_ata = get_associated_token_address(buyer.pubkey(), quote_mint)
    base_out = transfer(
        TransferParams(
            program_id=TOKEN_PROGRAM_ID,
            source=Pubkey.from_string(ld.pool.base_vault),
            dest=buyer_base_ata,
            owner=ld.authority.pubkey(),
            amount=base_amt,
        )
    )
    quote_in = transfer(
        TransferParams(
            program_id=TOKEN_PROGRAM_ID,
            source=buyer_quote_ata,
            dest=Pubkey.from_string(ld.pool.quote_vault),
            owner=buyer.pubkey(),
            amount=quote_amt,
        )
    )
    from solders.system_program import TransferParams as SysTransfer
    from solders.system_program import transfer as sys_transfer

    sol_spend = sys_transfer(
        SysTransfer(
            from_pubkey=buyer.pubkey(),
            to_pubkey=ld.authority.pubkey(),
            lamports=max(1, quote_amt // 1000),  # small, just to flip is_buy
        )
    )
    return [base_out, quote_in, sol_spend]


def _jito_tip_ix(buyer: Keypair) -> Instruction:
    """A System transfer to a real Jito tip account (the bundle footprint)."""
    from solders.system_program import TransferParams as SysTransfer
    from solders.system_program import transfer as sys_transfer

    return sys_transfer(
        SysTransfer(
            from_pubkey=buyer.pubkey(),
            to_pubkey=JITO_TIP_ACCOUNT,
            lamports=JITO_TIP_LAMPORTS,
        )
    )


def _sell_ixs(ld: _Loaded, seller: Keypair, base_amt: int, quote_amt: int) -> list[Instruction]:
    """A sell/drain: base IN seller→base_vault, quote OUT quote_vault→seller.

    Base reserve RISES + quote reserve FALLS → ``spot = quote/base`` drops (the
    drain). The pool authority signs the quote-out leg (it owns the quote vault).
    """
    base_mint = Pubkey.from_string(ld.pool.mint)
    quote_mint = Pubkey.from_string(ld.pool.quote_mint)
    seller_base_ata = get_associated_token_address(seller.pubkey(), base_mint)
    seller_quote_ata = get_associated_token_address(seller.pubkey(), quote_mint)
    base_in = transfer(
        TransferParams(
            program_id=TOKEN_PROGRAM_ID,
            source=seller_base_ata,
            dest=Pubkey.from_string(ld.pool.base_vault),
            owner=seller.pubkey(),
            amount=base_amt,
        )
    )
    quote_out = transfer(
        TransferParams(
            program_id=TOKEN_PROGRAM_ID,
            source=Pubkey.from_string(ld.pool.quote_vault),
            dest=seller_quote_ata,
            owner=ld.authority.pubkey(),
            amount=quote_amt,
        )
    )
    return [base_in, quote_out]


# --------------------------------------------------------------------------- #
# The attack                                                                   #
# --------------------------------------------------------------------------- #


def run_attack(ld: _Loaded) -> dict[str, Any]:
    from solders.system_program import TransferParams as SysTransfer
    from solders.system_program import transfer as sys_transfer

    base_mint = Pubkey.from_string(ld.pool.mint)
    base_unit = 10**6  # launch-mint decimals
    quote_unit = 10**9  # quote-mint decimals

    # 1. SYBIL FUND — one funder funds 4 fresh snipers (the common-funder graph),
    #    and the authority pre-funds each sniper's quote ATA (the buy-side capital).
    funder = Keypair()
    _airdrop(ld.client, funder.pubkey(), 50.0)
    snipers = [Keypair() for _ in range(N_SNIPERS)]
    for s in snipers:
        # funder → sniper (one-hop funding; all from the SAME funder = sybil graph)
        _send_legacy(
            ld.client,
            [
                sys_transfer(
                    SysTransfer(
                        from_pubkey=funder.pubkey(),
                        to_pubkey=s.pubkey(),
                        lamports=2 * LAMPORTS_PER_SOL,
                    )
                )
            ],
            [funder],
        )
        _provision_buyer(ld, s, quote_amount=20 * quote_unit)

    # 2. SHARED ALT — the funder builds ONE table; all snipers reference it.
    members = [
        Pubkey.from_string(ld.pool.pool_addr),
        Pubkey.from_string(ld.pool.base_vault),
        Pubkey.from_string(ld.pool.quote_vault),
        *[s.pubkey() for s in snipers],
    ]
    shared_alt = _build_shared_alt(ld.client, funder, members)

    # 3. SAME-SLOT CO-BUY + JITO TIP — fire all 4 buys inside one slot window; one
    #    carries a Jito tip transfer. skip_preflight + no per-tx confirm so they
    #    race into the same ~400ms slot (default surfpool clock mode). Each buy is
    #    a v0 tx that references the shared ALT. Signers: sniper (fee payer) +
    #    pool authority (signs the base-out leg).
    co_buy_sigs: list[Signature] = []
    for i, s in enumerate(snipers):
        ixs = _buy_ixs(ld, s, base_amt=50_000 * base_unit, quote_amt=2 * quote_unit)
        if i == 0:
            ixs.append(_jito_tip_ix(s))  # one bundle in the cluster
        sig = _send_v0(ld.client, ixs, [s, ld.authority], [shared_alt], confirm=False)
        co_buy_sigs.append(sig)
    for sig in co_buy_sigs:
        ld.client.confirm_transaction(sig, commitment=Confirmed)

    # 4. WASH LOOP — one sniper round-trips buy↔sell with no net fresh capital.
    #    sell signers: washer (base-in) + authority (quote-out); buy: same pair.
    washer = snipers[1]
    for _ in range(4):
        _send_legacy(
            ld.client,
            _sell_ixs(ld, washer, base_amt=10_000 * base_unit, quote_amt=quote_unit // 2),
            [washer, ld.authority],
        )
        _send_legacy(
            ld.client,
            _buy_ixs(ld, washer, base_amt=10_000 * base_unit, quote_amt=quote_unit // 2),
            [washer, ld.authority],
        )

    # 5. DRAIN — all snipers dump their base back into the vault (reserves recover +
    #    early buyers exit → the inflate-then-drain tail; price falls).
    for s in snipers:
        ata = get_associated_token_address(s.pubkey(), base_mint)
        amt = int(ld.client.get_token_account_balance(ata).value.amount)
        if amt > 0:
            _send_legacy(
                ld.client,
                _sell_ixs(ld, s, base_amt=amt, quote_amt=quote_unit // 4),
                [s, ld.authority],
            )

    return {
        "scenario": "attack",
        "funder": str(funder.pubkey()),
        "snipers": [str(s.pubkey()) for s in snipers],
        "shared_alt": str(shared_alt.key),
        "co_buy_sigs": [str(sig) for sig in co_buy_sigs],
        "jito_tip_account": str(JITO_TIP_ACCOUNT),
    }


def run_organic(ld: _Loaded) -> dict[str, Any]:
    """Control: distinct payers, spread slots, fat-tailed sizes, two-sided, no
    tip, no shared ALT, no common funder. Must NOT block."""
    base_mint = Pubkey.from_string(ld.pool.mint)
    base_unit = 10**6
    quote_unit = 10**9
    buyers = [Keypair() for _ in range(8)]
    sizes = [0.2, 1.5, 0.3, 3.0, 0.5, 0.8, 2.2, 0.4]  # fat-tailed, organic spread
    for b, sz in zip(buyers, sizes, strict=True):
        _airdrop(ld.client, b.pubkey(), 10.0)  # each INDEPENDENTLY funded (no common funder)
        _provision_buyer(ld, b, quote_amount=int(sz * 5) * quote_unit)
        ixs = _buy_ixs(
            ld,
            b,
            base_amt=int(sz * 20_000) * base_unit,
            quote_amt=int(sz * quote_unit),
        )
        # plain legacy tx — NO ALT, NO tip; confirmed one at a time = spread slots
        _send_legacy(ld.client, ixs, [b, ld.authority])
        time.sleep(0.5)  # ensure distinct slots (no co-buy cluster)

    # genuine two-sided flow: some real sells (price discovery, not a drain)
    for b in buyers[:3]:
        ata = get_associated_token_address(b.pubkey(), base_mint)
        amt = int(int(ld.client.get_token_account_balance(ata).value.amount) * 0.3)  # partial
        if amt > 0:
            _send_legacy(
                ld.client,
                _sell_ixs(ld, b, base_amt=amt, quote_amt=quote_unit // 4),
                [b, ld.authority],
            )
        time.sleep(0.3)

    return {"scenario": "organic", "buyers": [str(b.pubkey()) for b in buyers]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch-Firewall on-chain attacker")
    ap.add_argument("--scenario", default="attack", choices=["attack", "organic"])
    args = ap.parse_args()
    try:
        ld = _load()
        report = run_attack(ld) if args.scenario == "attack" else run_organic(ld)
    except Exception as exc:
        print(f"  fork_attack FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    out = Path(f"/tmp/gecko-lf-fork-{args.scenario}.json")
    out.write_text(json.dumps(report, indent=2))
    print(f"\n  scenario={args.scenario} submitted; report -> {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
