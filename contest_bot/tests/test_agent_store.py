"""Phase-2 agent store — registry + state mirror + Mongo state store.

Uses mongomock (a pymongo drop-in) for the Mongo path and the in-memory fallback
for the no-Mongo path. No live Mongo required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import mongomock
import pytest

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import agent_store as ast_  # noqa: E402
from bot_state import BotState  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # hermetic: the `collection=None` tests use in-memory, never a real Mongo,
    # even if MONGODB_URI is in the env.
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()
    yield
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()


def _col(name="agents"):
    return mongomock.MongoClient().db[name]


def _spec(sid="trend_breakout"):
    return {"strategy_id": sid, "version": "v0", "universe": ["BTC", "ETH"], "venue": "okx_spot",
            "entry_gates": {"adx_min": 22.0, "churn_max": 3.0}, "exit": {"tp_pct": 1.0}}


# ── registry (mongomock) ─────────────────────────────────────────────
def test_deploy_and_get_roundtrip():
    reg = ast_.AgentRegistry(collection=_col())
    aid = reg.deploy(_spec(), user_id="u1", verdict="PAPER ONLY")
    doc = reg.get(aid)
    assert doc["strategy_id"] == "trend_breakout" and doc["status"] == "deployed"
    assert doc["spec"]["entry_gates"]["churn_max"] == 3.0 and doc["user_id"] == "u1"


def test_deploy_refuses_reject_verdict():
    reg = ast_.AgentRegistry(collection=_col())
    with pytest.raises(ValueError):
        reg.deploy(_spec(), verdict="REJECT")


def test_list_and_set_status():
    reg = ast_.AgentRegistry(collection=_col())
    a = reg.deploy(_spec(), user_id="u1")
    reg.deploy(_spec("mean_reversion"), user_id="u2")
    assert len(reg.list_agents()) == 2
    assert len(reg.list_agents(user_id="u1")) == 1
    assert reg.set_status(a, "stopped") is True
    assert reg.get(a)["status"] == "stopped"
    assert reg.set_status("nope", "stopped") is False


# ── in-memory fallback (no collection) ───────────────────────────────
def test_registry_in_memory_fallback():
    reg = ast_.AgentRegistry(collection=None)  # no Mongo → in-memory
    aid = reg.deploy(_spec(), user_id="local")
    assert reg.get(aid)["strategy_id"] == "trend_breakout"
    assert reg.list_agents()[0]["agent_id"] == aid


# ── state mirror ─────────────────────────────────────────────────────
def test_state_store_put_get():
    store = ast_.AgentStateStore(collection=_col("agent_state"))
    store.put_state("a1", {"positions": [], "poll_count": 5})
    got = store.get_state("a1")
    assert got["state"]["poll_count"] == 5 and got["agent_id"] == "a1"


# ── MongoBotStateStore drop-in ───────────────────────────────────────
def test_mongo_bot_state_store_roundtrip():
    col = _col("agent_state")
    store = ast_.MongoBotStateStore("a1", collection=col)
    assert store.load().poll_count == 0  # empty → fresh BotState
    store.save(BotState(poll_count=7, daily_trades=2, realized_pnl_today=1.5))
    loaded = store.load()
    assert loaded.poll_count == 7 and loaded.daily_trades == 2 and loaded.realized_pnl_today == 1.5


def test_mongo_bot_state_store_corrupt_doc_starts_clean():
    col = _col("agent_state")
    col.insert_one({"agent_id": "a1", "state": {"poll_count": "not-an-int-shape!!", "positions": 5}})
    store = ast_.MongoBotStateStore("a1", collection=col)
    # invalid shape → clean BotState (never raises into the trading loop)
    assert store.load().poll_count == 0
