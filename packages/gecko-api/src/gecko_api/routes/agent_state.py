"""V1 Phase 1 — Task 1.4 — session-scoped read route `GET /v1/agent/state`.

Resolves the verified session principal -> the caller's OWN `user_agents` row ->
the hosted agent's Mongo `agent_state` doc, scoped down to user-safe fields.

SECURITY-CRITICAL ownership gate (D1-A): the HMAC session token yields a
``user_id``; the `user_agents` lookup filters EXPLICITLY on that ``user_id``.
Mongo `agent_state` has no RLS, so this Supabase filter is THE ownership gate —
`read_agent_state` is NEVER called with an agent_id that wasn't returned by a row
filtered on the caller's own ``user_id``. A binding owned by another user simply
returns no row -> 404; never another user's state.

`scope_state_for_user` is applied before the response so internal fields
(`spec`, `total_spent_usd`, cohort/model internals) never reach the client. The
raw state is never returned.

Thin transport layer — the Mongo read + scoping whitelist live in
`gecko_core.agents.state_reader`; the ownership write lives in `_bindings`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from gecko_core.agents.state_reader import read_agent_state, scope_state_for_user
from gecko_core.db import create_supabase_client
from supabase import Client

from ._session import SessionCtx, require_session

router = APIRouter(prefix="/v1", tags=["agent"])

_USER_AGENTS_TABLE = "user_agents"


def _client() -> Client:
    """Service-role Supabase client seam. Reuses the canonical core factory
    (`gecko_core.db.create_supabase_client`). Tests monkeypatch this name to
    inject a recording fake — keep it module-level."""
    return create_supabase_client()


def lookup_agent_for_user(user_id: str) -> dict[str, Any] | None:
    """Return the caller's OWN `user_agents` binding row, or None.

    The explicit `.eq("user_id", user_id)` filter is the ownership gate: only
    rows owned by `user_id` can ever be returned. `.is_("deleted_at", "null")`
    excludes soft-deleted bindings. `.maybe_single()` yields the row dict or
    None — never raises on zero rows.

    NEVER call `read_agent_state` with an agent_id that did not come from a row
    returned by THIS function for the caller's own user_id.
    """
    resp = (
        _client()
        .table(_USER_AGENTS_TABLE)
        .select("agent_id, strategy, profile")
        .eq("user_id", user_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    data = getattr(resp, "data", None)
    return data if data else None


@router.get("/agent/state")
def agent_state(ctx: Annotated[SessionCtx, Depends(require_session)]) -> dict[str, Any]:
    """Return the caller's hosted-agent binding + scoped runtime state.

    404 when the caller has no agent bound. 200 with `state: null` when the
    binding exists but the agent has not written a Mongo state doc yet.
    """
    row = lookup_agent_for_user(ctx.user_id)
    if row is None:
        raise HTTPException(404, "no agent for this user")

    raw = read_agent_state(row["agent_id"])
    scoped = scope_state_for_user(raw) if raw else None
    return {
        "agent_id": row["agent_id"],
        "strategy": row.get("strategy"),
        "profile": row.get("profile"),
        "state": scoped,
        "updated_at": (scoped or {}).get("updated_at"),
    }
