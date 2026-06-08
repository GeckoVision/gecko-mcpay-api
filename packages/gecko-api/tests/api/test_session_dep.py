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
from gecko_api.routes._session import issue, verify_session_token

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
