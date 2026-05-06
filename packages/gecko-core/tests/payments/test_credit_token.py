"""Tests for the Ed25519-signed credit-pack JWT (S20-B4).

Covers:
  1. issue + verify roundtrip (fresh keypair).
  2. tampered signature → CreditTokenInvalid.
  3. expired token → CreditTokenExpired.
  4. key rotation: previous-key signature still verifies in grace.
  5. concurrent decrement: 2x 1M against 1.5M → one InsufficientCredit.
  6. re-issuing a credit pack for an existing jti is idempotent.
  7. revoked token raises CreditTokenRevoked on decrement.
  8. token shape — 3 base64url segments.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import pytest
from gecko_core.db import mongo_credit_tokens
from gecko_core.db.mongo_credit_tokens import (
    CreditTokenRevoked,
    InsufficientCredit,
    StubCreditTokenCollection,
    decrement_credit_pack,
    get_credit_pack,
    revoke_credit_pack,
    store_credit_pack,
)
from gecko_core.payments import credit_token
from gecko_core.payments.credit_token import (
    ENV_GRACE_DAYS,
    ENV_SIGNING_KEY,
    ENV_SIGNING_KEY_PREVIOUS,
    KEY_ROTATION_GRACE_DAYS,
    CreditTokenExpired,
    CreditTokenInvalid,
    generate_signing_key,
    issue_credit_token,
    verify_credit_token,
)


@pytest.fixture
def fresh_signing_env(monkeypatch: pytest.MonkeyPatch) -> bytes:
    priv, _ = generate_signing_key()
    monkeypatch.setenv(ENV_SIGNING_KEY, base64.b64encode(priv).decode("ascii"))
    monkeypatch.delenv(ENV_SIGNING_KEY_PREVIOUS, raising=False)
    monkeypatch.delenv(ENV_GRACE_DAYS, raising=False)
    credit_token._signing_key_cache_clear()
    yield priv
    credit_token._signing_key_cache_clear()


@pytest.fixture
def stub_collection(monkeypatch: pytest.MonkeyPatch) -> StubCreditTokenCollection:
    stub = StubCreditTokenCollection()
    monkeypatch.setattr(mongo_credit_tokens, "credit_tokens_collection", lambda: stub)
    return stub


# --------------------------------------------------------------------------
# 1. roundtrip
# --------------------------------------------------------------------------


def test_issue_and_verify_roundtrip(fresh_signing_env: bytes) -> None:
    token = issue_credit_token("solana:abc", "tx-1", "solana")
    claims = verify_credit_token(token)
    assert claims.sub == "solana:abc"
    assert claims.jti == "tx-1"
    assert claims.chain == "solana"
    assert claims.total_tokens == 1_500_000
    assert claims.exp > claims.iat


# --------------------------------------------------------------------------
# 2. tampered signature
# --------------------------------------------------------------------------


def test_tampered_signature_fails(fresh_signing_env: bytes) -> None:
    token = issue_credit_token("solana:abc", "tx-2", "solana")
    h, p, s = token.split(".")
    # Flip a byte of the signature segment
    bad_sig_bytes = bytearray(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
    bad_sig_bytes[0] ^= 0xFF
    bad_s = base64.urlsafe_b64encode(bytes(bad_sig_bytes)).rstrip(b"=").decode("ascii")
    tampered = f"{h}.{p}.{bad_s}"
    with pytest.raises(CreditTokenInvalid):
        verify_credit_token(tampered)


# --------------------------------------------------------------------------
# 3. expired
# --------------------------------------------------------------------------


def test_expired_token_raises(fresh_signing_env: bytes) -> None:
    token = issue_credit_token("solana:abc", "tx-3", "solana", ttl_days=1)
    # Re-verify with a `now` 2 days in the future
    future = int(time.time()) + 2 * 86_400
    with pytest.raises(CreditTokenExpired):
        verify_credit_token(token, now=future)


# --------------------------------------------------------------------------
# 4. key rotation grace
# --------------------------------------------------------------------------


def test_previous_key_within_grace_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    old_priv, _ = generate_signing_key()
    new_priv, _ = generate_signing_key()
    # Sign a token with the OLD key
    token = issue_credit_token(
        "solana:abc",
        "tx-4",
        "solana",
        signing_key=old_priv,
    )
    # Now flip env to NEW key as primary, OLD as previous
    monkeypatch.setenv(ENV_SIGNING_KEY, base64.b64encode(new_priv).decode("ascii"))
    monkeypatch.setenv(ENV_SIGNING_KEY_PREVIOUS, base64.b64encode(old_priv).decode("ascii"))
    monkeypatch.setenv(ENV_GRACE_DAYS, str(KEY_ROTATION_GRACE_DAYS))
    credit_token._signing_key_cache_clear()
    try:
        claims = verify_credit_token(token)
        assert claims.jti == "tx-4"
    finally:
        credit_token._signing_key_cache_clear()


def test_previous_key_outside_grace_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    old_priv, _ = generate_signing_key()
    new_priv, _ = generate_signing_key()
    token = issue_credit_token(
        "solana:abc",
        "tx-4b",
        "solana",
        signing_key=old_priv,
    )
    monkeypatch.setenv(ENV_SIGNING_KEY, base64.b64encode(new_priv).decode("ascii"))
    monkeypatch.setenv(ENV_SIGNING_KEY_PREVIOUS, base64.b64encode(old_priv).decode("ascii"))
    monkeypatch.setenv(ENV_GRACE_DAYS, "7")
    credit_token._signing_key_cache_clear()
    try:
        future = int(time.time()) + 30 * 86_400  # well past the 7d grace
        # exp default is 90 days so the token isn't expired — only the
        # rotation grace should reject it.
        with pytest.raises(CreditTokenInvalid, match="grace window"):
            verify_credit_token(token, now=future)
    finally:
        credit_token._signing_key_cache_clear()


# --------------------------------------------------------------------------
# 5. concurrent decrement atomicity
# --------------------------------------------------------------------------


def test_concurrent_decrement_atomic(
    fresh_signing_env: bytes, stub_collection: StubCreditTokenCollection
) -> None:
    # Seed a 1.5M pack
    token = issue_credit_token("solana:abc", "tx-5", "solana", total_tokens=1_500_000)
    claims = verify_credit_token(token)

    async def run() -> tuple[list[Any], list[Exception]]:
        await store_credit_pack(claims, total_tokens=1_500_000)
        # Two concurrent decrements of 1M each
        results = await asyncio.gather(
            decrement_credit_pack(claims.jti, 1_000_000),
            decrement_credit_pack(claims.jti, 1_000_000),
            return_exceptions=True,
        )
        oks = [r for r in results if not isinstance(r, Exception)]
        errs = [r for r in results if isinstance(r, Exception)]
        return oks, errs

    oks, errs = asyncio.run(run())
    assert len(oks) == 1
    assert oks[0] == 500_000
    assert len(errs) == 1
    assert isinstance(errs[0], InsufficientCredit)


# --------------------------------------------------------------------------
# 6. idempotent re-issue
# --------------------------------------------------------------------------


def test_reissue_credit_pack_is_noop(
    fresh_signing_env: bytes, stub_collection: StubCreditTokenCollection
) -> None:
    token = issue_credit_token("solana:abc", "tx-6", "solana", total_tokens=1_500_000)
    claims = verify_credit_token(token)

    async def run() -> dict[str, Any]:
        await store_credit_pack(claims, total_tokens=1_500_000)
        # Spend some
        await decrement_credit_pack(claims.jti, 100_000)
        # Re-store — must NOT reset the balance
        await store_credit_pack(claims, total_tokens=1_500_000)
        doc = await get_credit_pack(claims.jti)
        assert doc is not None
        return doc

    doc = asyncio.run(run())
    assert doc["tokens_remaining"] == 1_400_000


# --------------------------------------------------------------------------
# 7. revoked token
# --------------------------------------------------------------------------


def test_revoked_pack_rejects_decrement(
    fresh_signing_env: bytes, stub_collection: StubCreditTokenCollection
) -> None:
    token = issue_credit_token("solana:abc", "tx-7", "solana", total_tokens=1_500_000)
    claims = verify_credit_token(token)

    async def run() -> None:
        await store_credit_pack(claims, total_tokens=1_500_000)
        await revoke_credit_pack(claims.jti)
        with pytest.raises(CreditTokenRevoked):
            await decrement_credit_pack(claims.jti, 1_000)

    asyncio.run(run())


# --------------------------------------------------------------------------
# 8. JWT shape
# --------------------------------------------------------------------------


def test_token_is_three_base64url_segments(fresh_signing_env: bytes) -> None:
    token = issue_credit_token("solana:abc", "tx-8", "solana")
    parts = token.split(".")
    assert len(parts) == 3
    # Each segment must base64url-decode (with padding fixup)
    for seg in parts:
        pad = "=" * (-len(seg) % 4)
        base64.urlsafe_b64decode(seg + pad)
