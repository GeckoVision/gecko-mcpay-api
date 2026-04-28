"""HMAC-signed session-scoped events token for the Pro SSE endpoint.

Issued in the 202 response from POST /research/pro alongside the session_id.
Required to subscribe to GET /research/pro/{session_id}/events.

Format (urlsafe base64, no padding):
    base64(session_id "." expiry_unix "." hex_hmac_sha256)

Why HMAC and not JWT: zero deps, ~80 bytes, scoped to one resource, never
needs revocation (10-minute TTL means leaked tokens are short-lived). The
secret lives in `Settings.events_secret`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from uuid import UUID

logger = logging.getLogger(__name__)


_DEFAULT_TTL_SECONDS = 600  # 10 minutes — Pro debate runs in <2 min


class EventsTokenError(Exception):
    """Raised by `verify_token` for any rejection reason. Maps to 401."""


def issue_token(
    session_id: UUID,
    secret: str,
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> str:
    """Mint a token for `session_id` valid for `ttl_seconds`."""
    issued = int(now if now is not None else time.time())
    expiry = issued + ttl_seconds
    payload = f"{session_id}.{expiry}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}.{sig}".encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def verify_token(
    token: str,
    secret: str,
    expected_session_id: UUID,
    *,
    now: float | None = None,
) -> None:
    """Raise EventsTokenError on any failure. Returns None on success.

    Validates: shape, signature, expiry, session-id binding.
    """
    if not token:
        raise EventsTokenError("missing events token")
    # Re-pad for base64 decode.
    padding = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(token + padding).decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise EventsTokenError("malformed events token") from exc

    parts = raw.split(".")
    if len(parts) != 3:
        raise EventsTokenError("malformed events token")
    sid_str, expiry_str, sig = parts

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        f"{sid_str}.{expiry_str}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise EventsTokenError("invalid events token signature")

    try:
        expiry = int(expiry_str)
    except ValueError as exc:
        raise EventsTokenError("malformed expiry") from exc

    current = int(now if now is not None else time.time())
    if current >= expiry:
        raise EventsTokenError("events token expired")

    if sid_str != str(expected_session_id):
        raise EventsTokenError("token does not bind to this session")


__all__ = ["EventsTokenError", "issue_token", "verify_token"]
