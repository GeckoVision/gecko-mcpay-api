"""Hosted-agent persistence — Phase 2 of the agent flow (spec
`private/specs/2026-06-03-agent-flow-hosting-design.md`).

Three pieces, all Mongo-backed with an in-memory fallback so local/dev/tests run
with NO Mongo (degrade gracefully when MONGODB_URI is unset):

  AgentRegistry      — deployed StrategySpecs: deploy / get / list / set_status.
  AgentStateStore    — the runtime state mirror, keyed by agent_id (what the app
                       dashboard reads, decoupled from the live process).
  MongoBotStateStore — a drop-in for the monolith's BotStateStore that persists
                       BotState to Mongo keyed by agent_id (the design's "Mongo
                       state store replaces local JSON"). Same load()/save() seam.

Because a strategy is a declarative StrategySpec (not user code), "deploy" is
just writing a validated config doc — no sandbox needed.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from bot_state import BotState, BotStateStore  # same-dir import (monolith layout)

_DB_NAME = os.environ.get("GECKO_MONGO_DB", "gecko")
# in-memory fallbacks (used when no MONGODB_URI) — module-level so they persist
# for the life of the process / a test session.
_MEM_AGENTS: dict[str, dict] = {}
_MEM_STATE: dict[str, dict] = {}


def _mongo_uri() -> str | None:
    return os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or None


def _collection(name: str):
    """Return a pymongo collection for `name`, or None when no MONGODB_URI is
    set (→ caller uses the in-memory fallback). Never raises into the caller."""
    uri = _mongo_uri()
    if not uri:
        return None
    try:
        import pymongo

        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
        return client[_DB_NAME][name]
    except Exception:
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Agent registry ───────────────────────────────────────────────────
class AgentRegistry:
    """Stores deployed agents. `deploy` refuses a REJECT verdict (the gate is the
    product) — pass verdict=None to skip the check (e.g. backtest not run yet)."""

    def __init__(self, collection=None) -> None:
        self._col = collection if collection is not None else _collection("agents")

    def deploy(
        self, spec: dict, user_id: str = "local", verdict: str | None = None, agent_id: str | None = None
    ) -> str:
        if verdict == "REJECT":
            raise ValueError("cannot deploy a strategy with a REJECT verdict (failed the rigor gate)")
        aid = agent_id or uuid.uuid4().hex[:16]
        doc = {
            "agent_id": aid,
            "user_id": user_id,
            "spec": spec,
            "verdict": verdict,
            "status": "deployed",
            "venue": spec.get("venue"),
            "universe": spec.get("universe", []),
            "strategy_id": spec.get("strategy_id"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        if self._col is not None:
            self._col.replace_one({"agent_id": aid}, doc, upsert=True)
        else:
            _MEM_AGENTS[aid] = doc
        return aid

    def get(self, agent_id: str) -> dict | None:
        if self._col is not None:
            doc = self._col.find_one({"agent_id": agent_id}, {"_id": 0})
            return doc
        return _MEM_AGENTS.get(agent_id)

    def list_agents(self, user_id: str | None = None) -> list[dict]:
        if self._col is not None:
            q = {"user_id": user_id} if user_id else {}
            return list(self._col.find(q, {"_id": 0}).sort("created_at", -1))
        docs = list(_MEM_AGENTS.values())
        if user_id:
            docs = [d for d in docs if d.get("user_id") == user_id]
        return sorted(docs, key=lambda d: d.get("created_at", ""), reverse=True)

    def set_status(self, agent_id: str, status: str) -> bool:
        patch = {"status": status, "updated_at": _now()}
        if self._col is not None:
            return self._col.update_one({"agent_id": agent_id}, {"$set": patch}).matched_count > 0
        if agent_id in _MEM_AGENTS:
            _MEM_AGENTS[agent_id].update(patch)
            return True
        return False


# ── Agent state mirror (what the dashboard reads) ────────────────────
class AgentStateStore:
    """Latest runtime-state snapshot per agent (decoupled from the live process)."""

    def __init__(self, collection=None) -> None:
        self._col = collection if collection is not None else _collection("agent_state")

    def put_state(self, agent_id: str, state: dict) -> None:
        doc = {"agent_id": agent_id, "state": state, "updated_at": _now()}
        if self._col is not None:
            self._col.replace_one({"agent_id": agent_id}, doc, upsert=True)
        else:
            _MEM_STATE[agent_id] = doc

    def get_state(self, agent_id: str) -> dict | None:
        if self._col is not None:
            return self._col.find_one({"agent_id": agent_id}, {"_id": 0})
        return _MEM_STATE.get(agent_id)


# ── Drop-in Mongo state store for the monolith ───────────────────────
class MongoBotStateStore(BotStateStore):
    """BotStateStore that persists BotState to Mongo keyed by agent_id, so a
    hosted agent's positions/pnl/liveness survive in the DB (not local JSON).
    Falls back to the parent file store when Mongo is unavailable. Selected in
    the monolith when GECKO_AGENT_ID + GECKO_STATE_BACKEND=mongo are set."""

    def __init__(self, agent_id: str, collection=None) -> None:
        super().__init__()  # keep a file path as the fallback target
        self._agent_id = agent_id
        # SAME collection AgentStateStore reads → the monolith is the writer, the
        # control-plane API the reader (the dashboard's state mirror).
        self._col = collection if collection is not None else _collection("agent_state")

    def load(self) -> BotState:
        if self._col is None:
            return super().load()
        doc = self._col.find_one({"agent_id": self._agent_id}, {"_id": 0})
        if not doc or "state" not in doc:
            return BotState()
        try:
            return BotState.model_validate(doc["state"])
        except Exception:
            return BotState()

    def save(self, state: BotState) -> None:
        if self._col is None:
            super().save(state)
            return
        payload: dict[str, Any] = {
            "agent_id": self._agent_id,
            "state": state.model_dump(),
            "updated_at": _now(),
        }
        try:
            self._col.replace_one({"agent_id": self._agent_id}, payload, upsert=True)
        except Exception:
            super().save(state)
