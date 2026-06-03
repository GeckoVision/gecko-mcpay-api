"""Phase-3 orchestrator — start/stop/cap/port-pool with an injected FakeSpawner.

No real OS processes are spawned. Hermetic (in-memory registry, MONGODB_URI delenv'd).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import agent_orchestrator as orch_mod  # noqa: E402
import agent_store as ast_  # noqa: E402
from agent_orchestrator import AgentOrchestrator  # noqa: E402
from agent_store import AgentRegistry  # noqa: E402


class FakeSpawner:
    def __init__(self) -> None:
        self.spawned: list[tuple] = []
        self._alive: dict[int, bool] = {}

    def spawn(self, cmd, cwd=None):
        h = object()
        self.spawned.append((cmd, cwd))
        self._alive[id(h)] = True
        return h

    def is_alive(self, h) -> bool:
        return self._alive.get(id(h), False)

    def kill(self, h) -> None:
        self._alive[id(h)] = False


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()
    yield
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()


def _spec(sid="trend_breakout"):
    return {"strategy_id": sid, "universe": ["BTC"], "venue": "okx_spot"}


def _orch(reg=None, sp=None):
    reg = reg or AgentRegistry(collection=None)
    return AgentOrchestrator(registry=reg, spawner=sp or FakeSpawner()), reg


def test_start_spawns_and_marks_running():
    sp = FakeSpawner()
    o, reg = _orch(sp=sp)
    aid = reg.deploy(_spec(), user_id="u1")
    r = o.start(aid)
    assert r["status"] == "running" and orch_mod.PORT_LO <= r["port"] <= orch_mod.PORT_HI
    assert len(sp.spawned) == 1 and aid in sp.spawned[0][0]  # launch_agent.sh <aid> in argv
    assert reg.get(aid)["status"] == "running"


def test_start_idempotent():
    o, reg = _orch()
    aid = reg.deploy(_spec(), user_id="u1")
    p1 = o.start(aid)["port"]
    again = o.start(aid)
    assert again.get("already") is True and again["port"] == p1


def test_distinct_ports():
    o, reg = _orch()
    a = reg.deploy(_spec(), user_id="u1")
    b = reg.deploy(_spec(), user_id="u1")
    assert o.start(a)["port"] != o.start(b)["port"]


def test_per_user_cap(monkeypatch):
    monkeypatch.setattr(orch_mod, "MAX_AGENTS_PER_USER", 2)
    o, reg = _orch()
    ids = [reg.deploy(_spec(), user_id="u1") for _ in range(3)]
    o.start(ids[0])
    o.start(ids[1])
    with pytest.raises(PermissionError):
        o.start(ids[2])  # 3rd running for u1 → over cap


def test_stop_kills_and_frees_port():
    sp = FakeSpawner()
    o, reg = _orch(sp=sp)
    aid = reg.deploy(_spec(), user_id="u1")
    h_port = o.start(aid)["port"]
    assert o.stop(aid) is True
    assert reg.get(aid)["status"] == "stopped"
    assert o.list_running() == []
    # port is freed → a new agent can reuse it
    bid = reg.deploy(_spec(), user_id="u1")
    assert o.start(bid)["port"] == h_port


def test_list_running_prunes_dead():
    sp = FakeSpawner()
    o, reg = _orch(sp=sp)
    aid = reg.deploy(_spec(), user_id="u1")
    o.start(aid)
    # simulate the process dying
    h = o._running[aid]["handle"]
    sp._alive[id(h)] = False
    assert o.list_running() == []
    assert reg.get(aid)["status"] == "stopped"


def test_start_unknown_raises():
    o, _ = _orch()
    with pytest.raises(KeyError):
        o.start("nope")
