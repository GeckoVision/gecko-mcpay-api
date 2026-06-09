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

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from gecko_core.wallets import (
    WalletProvider,
    WalletProviderError,
    make_wallet_provider,
    user_scope,
)
from pydantic import BaseModel, ConfigDict, Field

# Session-token logic now lives in the shared `_session` module (Task 1.2 — the
# Phase 1 read route reuses it). Re-exported here under the historical private
# names so onboarding's routes (and any test monkeypatching) keep working
# unchanged. The token format is byte-identical to the pre-extraction format.
# `_verify` is re-exported for backward compat even though no route calls it
# directly — keep it so existing importers/monkeypatch parity survive the move.
from ._bindings import bind_user_agent
from ._session import issue as _issue
from ._session import session_from_header as _session
from ._session import user_id_for as _user_id_for
from ._session import verify_session_token as _verify  # noqa: F401

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["onboarding"])

# The Mongo GECKO_AGENT_ID this user's grant binds to. Single hosted Setup-C bot
# in V1 Phase 1; env-overridable for multi-agent later. Read at call time so a
# test/deploy override takes effect without reimporting the module.
_DEFAULT_AGENT_ID = "hosted-setupc-001"

_CFG = ConfigDict(extra="allow")

# Module-level provider seam. `make_wallet_provider()` is env-gated (Task 2.3):
# StubWalletProvider unless Privy is configured AND GECKO_WALLET_PROVIDER != "stub".
# With no Privy creds (dev/test/stub) this is byte-identical to the old hardcoded
# StubWalletProvider() and never touches the network at import time. Tests
# monkeypatch this attr with a fresh stub per test.
_provider: WalletProvider = make_wallet_provider()


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

    # Additive side-effect: write the user->agent ownership row so the Phase 1
    # read route can resolve this user's bot. A bind failure must NOT 500 the
    # grant — the scope is already granted and that's the user-facing contract.
    agent_id = os.environ.get("GECKO_DEFAULT_AGENT_ID", _DEFAULT_AGENT_ID)
    try:
        bind_user_agent(user_id, agent_id=agent_id)
    except Exception:
        logger.exception("bind_user_agent failed for user=%s agent=%s", user_id, agent_id)

    return {
        "user_id": user_id,
        "allowed_actions": sorted(scope.allowed_actions),
        "withdraw_allowlist": sorted(scope.withdraw_allowlist),
        "revoked": scope.revoked,
    }


class RevokeResponse(BaseModel):
    model_config = _CFG
    user_id: str
    revoked: bool


@router.post("/onboarding/revoke", response_model=RevokeResponse)
def revoke(authorization: Annotated[str | None, Header()] = None) -> dict:
    """Revoke the agent's grant. The user can pull the agent's trade access at
    ANY time — after this, execute/withdraw via the agent are refused until a new
    grant. The wallet (and its funds) remain entirely the user's; this only tears
    down Gecko's scoped permission. The cornerstone of the non-custodial promise."""
    user_id, _wallet = _session(authorization)
    _provider.revoke(user_id)
    return {"user_id": user_id, "revoked": True}


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
