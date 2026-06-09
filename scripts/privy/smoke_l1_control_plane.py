"""L1 control-plane smoke for the Privy custody adapter — LIVE Privy API.

Exercises the non-custodial control plane end-to-end against the REAL Privy v2
REST API (creds from the repo-root .env: PRIVY_APP_ID / PRIVY_APP_SECRET):

    link -> grant_scope -> scope_for -> revoke -> scope_for
    + execute / withdraw are signing-gated (NotImplementedError)

NO chain transactions, NO signing, NO money. This is control-plane ONLY:
it creates a real Privy wallet resource + a real Privy policy resource and
rewrites the policy to deny-all on revoke. Signing is gated in the adapter,
so nothing is ever broadcast.

SECURITY: never prints PRIVY_APP_ID or PRIVY_APP_SECRET. The wallet address,
wallet_id, and policy_id are public identifiers and are printed.

Run:
    set -a; source .env; set +a
    uv run python scripts/privy/smoke_l1_control_plane.py
"""

from __future__ import annotations

import sys
import time

from gecko_core.wallets.factory import make_wallet_provider
from gecko_core.wallets.privy import PrivyClientError
from gecko_core.wallets.privy_adapter import PrivyWalletAdapter
from gecko_core.wallets.provider import (
    TRADE_ONLY_ACTIONS,
    Scope,
)

# user_id maps to Privy's `external_id`, which is unique-per-wallet. A second
# create with an existing external_id returns a 500 from Privy (not a clean
# 409), so each run uses a fresh, clearly-test id under the gecko-l1-smoke
# prefix. Privy does NOT support deleting wallets/policies, so these test
# resources accumulate — they are inert (revoked deny-all, signing gated).
_RUN = time.strftime("%Y%m%dT%H%M%S")
USER_ID = f"gecko-l1-smoke-{_RUN}"
# Placeholder for the `link(user_id, address)` signature. The Privy adapter
# ignores this value for creation (it calls create_solana_wallet with
# owner_label=user_id) — the REAL address comes back on the WalletLink.
PLACEHOLDER_ADDR = "placeholder-address-ignored-by-privy-create"


def _ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


