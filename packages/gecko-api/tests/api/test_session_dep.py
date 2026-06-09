"""Shared session-verify dependency (Task 1.2) — direct unit tests.

The HMAC token logic was extracted out of onboarding into routes/_session.py so
the Phase 1 read route can reuse it. These tests pin the contract:

    1. issue(...) then verify_session_token(token) round-trips (user_id, wallet).
    2. a tampered token raises HTTPException(401).
    3. an expired token raises HTTPException(401).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from gecko_api.routes._session import (
    _secret,
    issue,
    session_from_header,
    verify_session_token,
)

USER = "u_deadbeefdeadbeef"
WALLET = "USERaddr1111111111111111111111111111111111"


def test_issue_then_verify_round_trips():
    tok = issue(USER, WALLET)
    assert verify_session_token(tok) == (USER, WALLET)


def test_tampered_token_raises_401():
    tok = issue(USER, WALLET)
    # Flip a character somewhere in the middle so it still base64-decodes-ish but
    # the signature (or payload) no longer matches.
    mid = len(tok) // 2
    flipped = "A" if tok[mid] != "A" else "B"
    tampered = tok[:mid] + flipped + tok[mid + 1 :]
    with pytest.raises(HTTPException) as exc:
        verify_session_token(tampered)
    assert exc.value.status_code == 401


def test_expired_token_raises_401():
    # Issue with a clock 30 days in the past so the 7-day TTL is well expired.
    past = 1_000_000.0
    tok = issue(USER, WALLET, now=past)
    with pytest.raises(HTTPException) as exc:
        verify_session_token(tok, now=past + 30 * 24 * 3600)
    assert exc.value.status_code == 401


def test_secret_dev_fallback_under_stub(monkeypatch):
    # The test suite runs under X402_MODE=stub. With no real secret set, _secret()
    # must return the dev fallback so local dev + CI keep working unchanged.
    monkeypatch.delenv("GECKO_SESSION_SECRET", raising=False)
    monkeypatch.delenv("EVENTS_SECRET", raising=False)
    monkeypatch.setenv("X402_MODE", "stub")
    assert _secret() == "dev-session-secret-not-for-production"


def test_secret_raises_in_production_when_unset(monkeypatch):
    # Mirror settings.py's prod-detection (mode != "stub"). With no real secret
    # set in a deployed env, refuse to issue forgeable tokens.
    monkeypatch.delenv("GECKO_SESSION_SECRET", raising=False)
    monkeypatch.delenv("EVENTS_SECRET", raising=False)
    monkeypatch.setenv("X402_MODE", "live")
    with pytest.raises(RuntimeError, match="must be set in production"):
        _secret()
    # issue(...) must surface the same refusal — it calls _secret() internally.
    with pytest.raises(RuntimeError, match="must be set in production"):
        issue(USER, WALLET)


def test_secret_uses_real_value_in_production_when_set(monkeypatch):
    # A real secret in a deployed env is fine — no raise.
    monkeypatch.setenv("X402_MODE", "live")
    monkeypatch.setenv("GECKO_SESSION_SECRET", "a-real-32-byte-production-secret!")
    assert _secret() == "a-real-32-byte-production-secret!"


def test_401_carries_www_authenticate_bearer():
    # Bearer 401s must advertise the scheme per the audited repo convention.
    with pytest.raises(HTTPException) as exc:
        session_from_header(None)
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}

    with pytest.raises(HTTPException) as exc:
        session_from_header("Basic abc")
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}

    # Tamper path through verify_session_token also carries the header.
    tok = issue(USER, WALLET)
    mid = len(tok) // 2
    flipped = "A" if tok[mid] != "A" else "B"
    with pytest.raises(HTTPException) as exc:
        verify_session_token(tok[:mid] + flipped + tok[mid + 1 :])
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}
