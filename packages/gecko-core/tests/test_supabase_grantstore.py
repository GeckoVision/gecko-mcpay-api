"""SupabaseGrantStore — the prod-persistent GrantStore (V1 Phase 2).

These tests drive a FAKE Supabase client seam: NO live Supabase, NO network,
NO secrets. The fake records every table().<op>().eq().execute() chain so we can
assert:

  * put() upserts BOTH wallet_links (with external_wallet_id) AND agent_grants
    (with policy_id + the scope arrays), each keyed by an EXPLICIT
    .eq("user_id", ...) filter (RLS belt-and-suspenders).
  * get() reads both tables and reconstructs the GrantRecord (incl. Scope).
  * revoke (put with scope.revoked=True) flips agent_grants.revoked.

SupabaseGrantStore is a drop-in for the in-memory GrantStore Protocol: same
get(user_id) / put(record) surface, so PrivyWalletAdapter uses it unchanged.
"""

from __future__ import annotations

from typing import Any

from gecko_core.wallets.privy_adapter import GrantRecord
from gecko_core.wallets.provider import Scope
from gecko_core.wallets.supabase_grant_store import SupabaseGrantStore

# ---------------------------------------------------------------------------
# Fake Supabase client seam.
#
# Mimics enough of supabase-py's fluent builder: client.table(name) ->
# builder; builder.select/.insert/.update/.upsert(...) -> builder;
# builder.eq(col, val) -> builder; builder.execute() -> APIResponse-ish with
# `.data`. Each terminal execute() appends a record of the whole chain to
# `client.calls` for assertions, and returns seeded rows for selects.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, client: FakeSupabaseClient, table: str) -> None:
        self._client = client
        self._table = table
        self._op: str | None = None
        self._payload: Any = None
        self._filters: dict[str, Any] = {}

    def select(self, *cols: str) -> _FakeQuery:
        self._op = "select"
        self._payload = list(cols)
        return self

    def insert(self, payload: dict[str, Any]) -> _FakeQuery:
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> _FakeQuery:
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload: dict[str, Any], **kwargs: Any) -> _FakeQuery:
        self._op = "upsert"
        self._payload = payload
        return self

    def eq(self, col: str, val: Any) -> _FakeQuery:
        self._filters[col] = val
        return self

    def limit(self, _n: int) -> _FakeQuery:
        return self

    def maybe_single(self) -> _FakeQuery:
        return self

    def execute(self) -> _FakeResponse:
        self._client.calls.append(
            {
                "table": self._table,
                "op": self._op,
                "payload": self._payload,
                "filters": dict(self._filters),
            }
        )
        if self._op == "select":
            rows = self._client.seeded.get(self._table, [])
            # Match ALL applied filters (e.g. user_id for the grant tables, OR
            # `id` for app_users which is keyed on its PK, not user_id).
            matched = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
            return _FakeResponse(matched)
        return _FakeResponse([self._payload] if isinstance(self._payload, dict) else [])


