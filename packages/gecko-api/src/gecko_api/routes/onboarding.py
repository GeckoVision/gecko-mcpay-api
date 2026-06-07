"""V1 Phase A — non-custodial onboarding + withdraw routes.

Wires the gecko_core `WalletProvider` seam (non-custodial: the user owns their
keys; Gecko holds only a scoped, revocable, trade-only grant; withdrawals only
to the user's own address) to the control plane the app calls:

    POST /v1/onboarding/link   {wallet_address}  -> session token + linked wallet
    GET  /v1/onboarding/me     (Bearer)          -> user + wallet + custody
    POST /v1/onboarding/grant  (Bearer)          -> grant the trade-only scope
    POST /v1/vault/withdraw    (Bearer){amount}  -> unwind to the user's OWN wallet

Stub-backed today (`StubWalletProvider`) so the whole flow is reachable + tested
without a vendor; the live adapter (Privy / OKX / MagicBlock) swaps in behind the
same seam during the real deploy. Auth here is OUR app session (HMAC token) —
distinct from the OKX/Privy wallet auth the user holds. The provider state is
in-process (single-replica V1; the real adapter persists in the vendor).

`/vault/withdraw` is SACRED: bound to the user's own address and NEVER gated by
the kill-switch — money-out must always be available.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from gecko_core.wallets import (
    StubWalletProvider,
    WalletProvider,
    WalletProviderError,
    user_scope,
)
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["onboarding"])

_CFG = ConfigDict(extra="allow")
_SESSION_TTL = 7 * 24 * 3600  # 7 days
_PREFIX = "onboard"

# Module-level provider seam. Swap to a vendor adapter (Privy/OKX/MagicBlock)
# behind this name later; tests monkeypatch it with a fresh stub per test.
_provider: WalletProvider = StubWalletProvider()


def _secret() -> str:
    return (
        os.environ.get("GECKO_SESSION_SECRET")
        or os.environ.get("EVENTS_SECRET")
        or "dev-session-secret-not-for-production"
    )


def _user_id_for(wallet: str) -> str:
    """Deterministic user id from the wallet (V1: one wallet = one user)."""
    return "u_" + hashlib.sha256(wallet.encode()).hexdigest()[:16]


def _issue(user_id: str, wallet: str, *, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = f"{_PREFIX}.{user_id}.{wallet}.{issued + _SESSION_TTL}"
    sig = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).rstrip(b"=").decode("ascii")


def _verify(token: str, *, now: float | None = None) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
        prefix, user_id, wallet, exp_s, sig = raw.split(".")
    except Exception as e:
        raise HTTPException(401, "invalid session token") from e
    if prefix != _PREFIX:
        raise HTTPException(401, "wrong token type")
    payload = f"{prefix}.{user_id}.{wallet}.{exp_s}"
    expected = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(401, "bad session signature")
    if int(now if now is not None else time.time()) > int(exp_s):
        raise HTTPException(401, "session expired")
    return user_id, wallet


def _session(authorization: str | None) -> tuple[str, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer session token")
    return _verify(authorization.split(None, 1)[1].strip())


class LinkRequest(BaseModel):
    wallet_address: str = Field(..., min_length=32, max_length=64)


class LinkResponse(BaseModel):
    model_config = _CFG
    session_token: str
    user_id: str
    wallet_address: str
    custody: str


@router.post("/onboarding/link", response_model=LinkResponse)
def link(req: LinkRequest) -> dict:
    """Bind the user's OWN wallet to a Gecko session. Non-custodial — we record
    the public address only, never keys."""
    user_id = _user_id_for(req.wallet_address)
    linked = _provider.link(user_id, req.wallet_address)
    return {
        "session_token": _issue(user_id, req.wallet_address),
        "user_id": user_id,
        "wallet_address": linked.address,
        "custody": linked.custody,
    }


class MeScope(BaseModel):
    model_config = _CFG
    allowed_actions: list[str]
    withdraw_allowlist: list[str]
    revoked: bool


class MeResponse(BaseModel):
    model_config = _CFG
    user_id: str
    wallet_address: str
    custody: str = "user-owned"
    # The user's current grant (null when they haven't granted, or after revoke
    # leaves no live grant). Lets the app show "what can the agent do right now".
    scope: MeScope | None = None


@router.get("/onboarding/me", response_model=MeResponse)
def me(authorization: Annotated[str | None, Header()] = None) -> dict:
    user_id, wallet = _session(authorization)
    scope = _provider.scope_for(user_id)
    scope_out = (
        {
            "allowed_actions": sorted(scope.allowed_actions),
            "withdraw_allowlist": sorted(scope.withdraw_allowlist),
            "revoked": scope.revoked,
        }
        if scope is not None
        else None
    )
    return {
        "user_id": user_id,
        "wallet_address": wallet,
        "custody": "user-owned",
        "scope": scope_out,
    }


class GrantResponse(BaseModel):
    model_config = _CFG
    user_id: str
    allowed_actions: list[str]
    withdraw_allowlist: list[str]
    revoked: bool


@router.post("/onboarding/grant", response_model=GrantResponse)
def grant(authorization: Annotated[str | None, Header()] = None) -> dict:
    """Grant the agent the canonical trade-only scope: trade actions + withdraw
    ONLY to the user's own address. Revocable by the user at any time."""
    user_id, wallet = _session(authorization)
    try:
        scope = _provider.grant_scope(user_id, user_scope(wallet))
    except WalletProviderError as e:
        raise HTTPException(409, str(e)) from e
    return {
        "user_id": user_id,
        "allowed_actions": sorted(scope.allowed_actions),
        "withdraw_allowlist": sorted(scope.withdraw_allowlist),
        "revoked": scope.revoked,
    }


class WithdrawRequest(BaseModel):
    amount: float = Field(..., gt=0)


class WithdrawResponse(BaseModel):
    model_config = _CFG
    user_id: str
    amount: float
    to_address: str | None = None
    ok: bool
    note: str = ""


@router.post("/vault/withdraw", response_model=WithdrawResponse)
def withdraw(req: WithdrawRequest, authorization: Annotated[str | None, Header()] = None) -> dict:
    """Unwind/return funds to the user's OWN wallet. SACRED: bound to the user's
    address by the grant's allow-list, and intentionally NOT gated by the
    kill-switch — money-out must always be available."""
    user_id, wallet = _session(authorization)
    try:
        receipt = _provider.withdraw(user_id, req.amount, wallet)  # to_address = user's own
    except WalletProviderError as e:
        raise HTTPException(409, str(e)) from e
    return {
        "user_id": user_id,
        "amount": receipt.amount,
        "to_address": receipt.to_address,
        "ok": receipt.ok,
        "note": receipt.note,
    }
