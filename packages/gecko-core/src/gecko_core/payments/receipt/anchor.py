"""Anchor a Decision Receipt — post ONE SPL Memo tx on Solana devnet.

Given a verdict envelope, compute ``h`` (see :mod:`.hash`), build a single
SPL Memo instruction carrying ``gecko:v1:{h}``, sign it with the devnet oracle
keypair, broadcast it as its own transaction, and return ``receipt_sig`` (the
base-58 transaction signature) + the published oracle pubkey.

This is a SEPARATE transaction from any x402 settlement (Coinbase's hosted
facilitator does not inject custom Solana memos — see the research doc §x402
interop). v0 scope: devnet only, ~5000-lamport fee paid from airdropped SOL,
NO real money. Gated behind :func:`gecko_core.payments.receipt.config.is_enabled`.

Lazy imports
------------
``solders`` / ``solana`` are imported INSIDE functions, not at module top, so
importing this module (and the verifier) never forces the Solana stack on code
paths that only need the pure hash helper.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from gecko_core.payments.receipt.config import ReceiptConfig, load_config
from gecko_core.payments.receipt.hash import memo_string, receipt_hash

if TYPE_CHECKING:  # pragma: no cover - typing only
    from solders.keypair import Keypair

logger = logging.getLogger(__name__)

# Memo program — the canonical SPL Memo v2 program id. Hard-coded (it is a
# fixed network constant) and asserted against spl.memo's constant at anchor
# time so a dependency bump can't silently retarget us.
MEMO_PROGRAM_ID_STR = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"

# Minimum balance (lamports) we want before attempting an anchor. A memo tx
# costs ~5000 lamports; we keep a small buffer. 0.001 SOL is plenty.
_MIN_BALANCE_LAMPORTS = 1_000_000
_AIRDROP_LAMPORTS = 1_000_000_000  # 1 SOL devnet airdrop when under the floor.


@dataclass(frozen=True)
class ReceiptAnchor:
    """Result of anchoring a Decision Receipt on devnet."""

    h: str
    receipt_sig: str
    oracle_pubkey: str
    memo: str
    cluster: str = "devnet"


def load_oracle_keypair(path: str | Any) -> Keypair:
    """Load the devnet oracle keypair from a Solana-CLI-format JSON file.

    The file is a JSON array of 64 ints (the secret key bytes). NEVER log its
    contents. Raises if the file is missing or malformed.
    """
    from pathlib import Path

    from solders.keypair import Keypair

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"oracle keypair file not found: {p}")
    return Keypair.from_json(p.read_text())


def _ensure_funded(client: Any, pubkey: Any) -> None:
    """Airdrop devnet SOL if the oracle is below the fee floor. Devnet only."""
    from solana.rpc.commitment import Confirmed

    balance = client.get_balance(pubkey).value
    if balance >= _MIN_BALANCE_LAMPORTS:
        logger.debug("oracle balance sufficient: %s lamports", balance)
        return
    logger.info("oracle below floor (%s lamports); requesting devnet airdrop", balance)
    sig = client.request_airdrop(pubkey, _AIRDROP_LAMPORTS).value
    client.confirm_transaction(sig, commitment=Confirmed)


def anchor_receipt(
    envelope: Any,
    *,
    config: ReceiptConfig | None = None,
    env: Mapping[str, str] | None = None,
) -> ReceiptAnchor:
    """Anchor ``envelope`` as a Decision Receipt and return the signature.

    Raises :class:`ReceiptDisabled` if the feature gate is off, and
    :class:`ReceiptConfigError` on bad config. Network/RPC errors from the
    Solana client propagate verbatim (we never catch-and-rephrase payment-path
    failures).
    """
    from solana.rpc.api import Client
    from solana.rpc.commitment import Confirmed
    from solana.rpc.types import TxOpts
    from solders.message import MessageV0
    from solders.pubkey import Pubkey
    from solders.transaction import VersionedTransaction
    from spl.memo.constants import MEMO_PROGRAM_ID
    from spl.memo.instructions import MemoParams, create_memo

    # Defensive: our hard-coded id must match the installed spl.memo constant.
    if str(MEMO_PROGRAM_ID) != MEMO_PROGRAM_ID_STR:
        raise RuntimeError(
            f"spl.memo MEMO_PROGRAM_ID {MEMO_PROGRAM_ID} != expected "
            f"{MEMO_PROGRAM_ID_STR}; refusing to anchor"
        )

    cfg = config or load_config(env)  # raises ReceiptDisabled if gate off
    h = receipt_hash(envelope)
    memo = memo_string(h)

    oracle = load_oracle_keypair(cfg.oracle_keypair_path)
    oracle_pubkey = oracle.pubkey()

    client = Client(cfg.rpc_url)
    _ensure_funded(client, oracle_pubkey)

    memo_ix = create_memo(
        MemoParams(
            program_id=Pubkey.from_string(MEMO_PROGRAM_ID_STR),
            signer=oracle_pubkey,
            message=memo.encode("utf-8"),
        )
    )

    blockhash = client.get_latest_blockhash().value.blockhash
    message = MessageV0.try_compile(
        payer=oracle_pubkey,
        instructions=[memo_ix],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )
    tx = VersionedTransaction(message, [oracle])

    resp = client.send_transaction(
        tx, opts=TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
    )
    receipt_sig = str(resp.value)
    client.confirm_transaction(resp.value, commitment=Confirmed)

    logger.info("anchored receipt h=%s sig=%s", h, receipt_sig)
    return ReceiptAnchor(
        h=h,
        receipt_sig=receipt_sig,
        oracle_pubkey=str(oracle_pubkey),
        memo=memo,
        cluster="devnet",
    )


__all__ = [
    "MEMO_PROGRAM_ID_STR",
    "ReceiptAnchor",
    "anchor_receipt",
    "load_oracle_keypair",
]
