"""V1 Phase 1 — Task 1.4 — session-scoped GET /v1/agent/state.

SECURITY-CRITICAL: this route must NEVER leak another user's agent. The ownership
gate is the explicit `.eq("user_id", caller_user_id)` filter on the `user_agents`
lookup — Mongo `agent_state` has no RLS, so that Supabase filter is THE gate.
`read_agent_state` must never be called with an agent_id that wasn't returned by a
`user_agents` row filtered on the caller's own user_id.

End-to-end via TestClient with the Supabase + Mongo seams monkeypatched — no live
Mongo, no live Supabase, no network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from gecko_api.routes._session import issue, user_id_for

WALLET = "USERaddr1111111111111111111111111111111111"
OTHER_WALLET = "OTHERaddr22222222222222222222222222222222"
AGENT_ID = "hosted-setupc-001"

# A raw state dict carrying BOTH user-safe fields and internal fields. The route
# must scope this down before it reaches the response.
_RAW_STATE = {
    "positions": [{"symbol": "WIF", "qty": 1.0}],
    "realized_pnl_today": 1.23,
    "updated_at": "2026-06-08T00:00:00Z",
    # internal — must NEVER surface:
    "spec": {"strategy": "setup_c", "secret_cohort": "x"},
    "total_spent_usd": 99.99,
}


class _FakeQuery:
    """Records the chained filter calls so the test can assert the ownership gate.

    Mimics the supabase-py fluent builder:
        table(t).select(...).eq("user_id", uid).is_("deleted_at", "null").maybe_single().execute()
    Returns the seeded row ONLY when the eq("user_id", ...) value matches the row
    owner — exactly the behavior the real Postgres filter gives.
    """

    def __init__(self, rows_by_user: dict[str, dict], recorder: dict) -> None:
        self._rows_by_user = rows_by_user
        self._recorder = recorder
        self._eq_user_id: str | None = None

    def select(self, *cols, **_kw):
        self._recorder["select"] = cols
        return self

    def eq(self, column, value):
        self._recorder.setdefault("eq", []).append((column, value))
        if column == "user_id":
            self._eq_user_id = value
        return self

    def is_(self, column, value):
        self._recorder.setdefault("is_", []).append((column, value))
        return self

    def maybe_single(self):
        self._recorder["maybe_single"] = True
        return self

    def execute(self):
        # The gate: a row is returned ONLY for its owner's user_id.
        row = self._rows_by_user.get(self._eq_user_id or "")
        return type("_Resp", (), {"data": row})()


class _FakeSupabase:
    def __init__(self, rows_by_user: dict[str, dict], recorder: dict) -> None:
        self._rows_by_user = rows_by_user
        self._recorder = recorder

    def table(self, name: str):
        self._recorder["table"] = name
        return _FakeQuery(self._rows_by_user, self._recorder)


@pytest.fixture
def recorder() -> dict:
    return {}


@pytest.fixture
def client(monkeypatch, recorder) -> TestClient:
    from gecko_api.routes import agent_state

    user_id = user_id_for(WALLET)
    rows_by_user = {
        user_id: {"agent_id": AGENT_ID, "strategy": "setup_c", "profile": "balanced"},
    }
    monkeypatch.setattr(agent_state, "_client", lambda: _FakeSupabase(rows_by_user, recorder))
    monkeypatch.setattr(agent_state, "read_agent_state", lambda _aid: dict(_RAW_STATE))

    from gecko_api.main import app

    return TestClient(app)


def _token(wallet: str = WALLET) -> str:
    return issue(user_id_for(wallet), wallet)


def _auth(wallet: str = WALLET) -> dict:
    return {"Authorization": f"Bearer {_token(wallet)}"}


def test_owner_happy_path_returns_scoped_state(client, recorder):
    r = client.get("/v1/agent/state", headers=_auth())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["agent_id"] == AGENT_ID
    assert j["strategy"] == "setup_c"
    assert j["profile"] == "balanced"
    assert j["updated_at"] == "2026-06-08T00:00:00Z"

    state = j["state"]
    # safe fields present
    assert state["positions"] == [{"symbol": "WIF", "qty": 1.0}]
    assert state["realized_pnl_today"] == 1.23
    # SCOPING PROOF: internal fields must NOT leak
    assert "spec" not in state
    assert "total_spent_usd" not in state

    # ownership gate assertions — the lookup MUST filter on the caller's user_id
    assert recorder["table"] == "user_agents"
    assert ("user_id", user_id_for(WALLET)) in recorder["eq"]
    assert ("deleted_at", "null") in recorder["is_"]


def test_no_binding_returns_404(client, monkeypatch):
    # Reseed with an EMPTY rows map so the lookup finds nothing for this user.
    from gecko_api.routes import agent_state

    rec: dict = {}
    monkeypatch.setattr(agent_state, "_client", lambda: _FakeSupabase({}, rec))
    r = client.get("/v1/agent/state", headers=_auth())
    assert r.status_code == 404
    assert "no agent for this user" in r.json()["detail"]


def test_tampered_token_returns_401(client):
    tok = _token()
    mid = len(tok) // 2
    flipped = "A" if tok[mid] != "A" else "B"
    tampered = tok[:mid] + flipped + tok[mid + 1 :]
    r = client.get("/v1/agent/state", headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401


def test_expired_token_returns_401(client, monkeypatch):
    # Issue with a past clock so the 7-day TTL is well expired by now.
    past = 1_000_000.0
    expired = issue(user_id_for(WALLET), WALLET, now=past)
    r = client.get("/v1/agent/state", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


def test_missing_token_returns_401(client):
    assert client.get("/v1/agent/state").status_code == 401


def test_binding_for_different_user_does_not_leak(client, monkeypatch, recorder):
    """LEAK GUARD: the only seeded row belongs to WALLET's user. A DIFFERENT
    caller's user_id must resolve to no row → 404, never 200, never the other
    user's state. read_agent_state must NOT be called."""
    from gecko_api.routes import agent_state

    called: list[str] = []

    def _spy_read(aid: str):
        called.append(aid)
        return dict(_RAW_STATE)

    monkeypatch.setattr(agent_state, "read_agent_state", _spy_read)

    # Caller is OTHER_WALLET; the seeded row is owned by WALLET's user only.
    r = client.get("/v1/agent/state", headers=_auth(OTHER_WALLET))
    assert r.status_code == 404
    assert "no agent for this user" in r.json()["detail"]
    # The ownership gate filtered on the OTHER user's id...
    assert ("user_id", user_id_for(OTHER_WALLET)) in recorder["eq"]
    # ...and read_agent_state was NEVER reached with any agent_id.
    assert called == []


def test_no_mongo_state_yet_returns_200_with_null_state(client, monkeypatch):
    """Binding exists but the agent has no Mongo state doc yet → 200 with
    state: None (not a 404, not a 500)."""
    from gecko_api.routes import agent_state

    monkeypatch.setattr(agent_state, "read_agent_state", lambda _aid: None)
    r = client.get("/v1/agent/state", headers=_auth())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["agent_id"] == AGENT_ID
    assert j["state"] is None
    assert j["updated_at"] is None