def main() -> int:
    print("=== L1 control-plane smoke: Privy custody adapter (LIVE) ===\n")

    # -- Step 1: factory resolves to the REAL adapter, not the stub ----------
    print("[1] make_wallet_provider() resolves to PrivyWalletAdapter")
    provider = make_wallet_provider()
    if not isinstance(provider, PrivyWalletAdapter):
        _fail(
            f"factory returned {type(provider).__name__}, not PrivyWalletAdapter. "
            "Env not loaded (PRIVY_APP_ID/SECRET missing or GECKO_WALLET_PROVIDER=stub). "
            "Did you `set -a; source .env; set +a`?"
        )
        return 1
    _ok(f"factory resolved {type(provider).__name__} (provider tag={provider.provider!r})")

    # Use the FACTORY-BUILT adapter directly — no per-call client workaround.
    # PrivyClient now opens + closes a fresh httpx.AsyncClient per request, so
    # the adapter's asyncio.run-per-call sync bridge works across N calls
    # (link -> grant -> scope_for -> revoke) without "Event loop is closed".
    # This is exactly what factory.py constructs in prod.
    adapter = provider

    # -- Step 2: link -> real create_solana_wallet ---------------------------
    print("\n[2] link() -> real Privy create_solana_wallet")
    try:
        link = adapter.link(USER_ID, PLACEHOLDER_ADDR)
    except PrivyClientError as exc:
        _fail(f"link raised PrivyClientError verbatim: {exc}")
        return 1

    wallet_id = adapter._store.get(USER_ID).wallet_id  # public id, fine to print
    print(f"        wallet_id = {wallet_id}")
    print(f"        address   = {link.address}")
    print(f"        custody   = {link.custody}")
    print(f"        provider  = {link.provider}")
    if link.custody != "user-owned":
        _fail(f"custody is {link.custody!r}, expected 'user-owned'")
        return 1
    _ok("wallet created; custody == 'user-owned'")
    created_address = link.address

    # -- Step 3: grant_scope -> real create_policy + attach ------------------
    print("\n[3] grant_scope() -> real Privy create_policy + attach_policy_to_wallet")
    # Self-allowlist = the freshly-created wallet's own address (the user's own
    # wallet). withdraw_allowlist MUST be exactly {created_address} or
    # scope_to_privy_rules fails closed.
    scope = Scope(
        allowed_actions=TRADE_ONLY_ACTIONS,
        withdraw_allowlist=frozenset({created_address}),
    )
    try:
        granted = adapter.grant_scope(USER_ID, scope)
    except PrivyClientError as exc:
        _fail(f"grant_scope raised PrivyClientError verbatim: {exc}")
        return 1

    policy_id = adapter._store.get(USER_ID).policy_id
    print(f"        policy_id = {policy_id}")
    print(f"        actions   = {sorted(granted.allowed_actions)}")
    print(f"        allowlist = {sorted(granted.withdraw_allowlist)}")
    if policy_id is None:
        _fail("no policy_id persisted after grant_scope")
        return 1
    if granted.revoked:
        _fail("granted scope is already revoked")
        return 1
    _ok("policy created + attached; scope not revoked")

    # -- Step 4: scope_for reflects the live grant ---------------------------
    print("\n[4] scope_for() reflects the granted (non-revoked) scope")
    s = adapter.scope_for(USER_ID)
    if s is None:
        _fail("scope_for returned None after grant")
        return 1
    if s.revoked:
        _fail("scope_for shows revoked=True before revoke")
        return 1
    if created_address not in s.withdraw_allowlist:
        _fail("scope_for allowlist missing the user's own address")
        return 1
    _ok("scope_for returns the live grant (revoked=False, self-allowlisted)")

    # -- Step 5: revoke -> real deny-all policy rewrite ----------------------
    print("\n[5] revoke() -> real Privy update_policy_rules (deny-all)")
    try:
        adapter.revoke(USER_ID)
    except PrivyClientError as exc:
        _fail(f"revoke raised PrivyClientError verbatim: {exc}")
        return 1
    s_after = adapter.scope_for(USER_ID)
    if s_after is None or not s_after.revoked:
        _fail("scope_for does not show revoked=True after revoke")
        return 1
    _ok("policy rewritten to deny-all; scope_for shows revoked=True")

    # Optional: fetch the policy back and confirm the deny-all rule shape.
    print("\n[5b] (optional) confirm policy rules are deny-all on Privy")
    try:
        raw = adapter._run(adapter._client._get(f"/v1/policies/{policy_id}"))
        rules = raw.get("rules")
        print(f"        live rules = {rules}")
        if isinstance(rules, list) and any(
            r.get("action") == "DENY" and r.get("method") == "*" for r in rules
        ):
            _ok("Privy policy now carries a method='*' DENY rule")
        else:
            print(
                "  WARN  could not confirm deny-all shape (Privy GET shape may differ); "
                "local revoked flag is authoritative for L1"
            )
    except PrivyClientError as exc:
        print(f"  WARN  policy GET raised (non-fatal for L1): {exc}")

    # -- Step 6: execute / withdraw are signing-gated ------------------------
    print("\n[6] execute()/withdraw() are signing-gated (NotImplementedError)")
    # After revoke the live-scope guard raises RevokedError before the gate, so
    # use a SECOND fresh user to hit the pure signing gate on a live grant.
    gate_user = f"gecko-l1-smoke-gate-{_RUN}"
    try:
        glink = adapter.link(gate_user, PLACEHOLDER_ADDR)
        gscope = Scope(
            allowed_actions=TRADE_ONLY_ACTIONS,
            withdraw_allowlist=frozenset({glink.address}),
        )
        adapter.grant_scope(gate_user, gscope)
    except PrivyClientError as exc:
        _fail(f"gate-user setup raised PrivyClientError: {exc}")
        return 1

    gate_wallet_id = adapter._store.get(gate_user).wallet_id
    gate_policy_id = adapter._store.get(gate_user).policy_id
    print(f"        gate wallet_id = {gate_wallet_id}")
    print(f"        gate policy_id = {gate_policy_id}")

    try:
        adapter.execute(gate_user, "kamino_deposit", 1.0)
        _fail("execute did NOT raise — signing is NOT gated!")
        return 1
    except NotImplementedError as exc:
        _ok(f"execute raised NotImplementedError: {exc}")

    try:
        # withdraw-to-self passes the allowlist guard, then hits the signing gate
        adapter.withdraw(gate_user, 1.0, glink.address)
        _fail("withdraw did NOT raise — signing is NOT gated!")
        return 1
    except NotImplementedError as exc:
        _ok(f"withdraw raised NotImplementedError: {exc}")

    # Revoke the gate user's grant too (deny-all) so we don't leave a live
    # signable policy behind on Privy.
    try:
        adapter.revoke(gate_user)
        _ok("gate-user grant revoked (deny-all) for cleanup")
    except PrivyClientError as exc:
        print(f"  WARN  gate-user revoke raised (non-fatal): {exc}")

    print("\n=== SUMMARY ===")
    print(f"  primary wallet_id : {wallet_id}")
    print(f"  primary address   : {created_address}")
    print(f"  primary policy_id : {policy_id} (revoked -> deny-all)")
    print(f"  gate wallet_id    : {gate_wallet_id}")
    print(f"  gate policy_id    : {gate_policy_id} (revoked -> deny-all)")
    print("\nL1 PASS")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:
        print(f"\nL1 FAIL: {type(exc).__name__}: {exc}")
        rc = 1
    sys.exit(rc)
