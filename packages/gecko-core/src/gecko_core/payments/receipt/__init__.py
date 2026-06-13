"""Decision Receipt — on-chain proof that an agent checked before it acted.

v0 (devnet, SPL Memo). Three pieces, each in its own module:

  * :mod:`gecko_core.payments.receipt.hash`   — canonical serialization +
    sha256. The load-bearing spec a third party must reproduce byte-for-byte.
  * :mod:`gecko_core.payments.receipt.anchor` — post one SPL Memo
    ``gecko:v1:{h}`` instruction in a separate devnet tx; return ``receipt_sig``.
  * :mod:`gecko_core.payments.receipt.verify` — re-hash the envelope, fetch
    the tx, find the memo, assert it carries ``gecko:v1:{h}`` and is signed by
    the published oracle pubkey.

Everything is gated behind ``GECKO_RECEIPT_ENABLED`` + an explicit devnet RPC;
default off. Mainnet / custom-program anchoring is v1 — out of scope here.

See ``private/strategy/2026-06-12-onchain-receipt-research.md``.
"""

from __future__ import annotations

from gecko_core.payments.receipt.hash import (
    BENTO_MEMO_PREFIX,
    RECEIPT_MEMO_PREFIX,
    bento_memo_string,
    canonical_envelope_json,
    memo_string,
    receipt_hash,
)

__all__ = [
    "BENTO_MEMO_PREFIX",
    "RECEIPT_MEMO_PREFIX",
    "bento_memo_string",
    "canonical_envelope_json",
    "memo_string",
    "receipt_hash",
]
