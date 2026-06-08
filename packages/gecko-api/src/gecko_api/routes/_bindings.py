"""Writer for the `user_agents` ownership binding (V1 Phase 1 — Task 1.3).

The grant route calls :func:`bind_user_agent` after a scope grant succeeds so
that a `user_agents` row exists keyed `{user_id -> Mongo GECKO_AGENT_ID}`. The
Phase 1 read route (Task 1.4) resolves session -> user_id -> this row before it
will touch any Mongo `agent_state` doc; without this writer that read can never
find an agent for the user.

Per decision D1-A, RLS is belt-and-suspenders: the HMAC session token is the
real gate, so this writer uses the SERVICE-ROLE Supabase client (which bypasses
RLS) and writes `user_id` explicitly. The client is exposed behind the
module-level :func:`_client` seam so tests can monkeypatch a fake.
"""

from __future__ import annotations

from gecko_core.db import create_supabase_client
from supabase import Client

_USER_AGENTS_TABLE = "user_agents"


def _client() -> Client:
    """Service-role Supabase client seam. Reuses the canonical core factory
    (`gecko_core.db.create_supabase_client`); never constructs its own. Tests
    monkeypatch this to inject a recording fake."""
    return create_supabase_client()


def bind_user_agent(
    user_id: str,
    agent_id: str,
    *,
    strategy: str | None = None,
    profile: str | None = None,
    status: str = "deployed",
) -> None:
    """Idempotently bind ``user_id`` to ``agent_id`` in ``user_agents``.

    Upsert keyed on ``agent_id`` (the partial unique index
    ``user_agents_agent_id_uidx``) so a re-grant updates the existing row rather
    than inserting a duplicate or erroring on the unique constraint.

    Raises whatever the Supabase client raises — the caller (the grant route)
    owns the decision to log-and-continue so a write failure never breaks the
    user-facing grant.
    """
    payload: dict[str, str] = {
        "user_id": user_id,
        "agent_id": agent_id,
        "status": status,
    }
    if strategy is not None:
        payload["strategy"] = strategy
    if profile is not None:
        payload["profile"] = profile

    _client().table(_USER_AGENTS_TABLE).upsert(payload, on_conflict="agent_id").execute()
