"""Phase 2 — kill-switch endpoints (per-agent + global).

In-memory fallback (no MONGODB_URI); module-level registry/state reset per test.
Mirrors test_agent_api.py's isolation fixture.
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
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()
    import agent_api
    from agent_orchestrator import AgentOrchestrator

    agent_api._registry = ast_.AgentRegistry(collection=None)
    agent_api._state = ast_.AgentStateStore(collection=None)
    agent_api._orch = AgentOrchestrator(registry=agent_api._registry)
    yield
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()


def _client():
    import agent_api
    from fastapi.testclient import TestClient

    return TestClient(agent_api.app)


def _spec(sid="trend_breakout"):
    return {
        "strategy_id": sid,
        "universe": ["BTC"],
        "venue": "okx_spot",
        "entry_gates": {},
        "exit": {"tp_pct": 1.0},
    }


def test_kill_agent_sets_policy_flag():
    c = _client()
    aid = c.post("/agents", json={"spec": _spec()}).json()["agent_id"]
    r = c.post(f"/agents/{aid}/kill")
    assert r.status_code == 200 and r.json()["kill_switch"] is True
    # the flag is persisted on the agent doc, readable by the running monolith
    assert c.get(f"/agents/{aid}").json()["agent"]["policy"]["kill_switch"] is True
    import agent_api

    assert agent_api._registry.is_killed(aid) is True


def test_kill_agent_disarm():
    c = _client()
    aid = c.post("/agents", json={"spec": _spec()}).json()["agent_id"]
    c.post(f"/agents/{aid}/kill")
    r = c.post(f"/agents/{aid}/kill?engaged=false")
    assert r.json()["kill_switch"] is False
    import agent_api

    assert agent_api._registry.is_killed(aid) is False


def test_kill_unknown_agent_404():
    assert _client().post("/agents/nope/kill").status_code == 404


def test_global_kill_roundtrip():
    c = _client()
    assert c.get("/kill").json()["kill_switch"] is False
    r = c.post("/kill")
    assert r.status_code == 200 and r.json()["kill_switch"] is True
    assert c.get("/kill").json()["kill_switch"] is True
    c.post("/kill?engaged=false")
    assert c.get("/kill").json()["kill_switch"] is False
