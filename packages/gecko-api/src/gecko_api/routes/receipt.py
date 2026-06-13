"""Public Decision-Receipt verifier — ``POST /v1/receipt/verify``.

v0 (devnet, SPL Memo). A third party submits a verdict envelope + a
``receipt_sig`` and gets back whether the on-chain memo proves Gecko anchored
that exact decision. No payment, no session gate — verification is public and
trustless (the caller could run the same three RPC calls themselves; this route
is a convenience that pins the canonical hash spec + the published oracle key).

Thin transport: re-hash + memo check live in
``gecko_core.payments.receipt.verify``. This module parses input, resolves the
oracle pubkey + RPC, calls core, returns the result dict.

The oracle pubkey is resolved from ``GECKO_RECEIPT_ORACLE_PUBKEY`` (the public
key is safe to publish — it is the verification anchor). The RPC URL comes from
``GECKO_RECEIPT_RPC_URL`` (devnet). If either is unset the route returns 503 so
verification never silently passes against the wrong key.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from gecko_core.payments.receipt.verify import default_rpc_fetch, verify_receipt
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

router = APIRouter(prefix="/v1/receipt", tags=["receipt"])

# The oracle PUBLIC key is safe to publish — it is the verification anchor a
# third party checks the tx signer against. (The SECRET keypair lives only in
# GECKO_RECEIPT_ORACLE_KEYPAIR on the anchoring host.)
_ORACLE_PUBKEY_ENV = "GECKO_RECEIPT_ORACLE_PUBKEY"
_RPC_URL_ENV = "GECKO_RECEIPT_RPC_URL"

# Wide-open CORS — verification is public, like the verdict teaser.
_CORS_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
}


class _CitationIn(BaseModel):
    """Minimal citation shape the canonical hash reads (id/source/url)."""

    model_config = {"extra": "allow"}

    id: str | int | None = None
    source: str | None = None
    url: str | None = None


class _DissentIn(BaseModel):
    model_config = {"extra": "allow"}

    voice: str | None = None
    stance: str | None = None
    verbatim: str | None = None
    on_topic: str | None = None


class _EnvelopeIn(BaseModel):
    """The four spec fields the canonical hash commits to. Extra keys allowed
    (and ignored by the hash) so callers can post the full envelope verbatim."""

    model_config = {"extra": "allow"}

    verdict: str
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[_CitationIn] = Field(default_factory=list)
    dissent: list[_DissentIn] = Field(default_factory=list)


class VerifyRequest(BaseModel):
    """Request body for POST /v1/receipt/verify."""

    receipt_sig: str = Field(..., min_length=32, max_length=128)
    envelope: _EnvelopeIn


@router.post("/verify")
def verify(req: VerifyRequest) -> JSONResponse:
    """Re-hash the envelope, fetch the tx, assert the memo + oracle signer.

    503 if the oracle pubkey / RPC are not configured on this deploy (never
    pass verification against an unknown key). The on-chain fetch errors
    propagate verbatim as 502 — we do not catch-and-rephrase payment-path
    failures.
    """
    oracle_pubkey = os.environ.get(_ORACLE_PUBKEY_ENV, "").strip()
    rpc_url = os.environ.get(_RPC_URL_ENV, "").strip()
    if not oracle_pubkey or not rpc_url:
        raise HTTPException(
            status_code=503,
            detail="receipt verification not configured on this deploy "
            f"({_ORACLE_PUBKEY_ENV} / {_RPC_URL_ENV} unset)",
        )

    # ``envelope`` is a pydantic model carrying the four spec fields; the
    # canonical hash reads them by attribute, so model_dump round-trips cleanly.
    envelope: dict[str, Any] = req.envelope.model_dump()

    try:
        result = verify_receipt(
            envelope,
            receipt_sig=req.receipt_sig,
            oracle_pubkey=oracle_pubkey,
            fetch=default_rpc_fetch(rpc_url),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"rpc error: {exc}") from exc

    return JSONResponse(content=result.to_dict(), headers=_CORS_HEADERS)


__all__ = ["router"]
