"""V1 Phase A onboarding routes — end-to-end via TestClient (stub-backed).

Exercises the full non-custodial loop: link -> me -> grant -> withdraw, plus the
auth + invariant edges. No vendor, no network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from gecko_core.wallets import StubWalletProvider

WALLET = "USERaddr1111111111111111111111111111111111"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    # Fresh in-process provider per test so state doesn't leak between tests.
    from gecko_api.routes import onboarding

    monkeypatch.setattr(onboarding, "_provider", StubWalletProvider())
    from gecko_api.main import app

    return TestClient(app)


def _link(client: TestClient) -> dict:
    r = client.post("/v1/onboarding/link", json={"wallet_address": WALLET})
    assert r.status_code == 200, r.text
    return r.json()


def test_link_returns_session_and_user_owned_custody(client):
    j = _link(client)
    assert j["wallet_address"] == WALLET
    assert j["custody"] == "user-owned"
    assert j["session_token"] and j["user_id"].startswith("u_")


def test_me_requires_session(client):
    assert client.get("/v1/onboarding/me").status_code == 401


def test_me_with_session(client):
    tok = _link(client)["session_token"]
    j = client.get("/v1/onboarding/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert j["wallet_address"] == WALLET and j["custody"] == "user-owned"


def test_grant_is_trade_only_and_withdraw_allowlisted_to_user(client):
    tok = _link(client)["session_token"]
    j = client.post("/v1/onboarding/grant", headers={"Authorization": f"Bearer {tok}"}).json()
    # trade-only: includes kamino actions, excludes any arbitrary external send
    assert "kamino_deposit" in j["allowed_actions"]
    assert "kamino_withdraw" in j["allowed_actions"]
    assert all("send_to" not in a for a in j["allowed_actions"])
    # the only address funds may go to is the user's own wallet
    assert j["withdraw_allowlist"] == [WALLET]
    assert j["revoked"] is False


def test_withdraw_returns_funds_to_user_and_is_not_gated(client):
    tok = _link(client)["session_token"]
    client.post("/v1/onboarding/grant", headers={"Authorization": f"Bearer {tok}"})
    r = client.post(
        "/v1/vault/withdraw", json={"amount": 50.0}, headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 200, r.text
    j = r.json()
    # money-out always lands at the user's OWN address
    assert j["ok"] is True and j["to_address"] == WALLET and j["amount"] == 50.0


def test_withdraw_requires_session(client):
    assert client.post("/v1/vault/withdraw", json={"amount": 1.0}).status_code == 401


def test_bad_session_token_rejected(client):
    r = client.get("/v1/onboarding/me", headers={"Authorization": "Bearer not.a.real.token"})
    assert r.status_code == 401


def test_me_scope_null_before_grant_then_populated(client):
    tok = _link(client)["session_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/v1/onboarding/me", headers=h).json()["scope"] is None
    client.post("/v1/onboarding/grant", headers=h)
    s = client.get("/v1/onboarding/me", headers=h).json()["scope"]
    assert s["withdraw_allowlist"] == [WALLET]
    assert "kamino_deposit" in s["allowed_actions"] and s["revoked"] is False
