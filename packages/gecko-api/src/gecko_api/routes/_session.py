"""Shared app-session token (HMAC) + FastAPI verify dependency.

Extracted from `onboarding.py` so the Phase 1 read route (`GET /v1/agent/state`)
and the onboarding routes share ONE verification path. The token format is
byte-identical to onboarding's pre-extraction format: same prefix, same HMAC
(SHA-256 over `prefix.user_id.wallet.exp`), same urlsafe-base64 + strip-padding
encoding, same 7-day TTL. A token issued before this refactor still verifies.

Auth here is OUR app session (HMAC token) — distinct from the OKX/Privy wallet
auth the user holds.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException

_SESSION_TTL = 7 * 24 * 3600  # 7 days
_PREFIX = "onboard"

# Last-resort secret for local dev + CI ONLY. Never reachable in a deployed
# (non-stub) environment — `_secret()` raises before returning it there.
_DEV_FALLBACK_SECRET = "dev-session-secret-not-for-production"

# Bearer 401s carry this per the audited repo convention (main.py:805 exposes
# the header to browser clients; S22-MCP-HOST-06 verifies propagation).
_WWW_AUTH = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class SessionCtx:
    """The verified session principal: who the bearer token belongs to."""

    user_id: str
    wallet: str


def _secret() -> str:
    secret = os.environ.get("GECKO_SESSION_SECRET") or os.environ.get("EVENTS_SECRET")
    if secret:
        return secret
    # No real secret set. Session tokens authorize custody/withdraw routes and
    # this repo is PUBLIC — an unset secret in a deployed env means anyone can
    # forge tokens. Mirror settings.py's prod-detection (the `mode != "stub"`
    # guard at settings.py:210): X402_MODE defaults to "stub" for local dev + CI,
    # so the dev fallback stays reachable there. Evaluated at call time so tests
    # that never set the var keep hitting the fallback path.
    if os.environ.get("X402_MODE", "stub") != "stub":
        raise RuntimeError(
            "GECKO_SESSION_SECRET must be set in production — "
            "refusing to issue forgeable session tokens"
        )
    return _DEV_FALLBACK_SECRET


def user_id_for(wallet: str) -> str:
    """Deterministic user id from the wallet (V1: one wallet = one user)."""
    return "u_" + hashlib.sha256(wallet.encode()).hexdigest()[:16]


def issue(user_id: str, wallet: str, *, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = f"{_PREFIX}.{user_id}.{wallet}.{issued + _SESSION_TTL}"
    sig = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).rstrip(b"=").decode("ascii")


def verify_session_token(token: str, *, now: float | None = None) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
        prefix, user_id, wallet, exp_s, sig = raw.split(".")
    except Exception as e:
        raise HTTPException(401, "invalid session token", headers=_WWW_AUTH) from e
    if prefix != _PREFIX:
        raise HTTPException(401, "wrong token type", headers=_WWW_AUTH)
    payload = f"{prefix}.{user_id}.{wallet}.{exp_s}"
    expected = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(401, "bad session signature", headers=_WWW_AUTH)
    if int(now if now is not None else time.time()) > int(exp_s):
        raise HTTPException(401, "session expired", headers=_WWW_AUTH)
    return user_id, wallet


def session_from_header(authorization: str | None) -> tuple[str, str]:
    """Parse a `Bearer <token>` header and verify it. 401 on any failure."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer session token", headers=_WWW_AUTH)
    return verify_session_token(authorization.split(None, 1)[1].strip())


def require_session(
    authorization: Annotated[str | None, Header()] = None,
) -> SessionCtx:
    """FastAPI dependency: verify the Bearer session token, return the principal.

    Raises HTTPException(401) on missing header, bad scheme, tamper, or expiry.
    """
    user_id, wallet = session_from_header(authorization)
    return SessionCtx(user_id=user_id, wallet=wallet)
