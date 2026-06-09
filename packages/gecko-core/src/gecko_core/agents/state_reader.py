"""Session-safe reader for the hosted-agent `agent_state` Mongo mirror.

The hosted paper agent persists `{agent_id, state, updated_at}` into the Mongo
collection `agent_state` (contest_bot/agent_store.py's MongoBotStateStore writes,
AgentStateStore reads). This module is the gecko-core READER half: gecko-api
calls `read_agent_state` to surface a user's deployed-agent runtime state.

gecko-core must not depend on contest_bot, so the Mongo connection pattern is
REIMPLEMENTED here (same env vars, db name, timeout, and doc shape) rather than
imported. Degrades gracefully to None when no Mongo is configured.

`scope_state_for_user` is the security boundary: `state` carries internal fields
(`spec`, `total_spent_usd`, cohort/model internals) that must never reach a
user-facing API. It is a WHITELIST — missing keys are omitted, unknown keys are
dropped.
"""

from __future__ import annotations

import os
from typing import Any

_DB_NAME = os.environ.get("GECKO_MONGO_DB", "gecko")

# Only these keys are safe to surface to a user-facing API. Anything not listed
# here (notably `spec`, `total_spent_usd`, cohort/model internals) is dropped.
_USER_SAFE_KEYS: frozenset[str] = frozenset(
    {
        "positions",
        "realized_pnl_today",
        "wins_today",
        "losses_today",
        "daily_trades",
        "still_alive_at",
        "poll_count",
        "updated_at",
    }
)


def _mongo_uri() -> str | None:
    return os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or None


def _collection(name: str) -> Any | None:
    """Return a pymongo collection for `name`, or None when no MONGODB_URI /
    MONGO_URI is set (→ caller returns None). Never raises into the caller."""
    uri = _mongo_uri()
    if not uri:
        return None
    try:
        import pymongo

        client: Any = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
        return client[_DB_NAME][name]
    except Exception:
        return None


def read_agent_state(agent_id: str) -> dict[str, Any] | None:
    """Return the stored runtime state for `agent_id`, or None when there is no
    Mongo configured / no doc. The doc shape written by the hosted agent is
    `{agent_id, state, updated_at}`; we return the `state` sub-doc merged with
    `updated_at` so the caller gets liveness alongside the snapshot.

    NOT scoped — callers exposing this to users MUST pass the result through
    `scope_state_for_user`.
    """
    col = _collection("agent_state")
    if col is None:
        return None
    doc = col.find_one({"agent_id": agent_id}, {"_id": 0})
    if not doc or "state" not in doc:
        return None
    return {**doc["state"], "updated_at": doc.get("updated_at")}


def scope_state_for_user(state: dict[str, Any]) -> dict[str, Any]:
    """Whitelist-filter a raw agent state down to user-safe fields.

    Drops everything not in `_USER_SAFE_KEYS` (e.g. `spec`, `total_spent_usd`).
    Missing whitelisted keys are simply omitted — never defaulted in.
    """
    return {k: v for k, v in state.items() if k in _USER_SAFE_KEYS}
