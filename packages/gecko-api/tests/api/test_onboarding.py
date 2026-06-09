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


def test_revoke_pulls_grant_and_blocks_agent(client):
    tok = _link(client)["session_token"]
    h = {"Authorization": f"Bearer {tok}"}
    client.post("/v1/onboarding/grant", headers=h)
    # user revokes the agent's access
    r = client.post("/v1/onboarding/revoke", headers=h)
    assert r.status_code == 200 and r.json()["revoked"] is True
    # the agent can no longer act on the user's behalf
    w = client.post("/v1/vault/withdraw", json={"amount": 10.0}, headers=h)
    assert w.status_code == 409  # RevokedError surfaces as conflict
    # but the user is still recognized — the wallet is theirs, not unlinked
    assert client.get("/v1/onboarding/me", headers=h).status_code == 200


def test_revoke_requires_session(client):
    assert client.post("/v1/onboarding/revoke").status_code == 401


class _FakeTable:
    """Records upsert calls so the test can assert the payload + on_conflict."""

    def __init__(self, recorder: list[dict]) -> None:
        self._recorder = recorder

    def upsert(self, payload, *, on_conflict=None, **_kw):
        self._recorder.append({"payload": payload, "on_conflict": on_conflict})
        return self

    def execute(self):  # mimic the supabase-py fluent .execute() terminal
        return self


class _FakeSupabase:
    """Minimal stand-in for the service-role Supabase client. Records every
    table().upsert() so the bind writer can be asserted without a network."""

    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.tables: list[str] = []

    def table(self, name: str) -> _FakeTable:
        self.tables.append(name)
        return _FakeTable(self.upserts)


def test_grant_binds_agent(client, monkeypatch):
    from gecko_api.routes import _bindings

    fake = _FakeSupabase()
    # Module seam: bind_user_agent resolves its client through _bindings._client().
    monkeypatch.setattr(_bindings, "_client", lambda: fake)

    tok = _link(client)["session_token"]
    user_id = _link(client)["user_id"]  # deterministic from WALLET
    r = client.post("/v1/onboarding/grant", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text

    assert fake.tables == ["user_agents"], fake.tables
    assert len(fake.upserts) == 1, fake.upserts
    call = fake.upserts[0]
    assert call["on_conflict"] == "agent_id"
    assert call["payload"]["user_id"] == user_id
    assert call["payload"]["agent_id"] == "hosted-setupc-001"


def test_grant_succeeds_even_if_bind_write_fails(client, monkeypatch):
    """The bind is an additive side-effect: a write failure must NOT 500 the
    grant. The grant succeeding is the user-facing contract."""
    from gecko_api.routes import _bindings

    def _boom():
        raise RuntimeError("supabase down")

    monkeypatch.setattr(_bindings, "_client", _boom)

    tok = _link(client)["session_token"]
    r = client.post("/v1/onboarding/grant", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    assert r.json()["revoked"] is False