class FakeSupabaseClient:
    def __init__(self, seeded: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.seeded: dict[str, list[dict[str, Any]]] = seeded or {}
        self.calls: list[dict[str, Any]] = []

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scope() -> Scope:
    return Scope(
        allowed_actions=frozenset({"jupiter_swap", "kamino_deposit"}),
        withdraw_allowlist=frozenset({"OwnerAddr111"}),
    )


def _calls_for(client: FakeSupabaseClient, table: str) -> list[dict[str, Any]]:
    return [c for c in client.calls if c["table"] == table]


# ---------------------------------------------------------------------------
# put()
# ---------------------------------------------------------------------------


def test_put_upserts_wallet_links_with_external_wallet_id() -> None:
    client = FakeSupabaseClient()
    store = SupabaseGrantStore(client=client)
    rec = GrantRecord(
        user_id="user-1",
        wallet_id="wallet-xyz",
        address="OwnerAddr111",
        policy_id="policy-abc",
        scope=_scope(),
    )

    store.put(rec)

    wl = _calls_for(client, "wallet_links")
    writes = [c for c in wl if c["op"] in ("insert", "update", "upsert")]
    assert writes, "put must write wallet_links"
    payloads = [c["payload"] for c in writes]
    merged = {k: v for p in payloads for k, v in p.items()}
    assert merged["user_id"] == "user-1"
    assert merged["address"] == "OwnerAddr111"
    assert merged["provider"] == "privy"
    assert merged["custody"] == "user-owned"
    assert merged["external_wallet_id"] == "wallet-xyz"
    # Every select/update is explicitly user-scoped (RLS belt-and-suspenders);
    # inserts carry user_id in the payload instead of a filter.
    for c in wl:
        if c["op"] in ("select", "update"):
            assert c["filters"].get("user_id") == "user-1"
        if c["op"] == "insert":
            assert c["payload"]["user_id"] == "user-1"


def test_put_upserts_agent_grants_with_policy_id_and_scope_arrays() -> None:
    client = FakeSupabaseClient()
    store = SupabaseGrantStore(client=client)
    rec = GrantRecord(
        user_id="user-1",
        wallet_id="wallet-xyz",
        address="OwnerAddr111",
        policy_id="policy-abc",
        scope=_scope(),
    )

    store.put(rec)

    ag = _calls_for(client, "agent_grants")
    writes = [c for c in ag if c["op"] in ("insert", "update", "upsert")]
    assert writes, "put must write agent_grants"
    merged = {k: v for c in writes for k, v in c["payload"].items()}
    assert merged["user_id"] == "user-1"
    assert merged["policy_id"] == "policy-abc"
    assert sorted(merged["allowed_actions"]) == ["jupiter_swap", "kamino_deposit"]
    assert sorted(merged["withdraw_allowlist"]) == ["OwnerAddr111"]
    assert merged["revoked"] is False
    for c in ag:
        if c["op"] in ("select", "update"):
            assert c["filters"].get("user_id") == "user-1"
        if c["op"] == "insert":
            assert c["payload"]["user_id"] == "user-1"


def test_put_existing_row_updates_not_double_inserts() -> None:
    # A fully-returning user: identity row + both grant rows already exist.
    seeded = {
        "app_users": [{"id": "user-1"}],
        "wallet_links": [{"user_id": "user-1", "address": "OwnerAddr111"}],
        "agent_grants": [{"user_id": "user-1", "allowed_actions": [], "revoked": False}],
    }
    client = FakeSupabaseClient(seeded=seeded)
    store = SupabaseGrantStore(client=client)
    store.put(
        GrantRecord(
            user_id="user-1",
            wallet_id="wallet-xyz",
            address="OwnerAddr111",
            policy_id="policy-abc",
            scope=_scope(),
        )
    )
    # When all rows already exist we UPDATE them (filtered by user_id), never
    # insert — including app_users, which is only ever insert-if-absent.
    ops = {c["op"] for c in client.calls if c["op"] in ("insert", "update")}
    assert "update" in ops
    assert "insert" not in ops


def test_put_mints_app_users_before_fk_children() -> None:
    """The identity row must be inserted into app_users BEFORE wallet_links /
    agent_grants, or the FK (wallet_links.user_id -> app_users.id) 500s the
    first onboarding/link for any fresh user (23503 foreign_key_violation)."""
    client = FakeSupabaseClient()
    store = SupabaseGrantStore(client=client)

    store.put(
        GrantRecord(
            user_id="user-1",
            wallet_id="wallet-xyz",
            address="OwnerAddr111",
            policy_id="policy-abc",
            scope=_scope(),
        )
    )

    # app_users was inserted, keyed on its PK `id` (not user_id).
    au_inserts = [c for c in _calls_for(client, "app_users") if c["op"] == "insert"]
    assert au_inserts, "put must mint the app_users identity row"
    assert au_inserts[0]["payload"] == {"id": "user-1"}

    # ...and it happens BEFORE the first wallet_links write (ordering matters:
    # the FK parent must exist first).
    order = [c["table"] for c in client.calls]
    first_app_user = order.index("app_users")
    first_wallet_link = order.index("wallet_links")
    assert first_app_user < first_wallet_link


def test_put_idempotent_user_not_reinserted() -> None:
    """A returning user (app_users row already present) is NOT re-inserted —
    _ensure_user is insert-if-absent, never update/double-insert."""
    seeded = {"app_users": [{"id": "user-1"}]}
    client = FakeSupabaseClient(seeded=seeded)
    store = SupabaseGrantStore(client=client)

    store.put(
        GrantRecord(
            user_id="user-1",
            wallet_id="wallet-xyz",
            address="OwnerAddr111",
            policy_id="policy-abc",
            scope=_scope(),
        )
    )

    au = _calls_for(client, "app_users")
    assert any(c["op"] == "select" for c in au), "must check existence first"
    assert not any(c["op"] == "insert" for c in au), "existing user must NOT be re-inserted"
    # app_users is the identity root: never UPDATE it from the grant store.
    assert not any(c["op"] == "update" for c in au)


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


def test_get_reconstructs_grant_record() -> None:
    seeded = {
        "wallet_links": [
            {
                "user_id": "user-1",
                "address": "OwnerAddr111",
                "provider": "privy",
                "custody": "user-owned",
                "external_wallet_id": "wallet-xyz",
            }
        ],
        "agent_grants": [
            {
                "user_id": "user-1",
                "allowed_actions": ["jupiter_swap", "kamino_deposit"],
                "withdraw_allowlist": ["OwnerAddr111"],
                "revoked": False,
                "policy_id": "policy-abc",
            }
        ],
    }
    client = FakeSupabaseClient(seeded=seeded)
    store = SupabaseGrantStore(client=client)

    rec = store.get("user-1")

    assert rec is not None
    assert rec.user_id == "user-1"
    assert rec.wallet_id == "wallet-xyz"
    assert rec.address == "OwnerAddr111"
    assert rec.policy_id == "policy-abc"
    assert rec.scope is not None
    assert rec.scope.allowed_actions == frozenset({"jupiter_swap", "kamino_deposit"})
    assert rec.scope.withdraw_allowlist == frozenset({"OwnerAddr111"})
    assert rec.scope.revoked is False
    # Reads are explicitly user-scoped.
    for c in client.calls:
        assert c["filters"].get("user_id") == "user-1"


def test_get_missing_user_returns_none() -> None:
    client = FakeSupabaseClient(seeded={})
    store = SupabaseGrantStore(client=client)
    assert store.get("nobody") is None


def test_get_link_without_grant_reconstructs_record_with_none_scope() -> None:
    seeded = {
        "wallet_links": [
            {
                "user_id": "user-1",
                "address": "OwnerAddr111",
                "provider": "privy",
                "custody": "user-owned",
                "external_wallet_id": "wallet-xyz",
            }
        ],
        "agent_grants": [],
    }
    client = FakeSupabaseClient(seeded=seeded)
    store = SupabaseGrantStore(client=client)

    rec = store.get("user-1")

    assert rec is not None
    assert rec.wallet_id == "wallet-xyz"
    assert rec.scope is None
    assert rec.policy_id is None


# ---------------------------------------------------------------------------
# revoke (put with a revoked scope flips agent_grants.revoked)
# ---------------------------------------------------------------------------


def test_put_revoked_scope_flips_revoked_flag() -> None:
    seeded = {
        "wallet_links": [{"user_id": "user-1", "address": "OwnerAddr111"}],
        "agent_grants": [
            {"user_id": "user-1", "allowed_actions": ["jupiter_swap"], "revoked": False}
        ],
    }
    client = FakeSupabaseClient(seeded=seeded)
    store = SupabaseGrantStore(client=client)

    revoked_scope = Scope(
        allowed_actions=frozenset({"jupiter_swap", "kamino_deposit"}),
        withdraw_allowlist=frozenset({"OwnerAddr111"}),
        revoked=True,
    )
    store.put(
        GrantRecord(
            user_id="user-1",
            wallet_id="wallet-xyz",
            address="OwnerAddr111",
            policy_id="policy-abc",
            scope=revoked_scope,
        )
    )

    ag_writes = [
        c for c in _calls_for(client, "agent_grants") if c["op"] in ("insert", "update", "upsert")
    ]
    merged = {k: v for c in ag_writes for k, v in c["payload"].items()}
    assert merged["revoked"] is True
    for c in _calls_for(client, "agent_grants"):
        assert c["filters"].get("user_id") == "user-1"


def test_is_drop_in_for_in_memory_grantstore_protocol() -> None:
    """Structural: SupabaseGrantStore matches the get/put surface PrivyWalletAdapter uses."""
    from gecko_core.wallets.privy_adapter import GrantStore

    client = FakeSupabaseClient(seeded={})
    store: GrantStore = SupabaseGrantStore(client=client)  # type: ignore[assignment]
    assert hasattr(store, "get") and hasattr(store, "put")
