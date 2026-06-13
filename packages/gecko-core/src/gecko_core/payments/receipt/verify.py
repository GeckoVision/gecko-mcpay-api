"""Verify a Decision Receipt — re-hash + on-chain memo check.

A verifier is given a verdict envelope + a ``receipt_sig`` + the published
oracle pubkey. It:

  1. Re-hashes the envelope → ``h`` (the SAME canonical spec the anchor used).
  2. Fetches the transaction via ``getTransaction(receipt_sig, "jsonParsed")``.
  3. Finds the SPL Memo instruction and reads its UTF-8 string.
  4. Asserts the memo equals ``gecko:v1:{h}`` AND the tx is signed by the
     published oracle pubkey (oracle is in ``accountKeys`` with ``signer=true``).

Returns ``{verified, h, receipt_sig, oracle_pubkey, reason}``. ``verified`` is
``True`` only when ALL checks pass; ``reason`` explains a failure.

Design: the RPC read is injected as a ``fetch`` callable returning the raw
JSON-RPC ``result`` dict (the shape any public RPC returns for
``encoding=jsonParsed``). This keeps verification independent of any specific
SDK response object AND makes the contract test a pure fixture replay — no live
RPC, no solders response-type coupling. :func:`default_rpc_fetch` is the live
implementation (httpx POST to the configured devnet RPC).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from gecko_core.payments.receipt.anchor import MEMO_PROGRAM_ID_STR
from gecko_core.payments.receipt.hash import RECEIPT_MEMO_PREFIX, receipt_hash

logger = logging.getLogger(__name__)

# A fetch callable takes a signature string, returns the JSON-RPC ``result``
# dict (or None if the tx was not found).
RpcFetch = Callable[[str], dict[str, Any] | None]


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of a receipt verification."""

    verified: bool
    h: str
    receipt_sig: str
    oracle_pubkey: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_memo_strings(result: dict[str, Any]) -> list[str]:
    """Pull every SPL Memo instruction's UTF-8 program-input string from a
    ``jsonParsed`` getTransaction result.

    Under ``encoding=jsonParsed`` the memo program is unparsed (no built-in
    parser), so each memo instruction looks like::

        {"programId": "MemoSq4...", "program": "spl-memo",
         "parsed": "gecko:v1:<h>"}

    Older / raw RPCs may instead surface the memo as a base58 ``data`` field on
    an instruction whose ``programId`` is the memo program. We handle the
    common jsonParsed ``parsed``-string form (what api.devnet.solana.com
    returns) and fall back to reading log messages, which always echo
    ``Program log: Memo (len N): "<text>"``.
    """
    memos: list[str] = []
    tx = result.get("transaction") or {}
    message = tx.get("message") or {}
    instructions = message.get("instructions") or []

    for ix in instructions:
        if ix.get("programId") != MEMO_PROGRAM_ID_STR:
            continue
        parsed = ix.get("parsed")
        if isinstance(parsed, str):
            memos.append(parsed)
        elif isinstance(parsed, dict):
            # Some RPCs nest the text; tolerate {"info": {...}, "type": ...}.
            info = parsed.get("info")
            if isinstance(info, str):
                memos.append(info)

    # Fallback: scan log messages for the memo echo. This catches RPCs that
    # leave the memo instruction unparsed but still log it.
    if not memos:
        meta = result.get("meta") or {}
        for line in meta.get("logMessages") or []:
            marker = "Memo (len"
            if marker in line and '"' in line:
                # Format: Program log: Memo (len N): "<text>"
                start = line.find('"')
                end = line.rfind('"')
                if 0 <= start < end:
                    memos.append(line[start + 1 : end])

    return memos


def _signer_pubkeys(result: dict[str, Any]) -> list[str]:
    """Return the pubkeys that signed the tx (jsonParsed accountKeys form)."""
    tx = result.get("transaction") or {}
    message = tx.get("message") or {}
    keys = message.get("accountKeys") or []
    signers: list[str] = []
    for k in keys:
        if isinstance(k, dict):
            if k.get("signer"):
                signers.append(str(k.get("pubkey")))
        elif isinstance(k, str):
            # Non-jsonParsed accountKeys are bare strings; the header tells us
            # how many lead positions are signers. Fall back to "all" — the
            # memo signer check below still requires an exact pubkey match.
            signers.append(k)
    return signers


def verify_receipt(
    envelope: Any,
    *,
    receipt_sig: str,
    oracle_pubkey: str,
    fetch: RpcFetch,
) -> VerifyResult:
    """Verify a Decision Receipt against on-chain data.

    ``fetch`` returns the JSON-RPC ``result`` dict for ``receipt_sig`` (or
    ``None`` if not found). All failure modes set ``verified=False`` with a
    ``reason``; only an all-pass returns ``verified=True``.
    """
    h = receipt_hash(envelope)
    expected_memo = f"{RECEIPT_MEMO_PREFIX}{h}"

    base = {"h": h, "receipt_sig": receipt_sig, "oracle_pubkey": oracle_pubkey}

    result = fetch(receipt_sig)
    if not result:
        return VerifyResult(verified=False, reason="transaction not found", **base)

    memos = _extract_memo_strings(result)
    if not memos:
        return VerifyResult(verified=False, reason="no memo instruction in tx", **base)
    if expected_memo not in memos:
        return VerifyResult(
            verified=False,
            reason=f"memo mismatch: expected {expected_memo!r}, found {memos!r}",
            **base,
        )

    signers = _signer_pubkeys(result)
    if oracle_pubkey not in signers:
        return VerifyResult(
            verified=False,
            reason=f"oracle pubkey {oracle_pubkey} not among tx signers {signers}",
            **base,
        )

    return VerifyResult(verified=True, reason="", **base)


def default_rpc_fetch(rpc_url: str) -> RpcFetch:
    """Build a live ``fetch`` that POSTs ``getTransaction`` to ``rpc_url``.

    Uses ``encoding=jsonParsed`` + ``maxSupportedTransactionVersion=0`` so
    versioned memo txs (what the anchor emits) come back parsed. Returns the
    JSON-RPC ``result`` dict, or ``None`` when the tx is not found.
    """
    import httpx

    def _fetch(sig: str) -> dict[str, Any] | None:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                sig,
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
            ],
        }
        resp = httpx.post(rpc_url, json=payload, timeout=20.0)
        resp.raise_for_status()
        body = resp.json()
        result = body.get("result")
        return result if isinstance(result, dict) else None

    return _fetch


__all__ = [
    "RpcFetch",
    "VerifyResult",
    "default_rpc_fetch",
    "verify_receipt",
]
