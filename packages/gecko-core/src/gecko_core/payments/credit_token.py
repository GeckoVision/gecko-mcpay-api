"""Ed25519-signed JWT credit-pack token (S20-B4 / S20-B-CREDIT-PACK-01).

A ``credit-pack`` skill purchase ($10 → 1.5M output tokens) is a single
x402 settle that prepays a credit balance the holder can spend across
any other skill. This module owns the signing / verification of the
JWT that proves the holder paid for that balance.

Design choices:

* **`cryptography`** library, not ``pynacl``.
  ``cryptography`` is already a transitive dep (pulled by supabase,
  httpx[http2], etc. — see uv.lock) and provides
  ``Ed25519PrivateKey`` / ``Ed25519PublicKey`` directly. Adding
  ``pynacl`` would be a second native crypto dep for no functional gain.

* **Tokens-remaining lives in Mongo, not in the JWT.**
  The JWT carries the *immutable* ``total_tokens`` of the pack and the
  ``jti`` (settlement tx signature). The mutable balance is tracked
  server-side in ``credit_tokens`` so a forked / replayed JWT can never
  desync the balance. The JWT identifies *which* credit pack to spend
  against; Mongo enforces the spend limit atomically.

* **Lazy signing-key resolution via ``functools.lru_cache``.**
  Reads ``GECKO_CREDIT_SIGNING_KEY`` (base64-encoded 32-byte Ed25519
  raw private key) on first use. Tests can clear the cache
  (:func:`_signing_key_cache_clear`) between key rotations without
  re-importing the module.

* **JWT-compatible wire format**: ``base64url(header).base64url(payload).base64url(sig)``
  with ``alg=EdDSA``, ``typ=JWT``. We hand-roll the encode/decode (no
  ``PyJWT`` dep needed) because EdDSA in PyJWT pulls
  ``cryptography`` anyway and we already use it directly here.

Key-rotation procedure
----------------------

1. Generate a fresh keypair with :func:`generate_signing_key`.
2. Move the *current* private key from ``GECKO_CREDIT_SIGNING_KEY`` into
   the comma-separated list ``GECKO_CREDIT_SIGNING_KEY_PREVIOUS``.
3. Set ``GECKO_CREDIT_SIGNING_KEY`` to the fresh private key.
4. Restart gecko-api. New tokens are signed by the fresh key; tokens
   signed by the previous key continue to verify for
   ``KEY_ROTATION_GRACE_DAYS`` days (default 7, override via env
   ``GECKO_CREDIT_SIGNING_KEY_GRACE_DAYS``).
5. After the grace window, drop the old key from
   ``GECKO_CREDIT_SIGNING_KEY_PREVIOUS``.

Operationally: never put a private key in this file or in a commit.
The 32-byte raw seed is base64-encoded for env transport.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Final, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from pydantic import BaseModel, Field

ChainKind = Literal["solana", "base"]

DEFAULT_TTL_DAYS: Final[int] = 90
DEFAULT_TOTAL_TOKENS: Final[int] = 1_500_000
KEY_ROTATION_GRACE_DAYS: Final[int] = 7

ENV_SIGNING_KEY: Final[str] = "GECKO_CREDIT_SIGNING_KEY"
ENV_SIGNING_KEY_PREVIOUS: Final[str] = "GECKO_CREDIT_SIGNING_KEY_PREVIOUS"
ENV_GRACE_DAYS: Final[str] = "GECKO_CREDIT_SIGNING_KEY_GRACE_DAYS"


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class CreditTokenError(Exception):
    """Base class for credit-token errors."""


class CreditTokenInvalid(CreditTokenError):
    """Token shape was wrong, signature did not verify, or claims malformed."""


class CreditTokenExpired(CreditTokenError):
    """Token's ``exp`` is in the past (and outside any rotation grace)."""


class CreditTokenSigningKeyMissing(CreditTokenError):
    """``GECKO_CREDIT_SIGNING_KEY`` is unset / unparseable on issuance."""


# ---------------------------------------------------------------------------
# Claims model.
# ---------------------------------------------------------------------------


class CreditTokenClaims(BaseModel):
    """Pydantic model of the JWT payload.

    ``total_tokens`` is the immutable size of the pack (e.g. 1_500_000).
    The mutable ``tokens_remaining`` lives in Mongo, NOT here — see
    module docstring for rationale.
    """

    sub: str = Field(..., description="Chain-prefixed wallet, e.g. 'solana:8QURsr...'")
    jti: str = Field(..., description="Settlement tx signature; anti-replay key")
    iat: int = Field(..., description="Issued-at unix timestamp (seconds)")
    exp: int = Field(..., description="Expiry unix timestamp (seconds)")
    total_tokens: int = Field(..., ge=0, description="Immutable pack size at issuance")
    chain: ChainKind = Field(..., description="Chain the settlement landed on")
    version: int = Field(default=1, description="Schema version for future evolution")


