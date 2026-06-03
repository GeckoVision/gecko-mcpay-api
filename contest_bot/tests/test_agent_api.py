"""Phase-2 agent control plane — deploy / list / get / stop.

In-memory fallback (no MONGODB_URI in tests); the module-level registry/state are
reset per test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import agent_store as ast_  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # hermetic: never touch a real Mongo even if MONGODB_URI is in the env.
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()
    import agent_api

    agent_api._registry = ast_.AgentRegistry(collection=None)  # in-memory
    agent_api._state = ast_.AgentStateStore(collection=None)
    yield
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()


def _client():
    from fastapi.testclient import TestClient

    import agent_api

    return TestClient(agent_api.app)


def _spec(sid="trend_breakout"):
    return {"strategy_id": sid, "universe": ["BTC", "ETH"], "venue": "okx_spot",
            "entry_gates": {"churn_max": 3.0}, "exit": {"tp_pct": 1.0}}


def test_deploy_then_get_roundtrip():
    c = _client()
    r = c.post("/agents", json={"spec": _spec(), "user_id": "u1", "verdict": "PAPER ONLY"})
    assert r.status_code == 200
    aid = r.json()["agent_id"]
    assert r.json()["launch"].startswith("bash launch_agent.sh")
    g = c.get(f"/agents/{aid}")
    assert g.status_code == 200
    assert g.json()["agent"]["strategy_id"] == "trend_breakout"
    assert g.json()["state"] is None  # not running yet


def test_deploy_refused_on_reject_verdict():
    c = _client()
    r = c.post("/agents", json={"spec": _spec(), "verdict": "REJECT"})
    assert r.status_code == 409


def test_deploy_rejects_unknown_strategy():
    c = _client()
    r = c.post("/agents", json={"spec": _spec("nope")})
    assert r.status_code == 422


def test_get_unknown_agent_404():
    assert _client().get("/agents/doesnotexist").status_code == 404


def test_list_and_stop():
    c = _client()
    aid = c.post("/agents", json={"spec": _spec()}).json()["agent_id"]
    assert any(a["agent_id"] == aid for a in c.get("/agents").json()["agents"])
    s = c.post(f"/agents/{aid}/stop")
    assert s.status_code == 200 and s.json()["status"] == "stopped"
    assert c.get(f"/agents/{aid}").json()["agent"]["status"] == "stopped"


def test_stop_unknown_404():
    assert _client().post("/agents/nope/stop").status_code == 404


def test_get_agent_shows_state_mirror():
    c = _client()
    aid = c.post("/agents", json={"spec": _spec()}).json()["agent_id"]
    ast_.AgentStateStore().put_state(aid, {"poll_count": 9, "positions": []})
    g = c.get(f"/agents/{aid}")
    assert g.json()["state"]["state"]["poll_count"] == 9


def test_healthz():
    r = _client().get("/healthz")
    assert r.status_code == 200 and "n_agents" in r.json()
