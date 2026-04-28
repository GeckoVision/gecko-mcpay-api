"""Frames.ag bearer-token verification for /projects endpoints.

End users don't have Supabase creds; they hold a frames.ag apiToken in
``~/.agentwallet/config.json``. The CLI sends that token as a bearer
plus the username via headers; this module verifies the binding by
calling frames.ag's wallet balances endpoint and caches the result.

Verification model: verify-then-cache (per docs/auth-frames-bearer.md
section 1). Cache key is sha256(token); positive mappings only — never
poison-cache a 401.

Security notes:
    - Never log the apiToken or its hash. Log only the verified username.
    - Cache is in-process; OK for single-replica gecko-api today.
    - On frames.ag 5xx/timeout we 503 (don't extend TTL, don't grant access).
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Annotated

import httpx
from cachetools import TTLCache
from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)

# 10-minute positive cache. Sized for ~10k unique tokens — plenty of headroom
# for a single replica; per-instance memory is sub-megabyte.
_CACHE_MAXSIZE = 10_000
_CACHE_TTL_SECONDS = 600
_cache: TTLCache[str, str] = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=_CACHE_TTL_SECONDS)

# frames.ag base URL — overridable for tests/staging.
FRAMES_BASE_URL = os.environ.get("FRAMES_AG_BASE_URL", "https://frames.ag/api")
_FRAMES_TIMEOUT_S = 5.0


def _hash_token(token: str) -> str:
    """SHA256 of the bearer token. Never log the input or output."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="malformed Authorization header (expected 'Bearer <token>')",
        )
    return parts[1].strip()


async def _verify_with_frames(token: str, username: str) -> None:
    """Call frames.ag balances; 200 confirms token<->username binding.

    Raises 401 on 4xx, 503 on 5xx/timeout/transport errors.
    """
    url = f"{FRAMES_BASE_URL.rstrip('/')}/wallets/{username}/balances"
    try:
        async with httpx.AsyncClient(timeout=_FRAMES_TIMEOUT_S) as http:
            resp = await http.get(url, headers={"Authorization": f"Bearer {token}"})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.warning("frames.ag verification unreachable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="frames.ag verification unreachable",
        ) from exc

    if resp.status_code == 200:
        return
    if 400 <= resp.status_code < 500:
        # Token invalid, revoked, or doesn't bind to this username.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid frames.ag token",
        )
    # 5xx — frames is up but unhealthy. Don't grant access.
    logger.warning("frames.ag verification 5xx: %s", resp.status_code)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="frames.ag verification failed",
    )


async def verify_frames_token(
    authorization: Annotated[str | None, Header()] = None,
    x_frames_username: Annotated[str | None, Header(alias="X-Frames-Username")] = None,
) -> str:
    """FastAPI dependency. Returns the verified frames.ag username.

    Headers required:
        Authorization: Bearer <apiToken>
        X-Frames-Username: <username>

    On cache hit the cached username must equal the header — otherwise the
    same token is being presented for two identities, which is 401.
    """
    token = _parse_bearer(authorization)
    if not x_frames_username or not x_frames_username.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-Frames-Username header",
        )
    username = x_frames_username.strip()

    cache_key = _hash_token(token)
    cached = _cache.get(cache_key)
    if cached is not None:
        if cached != username:
            # Token rebound to a different identity — refuse.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="token does not bind to provided username",
            )
        return cached

    await _verify_with_frames(token, username)
    _cache[cache_key] = username
    logger.info("verified frames.ag user: %s", username)
    return username


def _reset_cache_for_tests() -> None:
    """Test-only — clear the in-process cache between cases."""
    _cache.clear()


__all__ = [
    "FRAMES_BASE_URL",
    "_reset_cache_for_tests",
    "verify_frames_token",
]
