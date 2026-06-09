"""Supabase-backed ``GrantStore`` — prod persistence for the Privy grant mapping.

The in-memory ``GrantStore`` (``privy_adapter.GrantStore``) loses state across
processes, so enabling Privy in a multi-process prod deploy would drop grant
state between replicas. ``SupabaseGrantStore`` persists the same
``GrantRecord`` to the Supabase remodel tables so every replica sees the same
(user → wallet, policy, scope) mapping.

It is a DROP-IN for the in-memory store: the exact same ``get(user_id)`` /
``put(record)`` surface that ``PrivyWalletAdapter`` calls. Revoke is expressed
the way the adapter already does it — ``put`` of a ``GrantRecord`` whose
``scope.revoked`` is ``True`` — so no extra method is needed.

GrantRecord → tables:
  wallet_links(user_id, address, provider='privy', custody='user-owned',
               external_wallet_id=record.wallet_id)
  agent_grants(user_id, allowed_actions[], withdraw_allowlist[],
               revoked, policy_id=record.policy_id)

NON-CUSTODIAL: only PUBLIC handles are stored (address, vendor wallet_id,
policy_id, the scope arrays). NEVER key material (invariant #1).

RLS belt-and-suspenders: every read/write carries an EXPLICIT
``.eq("user_id", ...)`` filter even though we use the service-role client, so a
row is never touched outside its owner.

LAZY CLIENT. The Supabase client is built on first use (or injected for tests),
never at construction — so the wallet factory can route here without a network
call or secret read at import/wiring time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from gecko_core.wallets.privy_adapter import GrantRecord
from gecko_core.wallets.provider import Scope

if TYPE_CHECKING:
    from supabase import Client

_WALLET_LINKS = "wallet_links"
_AGENT_GRANTS = "agent_grants"


class SupabaseGrantStore:
    """Persistent ``GrantStore`` over the Supabase ``wallet_links`` +
    ``agent_grants`` tables. Drop-in for the in-memory ``GrantStore``."""

    def __init__(self, client: Client | None = None) -> None:
        self._client = client

    # -- client seam -----------------------------------------------------

    def _db(self) -> Client:
        """Lazily build the service-role client (or use the injected one)."""
        if self._client is None:
            from gecko_core.db import create_supabase_client

            self._client = create_supabase_client()
        return self._client

    # -- GrantStore surface ---------------------------------------------

    def get(self, user_id: str) -> GrantRecord | None:
        """Read both tables, reconstruct the ``GrantRecord`` (or ``None``)."""
        db = self._db()

        link_rows = (
            db.table(_WALLET_LINKS)
            .select(
                "user_id",
                "address",
                "provider",
                "custody",
                "external_wallet_id",
            )
            .eq("user_id", user_id)
            .execute()
            .data
        )
        if not link_rows:
            return None
        link: dict[str, Any] = cast("dict[str, Any]", link_rows[0])

        grant_rows = (
            db.table(_AGENT_GRANTS)
            .select(
                "user_id",
                "allowed_actions",
                "withdraw_allowlist",
                "revoked",
                "policy_id",
            )
            .eq("user_id", user_id)
            .execute()
            .data
        )

        scope: Scope | None = None
        policy_id: str | None = None
        if grant_rows:
            grant: dict[str, Any] = cast("dict[str, Any]", grant_rows[0])
            policy_id = grant.get("policy_id")
            scope = Scope(
                allowed_actions=frozenset(grant.get("allowed_actions") or []),
                withdraw_allowlist=frozenset(grant.get("withdraw_allowlist") or []),
                revoked=bool(grant.get("revoked", False)),
            )

        return GrantRecord(
            user_id=user_id,
            wallet_id=link.get("external_wallet_id") or "",
            address=link.get("address") or "",
            policy_id=policy_id,
            scope=scope,
        )

    def put(self, record: GrantRecord) -> None:
        """Upsert ``wallet_links`` + ``agent_grants`` for ``record.user_id``.

        Select-then-update-or-insert (filtered by ``user_id``) rather than a
        PostgREST ``on_conflict`` upsert, because both tables key off PARTIAL
        unique indexes (``wallet_links`` on ``(user_id,address) WHERE
        deleted_at IS NULL``; ``agent_grants`` on ``(user_id) WHERE revoked =
        false``) which on_conflict can't target cleanly. The explicit
        ``.eq("user_id", ...)`` filter doubles as the RLS belt-and-suspenders.
        """
        db = self._db()

        wallet_payload: dict[str, Any] = {
            "user_id": record.user_id,
            "address": record.address,
            "provider": "privy",
            "custody": "user-owned",
            "external_wallet_id": record.wallet_id,
        }
        self._upsert(db, _WALLET_LINKS, record.user_id, wallet_payload)

        scope = record.scope
        grant_payload: dict[str, Any] = {
            "user_id": record.user_id,
            "allowed_actions": sorted(scope.allowed_actions) if scope else [],
            "withdraw_allowlist": sorted(scope.withdraw_allowlist) if scope else [],
            "revoked": bool(scope.revoked) if scope else False,
            "policy_id": record.policy_id,
        }
        self._upsert(db, _AGENT_GRANTS, record.user_id, grant_payload)

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _upsert(db: Client, table: str, user_id: str, payload: dict[str, Any]) -> None:
        existing = db.table(table).select("user_id").eq("user_id", user_id).execute().data
        if existing:
            db.table(table).update(payload).eq("user_id", user_id).execute()
        else:
            db.table(table).insert(payload).execute()


def make_grant_store() -> SupabaseGrantStore:
    """Factory for a lazily-bound Supabase ``GrantStore`` (no client built yet)."""
    return SupabaseGrantStore()


__all__ = ["SupabaseGrantStore", "make_grant_store"]

# NOTE on the drop-in guarantee: the in-memory `GrantStore` is a concrete class,
# not a Protocol, so a static `GrantStore`-typed assignment would be a nominal
# (subclass) check that this duck-typed store can't satisfy. The drop-in surface
# (same `get(user_id)` / `put(record)` signatures) is verified at RUNTIME instead
# by tests/test_supabase_grantstore.py::test_is_drop_in_for_in_memory_grantstore_protocol.