# ---------------------------------------------------------------------------
# base64url helpers (JWT-compatible — no padding).
# ---------------------------------------------------------------------------


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


# ---------------------------------------------------------------------------
# Signing-key resolution. Lazy + lru_cached so tests can clear and re-read.
# ---------------------------------------------------------------------------


def _decode_b64_secret(value: str) -> bytes:
    """Decode a base64-encoded 32-byte Ed25519 raw seed.

    Accepts both standard and url-safe base64; trims whitespace; tolerates
    missing padding. Raises CreditTokenSigningKeyMissing on shape failure.
    """
    s = value.strip()
    try:
        # Try urlsafe first (more permissive); fall back to standard.
        try:
            raw = _b64url_decode(s)
        except Exception:
            raw = base64.b64decode(s + "=" * (-len(s) % 4))
    except Exception as exc:
        raise CreditTokenSigningKeyMissing(
            f"signing key not valid base64: {exc.__class__.__name__}"
        ) from exc
    if len(raw) != 32:
        raise CreditTokenSigningKeyMissing(f"signing key must decode to 32 bytes; got {len(raw)}")
    return raw


@lru_cache(maxsize=1)
def _resolve_signing_key() -> Ed25519PrivateKey:
    raw = os.environ.get(ENV_SIGNING_KEY, "").strip()
    if not raw:
        raise CreditTokenSigningKeyMissing(f"{ENV_SIGNING_KEY} unset — cannot sign credit tokens")
    seed = _decode_b64_secret(raw)
    return Ed25519PrivateKey.from_private_bytes(seed)


@lru_cache(maxsize=1)
def _resolve_previous_keys() -> tuple[Ed25519PublicKey, ...]:
    raw = os.environ.get(ENV_SIGNING_KEY_PREVIOUS, "").strip()
    if not raw:
        return ()
    out: list[Ed25519PublicKey] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            seed = _decode_b64_secret(chunk)
        except CreditTokenSigningKeyMissing:
            # A bad previous key is a config error but must not break verify
            # of currently-valid tokens. Skip silently — the doctor surfaces
            # the bad value separately.
            continue
        priv = Ed25519PrivateKey.from_private_bytes(seed)
        out.append(priv.public_key())
    return tuple(out)


def _signing_key_cache_clear() -> None:
    """Test-only — drops the lazy resolver caches. NOT exported."""
    _resolve_signing_key.cache_clear()
    _resolve_previous_keys.cache_clear()


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def generate_signing_key() -> tuple[bytes, bytes]:
    """Generate a fresh Ed25519 keypair.

    Returns ``(private_seed_bytes, public_key_bytes)`` — both 32 bytes.
    Use ``base64.b64encode`` / ``base64.urlsafe_b64encode`` to encode the
    private seed into ``GECKO_CREDIT_SIGNING_KEY``. See key-rotation
    procedure in module docstring.
    """
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    return priv_raw, pub_raw


