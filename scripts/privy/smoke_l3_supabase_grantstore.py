"""L3 live round-trip for SupabaseGrantStore — REAL (migrated) Supabase.

Pattern-C artifact for PR #118: the fake-seam unit tests
(tests/test_supabase_grantstore.py) prove the select-then-write LOGIC, but a
stub never exercises real PostgREST behavior — partial-unique indexes, the
``.data`` shape, the FK to ``app_users``, and array column round-tripping. This
script drives ``SupabaseGrantStore.put`` / ``.get`` against the live DB so we
KNOW #118 works end-to-end before the founder merges it.

Exercises:
    insert app_users (FK prereq) -> put(record) -> get -> revoke (put revoked
    scope) -> get -> cleanup (delete agent_grants + wallet_links + app_users).

The whole body is wrapped in try/finally so cleanup ALWAYS runs, even on a
mid-script failure, leaving the DB clean.

SECURITY: never prints SUPABASE_* / PRIVY_* values. Only PUBLIC test handles
(test user_id, fake address, fake wallet/policy ids) are printed.

Run:
    set -a; source .env; set +a
    uv run python scripts/privy/smoke_l3_supabase_grantstore.py
"""

from __future__ import annotations

import sys
import time

from gecko_core.db import create_supabase_client
from gecko_core.wallets.privy_adapter import GrantRecord
from gecko_core.wallets.provider import TRADE_ONLY_ACTIONS, user_scope
from gecko_core.wallets.supabase_grant_store import SupabaseGrantStore

_RUN = time.strftime("%Y%m%dT%H%M%S")
TEST_UID = f"u_l3smoke_{_RUN}"
# 43-char fake base58-ish string (32-44 char range, no key material).
TEST_ADDRESS = "Gec" + "k" * 38 + "L3s"  # 44 chars, clearly synthetic
TEST_WALLET_ID = "l3-smoke-wallet"
TEST_POLICY_ID = "l3-smoke-policy"

_failures: list[str] = []


def _ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")
    _failures.append(msg)


def _check(cond: bool, msg: str) -> None:
    (_ok if cond else _fail)(msg)


def main() -> int:
    assert 32 <= len(TEST_ADDRESS) <= 44, "test address out of base58 length band"

    client = create_supabase_client()
    store = SupabaseGrantStore(client=client)

    print(f"L3 SupabaseGrantStore live round-trip — user_id={TEST_UID}")
    print(f"  address={TEST_ADDRESS} ({len(TEST_ADDRESS)} chars)")
    print()

    try:
        # -- 0. FK prereq: app_users root row -----------------------------
        print("[0] insert app_users FK root")
        client.table("app_users").insert({"id": TEST_UID}).execute()
        _ok("app_users row inserted")

        # -- 1. put -------------------------------------------------------
        print("\n[1] put(record)")
        scope = user_scope(TEST_ADDRESS, actions=TRADE_ONLY_ACTIONS)
        record = GrantRecord(
            user_id=TEST_UID,
            wallet_id=TEST_WALLET_ID,
            address=TEST_ADDRESS,
            policy_id=TEST_POLICY_ID,
            scope=scope,
        )
        store.put(record)
        _ok("put() returned without error")

        # -- 2. get -------------------------------------------------------
        print("\n[2] get(user_id) — reconstruct")
        got = store.get(TEST_UID)
        if got is None:
            _fail("get() returned None after put()")
            return 1
        print(f"  round-tripped record: {got}")
        _check(got.wallet_id == TEST_WALLET_ID, f"wallet_id == {TEST_WALLET_ID!r}")
        _check(got.policy_id == TEST_POLICY_ID, f"policy_id == {TEST_POLICY_ID!r}")
        _check(got.address == TEST_ADDRESS, "address matches")
        _check(got.scope is not None, "scope reconstructed")
        if got.scope is not None:
            _check(
                got.scope.allowed_actions == TRADE_ONLY_ACTIONS,
                "scope.allowed_actions == TRADE_ONLY_ACTIONS",
            )
            _check(
                got.scope.withdraw_allowlist == frozenset({TEST_ADDRESS}),
                "scope.withdraw_allowlist == {address}",
            )
            _check(got.scope.revoked is False, "scope.revoked is False")

        # -- 3. revoke (put revoked scope) --------------------------------
        print("\n[3] revoke — put(record with scope.revoked=True)")
        from dataclasses import replace

        revoked_scope = replace(scope, revoked=True)
        store.put(replace(record, scope=revoked_scope))
        _ok("put(revoked) returned without error")

        print("\n[4] get after revoke")
        got_rev = store.get(TEST_UID)
        if got_rev is None:
            _fail("get() returned None after revoke")
        else:
            print(f"  post-revoke record: {got_rev}")
            _check(got_rev.scope is not None, "scope present post-revoke")
            if got_rev.scope is not None:
                _check(got_rev.scope.revoked is True, "scope.revoked is True")
            # wallet identity unchanged through revoke
            _check(got_rev.wallet_id == TEST_WALLET_ID, "wallet_id stable post-revoke")
            _check(got_rev.policy_id == TEST_POLICY_ID, "policy_id stable post-revoke")

    finally:
        # -- 5. cleanup ---------------------------------------------------
        print("\n[5] cleanup (finally)")
        for table, col in (
            ("agent_grants", "user_id"),
            ("wallet_links", "user_id"),
            ("app_users", "id"),
        ):
            try:
                client.table(table).delete().eq(col, TEST_UID).execute()
                remaining = client.table(table).select(col).eq(col, TEST_UID).execute().data
                _check(not remaining, f"{table} clean ({col}={TEST_UID})")
            except Exception as exc:  # cleanup must be loud, not fatal
                _fail(f"cleanup {table} raised: {type(exc).__name__}: {exc}")

    print()
    if _failures:
        print(f"L3 RESULT: FAIL ({len(_failures)} check(s) failed)")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("L3 RESULT: PASS — Supabase GrantStore round-trip green, DB left clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