def _sign_jwt(payload: dict[str, object], priv: Ed25519PrivateKey) -> str:
    header = {"alg": "EdDSA", "typ": "JWT"}
    h_seg = _b64url_encode(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    p_seg = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{h_seg}.{p_seg}".encode("ascii")
    sig = priv.sign(signing_input)
    s_seg = _b64url_encode(sig)
    return f"{h_seg}.{p_seg}.{s_seg}"


def issue_credit_token(
    wallet: str,
    jti: str,
    chain: ChainKind,
    *,
    total_tokens: int = DEFAULT_TOTAL_TOKENS,
    ttl_days: int = DEFAULT_TTL_DAYS,
    signing_key: bytes | None = None,
) -> str:
    """Issue a signed credit-pack JWT.

    Args:
        wallet: Chain-prefixed wallet ID, e.g. ``solana:8QURsr...``.
        jti: Settlement tx signature — used as the unique credit-pack ID.
        chain: ``solana`` or ``base``.
        total_tokens: Immutable pack size at issuance (default 1.5M).
        ttl_days: TTL from now (default 90).
        signing_key: 32-byte raw Ed25519 seed; if None, resolved from
            ``GECKO_CREDIT_SIGNING_KEY`` env (base64-encoded).

    Returns the compact JWT string.
    """
    if total_tokens < 0:
        raise ValueError(f"total_tokens must be >= 0; got {total_tokens}")
    if ttl_days <= 0:
        raise ValueError(f"ttl_days must be > 0; got {ttl_days}")

    priv: Ed25519PrivateKey
    if signing_key is not None:
        if len(signing_key) != 32:
            raise ValueError(f"signing_key must be 32 bytes; got {len(signing_key)}")
        priv = Ed25519PrivateKey.from_private_bytes(signing_key)
    else:
        priv = _resolve_signing_key()

    iat = int(time.time())
    exp = iat + ttl_days * 86_400
    claims = CreditTokenClaims(
        sub=wallet,
        jti=jti,
        iat=iat,
        exp=exp,
        total_tokens=total_tokens,
        chain=chain,
        version=1,
    )
    return _sign_jwt(claims.model_dump(), priv)


def _verify_with_key(token: str, public_key: Ed25519PublicKey) -> CreditTokenClaims:
    parts = token.split(".")
    if len(parts) != 3:
        raise CreditTokenInvalid(f"token must have 3 base64url segments; got {len(parts)}")
    h_seg, p_seg, s_seg = parts
    signing_input = f"{h_seg}.{p_seg}".encode("ascii")
    try:
        sig = _b64url_decode(s_seg)
    except Exception as exc:
        raise CreditTokenInvalid(f"signature segment not base64url: {exc}") from exc
    try:
        public_key.verify(sig, signing_input)
    except InvalidSignature as exc:
        raise CreditTokenInvalid("signature verification failed") from exc
    try:
        header = json.loads(_b64url_decode(h_seg))
    except Exception as exc:
        raise CreditTokenInvalid(f"header not valid JSON: {exc}") from exc
    if header.get("alg") != "EdDSA" or header.get("typ") != "JWT":
        raise CreditTokenInvalid(
            f"unexpected header: alg={header.get('alg')!r} typ={header.get('typ')!r}"
        )
    try:
        payload = json.loads(_b64url_decode(p_seg))
    except Exception as exc:
        raise CreditTokenInvalid(f"payload not valid JSON: {exc}") from exc
    try:
        return CreditTokenClaims.model_validate(payload)
    except Exception as exc:
        raise CreditTokenInvalid(f"claims invalid: {exc}") from exc


@dataclass(frozen=True)
class _VerificationOutcome:
    claims: CreditTokenClaims
    signed_by_previous: bool


def verify_credit_token(
    token: str,
    *,
    public_key: bytes | None = None,
    now: int | None = None,
) -> CreditTokenClaims:
    """Verify signature + expiry; return parsed claims on success.

    Tries the current signing key first, then any keys in
    ``GECKO_CREDIT_SIGNING_KEY_PREVIOUS`` (within
    ``KEY_ROTATION_GRACE_DAYS`` of issuance).

    Args:
        token: Compact JWT string.
        public_key: 32-byte Ed25519 public key. If None, derives from
            the current signing key (and falls back to the rotated set).
        now: Unix-time override (test seam).

    Raises:
        CreditTokenInvalid: signature failed against every accepted key,
            or token is malformed.
        CreditTokenExpired: token's ``exp`` is in the past.
    """
    candidates: list[tuple[Ed25519PublicKey, bool]] = []
    if public_key is not None:
        if len(public_key) != 32:
            raise ValueError(f"public_key must be 32 bytes; got {len(public_key)}")
        candidates.append((Ed25519PublicKey.from_public_bytes(public_key), False))
    else:
        with contextlib.suppress(CreditTokenSigningKeyMissing):
            candidates.append((_resolve_signing_key().public_key(), False))
        for prev in _resolve_previous_keys():
            candidates.append((prev, True))

    if not candidates:
        raise CreditTokenInvalid("no signing key configured for verification")

    last_err: Exception | None = None
    outcome: _VerificationOutcome | None = None
    for pubkey, is_previous in candidates:
        try:
            claims = _verify_with_key(token, pubkey)
        except CreditTokenInvalid as exc:
            last_err = exc
            continue
        outcome = _VerificationOutcome(claims=claims, signed_by_previous=is_previous)
        break

    if outcome is None:
        assert last_err is not None
        raise CreditTokenInvalid(str(last_err))

    current = now if now is not None else int(time.time())
    if outcome.claims.exp < current:
        raise CreditTokenExpired(f"token expired at {outcome.claims.exp}; now={current}")

    if outcome.signed_by_previous:
        # Within rotation grace window? We use iat-based grace so a token
        # signed long ago by the now-rotated key can't be re-validated
        # forever — only if it was issued within the grace window.
        try:
            grace_days = int(os.environ.get(ENV_GRACE_DAYS, str(KEY_ROTATION_GRACE_DAYS)))
        except ValueError:
            grace_days = KEY_ROTATION_GRACE_DAYS
        cutoff = current - grace_days * 86_400
        if outcome.claims.iat < cutoff:
            raise CreditTokenInvalid("token was signed by a rotated key outside the grace window")

    return outcome.claims


__all__ = [
    "DEFAULT_TOTAL_TOKENS",
    "DEFAULT_TTL_DAYS",
    "ENV_GRACE_DAYS",
    "ENV_SIGNING_KEY",
    "ENV_SIGNING_KEY_PREVIOUS",
    "KEY_ROTATION_GRACE_DAYS",
    "ChainKind",
    "CreditTokenClaims",
    "CreditTokenError",
    "CreditTokenExpired",
    "CreditTokenInvalid",
    "CreditTokenSigningKeyMissing",
    "generate_signing_key",
    "issue_credit_token",
    "verify_credit_token",
]
