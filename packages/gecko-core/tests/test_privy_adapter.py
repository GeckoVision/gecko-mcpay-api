"""PrivyWalletAdapter — real non-custodial custody adapter (V1 Phase 2, Task 2.2).

TDD against a respx-mocked Privy v2 REST API. NO live network calls: every
Privy endpoint the adapter touches is mocked here. A test that escapes to the
real network is a failure (respx asserts_all_mocked by default).

Two test groups:

  1. Per-method behavior — link idempotency, grant (policy create + attach),
     scope_for, revoke (genuine authority removal), and the GATED execute/
     withdraw (raise NotImplementedError, never half-sign).

  2. Conformance — the SAME non-custodial invariant assertions the stub's
     contract test (`test_wallet_provider.py`) encodes, parametrized over BOTH
     StubWalletProvider AND PrivyWalletAdapter(respx-mocked), so the adapter is
     held to the identical contract: custody user-owned, out-of-scope blocked,
     withdraw-to-non-self blocked, revoke removes authority, allowlist-only.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from gecko_core.wallets import (
    NotLinkedError,
    RevokedError,
    ScopeError,
    StubWalletProvider,
    WalletProvider,
    user_scope,
)
from gecko_core.wallets.privy import PrivyClient
from gecko_core.wallets.privy_adapter import GrantStore, PrivyWalletAdapter

# ---------------------------------------------------------------------------
# Fixtures + constants
# ---------------------------------------------------------------------------

USER = "user-1"
USER_ADDR = "USERaddr1111111111111111111111111111111111"
EVIL_ADDR = "ATTACKERaddr22222222222222222222222222222222"

_BASE = "https://api.privy.io"
_WALLET_ID = "wal_abc123"
_POLICY_ID = "pol_xyz789"


def _wallet_body(wallet_id: str = _WALLET_ID, address: str = USER_ADDR) -> dict[str, Any]:
    return {
        "id": wallet_id,
        "address": address,
        "chain_type": "solana",
        "created_at": "2026-06-09T00:00:00Z",
    }


def _policy_body(policy_id: str = _POLICY_ID) -> dict[str, Any]:
    return {
        "id": policy_id,
        "name": f"gecko-scope-{USER}",
        "chain_type": "solana",
        "created_at": "2026-06-09T00:00:00Z",
    }


@pytest.fixture
def privy_client() -> Iterator[PrivyClient]:
    """A PrivyClient with injected (non-sentinel) creds + a real httpx client.

    respx patches the transport, so no bytes hit the network. Creds are dummy
    but non-sentinel so the constructor's gate passes.
    """
    client = PrivyClient(
        app_id="test-app-id",
        app_secret="test-app-secret",
        base_url=_BASE,
        client=httpx.AsyncClient(timeout=5.0),
    )
    yield client


@respx.mock
def _make_adapter(
    privy_client: PrivyClient,
    *,
    linked: bool = False,
    granted: bool = False,
) -> PrivyWalletAdapter:
    """Build an adapter, optionally pre-driven through link/grant under mocks."""
    adapter = PrivyWalletAdapter(privy_client, store=GrantStore())
    if linked or granted:
        respx.post(f"{_BASE}/v1/wallets").mock(
            return_value=httpx.Response(200, json=_wallet_body())
        )
    if granted:
        respx.post(f"{_BASE}/v1/policies").mock(
            return_value=httpx.Response(200, json=_policy_body())
        )
        respx.patch(f"{_BASE}/v1/wallets/{_WALLET_ID}").mock(
            return_value=httpx.Response(200, json=_wallet_body())
        )
    if linked or granted:
        adapter.link(USER, USER_ADDR)
    if granted:
        adapter.grant_scope(USER, user_scope(USER_ADDR))
    return adapter


# ---------------------------------------------------------------------------
# 1. Per-method behavior
# ---------------------------------------------------------------------------


@respx.mock
def test_link_creates_wallet_and_returns_user_owned(privy_client: PrivyClient) -> None:
    route = respx.post(f"{_BASE}/v1/wallets").mock(
        return_value=httpx.Response(200, json=_wallet_body())
    )
    adapter = PrivyWalletAdapter(privy_client, store=GrantStore())

    link = adapter.link(USER, USER_ADDR)

    assert route.called
    assert link.custody == "user-owned"
    assert link.provider == "privy"
    assert link.address == USER_ADDR
    # carries NO key material (same assertion as the stub contract)
    assert not any("key" in f.lower() or "secret" in f.lower() for f in vars(link))


@respx.mock
def test_link_is_idempotent_per_user(privy_client: PrivyClient) -> None:
    route = respx.post(f"{_BASE}/v1/wallets").mock(
        return_value=httpx.Response(200, json=_wallet_body())
    )
    adapter = PrivyWalletAdapter(privy_client, store=GrantStore())

    first = adapter.link(USER, USER_ADDR)
    second = adapter.link(USER, USER_ADDR)

    # Second link does NOT create a second Privy wallet.
    assert route.call_count == 1
    assert first.address == second.address


@respx.mock
def test_link_passes_user_id_as_external_id(privy_client: PrivyClient) -> None:
    route = respx.post(f"{_BASE}/v1/wallets").mock(
        return_value=httpx.Response(200, json=_wallet_body())
    )
    PrivyWalletAdapter(privy_client, store=GrantStore()).link(USER, USER_ADDR)

    sent = route.calls.last.request
    import json as _json

    body = _json.loads(sent.content)
    assert body["external_id"] == USER  # idempotency anchor on Privy's side
    assert body["chain_type"] == "solana"


@respx.mock
def test_grant_scope_creates_policy_with_self_only_rules(privy_client: PrivyClient) -> None:
    respx.post(f"{_BASE}/v1/wallets").mock(return_value=httpx.Response(200, json=_wallet_body()))
    policy_route = respx.post(f"{_BASE}/v1/policies").mock(
        return_value=httpx.Response(200, json=_policy_body())
    )
    attach_route = respx.patch(f"{_BASE}/v1/wallets/{_WALLET_ID}").mock(
        return_value=httpx.Response(200, json=_wallet_body())
    )
    adapter = PrivyWalletAdapter(privy_client, store=GrantStore())
    adapter.link(USER, USER_ADDR)

    scope = adapter.grant_scope(USER, user_scope(USER_ADDR))

    assert policy_route.called and attach_route.called
    assert scope.revoked is False

    import json as _json

    create_body = _json.loads(policy_route.calls.last.request.content)
    # Live Privy v2 POST /v1/policies REQUIRES a top-level version="1.0".
    assert create_body["version"] == "1.0"
    assert create_body["chain_type"] == "solana"

    rules = create_body["rules"]
    # Corrected wire shape: NO `neq` and NO explicit non-self transfer DENY —
    # non-self transfers are denied by Privy deny-by-default. Every transfer
    # ALLOW pins the destination to the user's own address with `eq`.
    assert all(c["operator"] != "neq" for r in rules for c in r["conditions"]), (
        "no rule may use the unsupported `neq` operator"
    )
    transfer_allow_dests = {
        c["value"]
        for r in rules
        if r["action"] == "ALLOW"
        for c in r["conditions"]
        if c["field"] in ("Transfer.destination", "Transfer.to")
    }
    assert transfer_allow_dests == {USER_ADDR}, "transfer ALLOWs must pin self only"

    # attach payload references exactly the created policy
    attach_body = _json.loads(attach_route.calls.last.request.content)
    assert attach_body["policy_ids"] == [_POLICY_ID]


@respx.mock
def test_grant_scope_requires_link(privy_client: PrivyClient) -> None:
    adapter = PrivyWalletAdapter(privy_client, store=GrantStore())
    with pytest.raises(NotLinkedError):
        adapter.grant_scope(USER, user_scope(USER_ADDR))


@respx.mock
def test_scope_for_none_then_reflects_grant(privy_client: PrivyClient) -> None:
    respx.post(f"{_BASE}/v1/wallets").mock(return_value=httpx.Response(200, json=_wallet_body()))
    respx.post(f"{_BASE}/v1/policies").mock(return_value=httpx.Response(200, json=_policy_body()))
    respx.patch(f"{_BASE}/v1/wallets/{_WALLET_ID}").mock(
        return_value=httpx.Response(200, json=_wallet_body())
    )
    adapter = PrivyWalletAdapter(privy_client, store=GrantStore())

    assert adapter.scope_for(USER) is None  # never linked
    adapter.link(USER, USER_ADDR)
    assert adapter.scope_for(USER) is None  # linked, not granted

    adapter.grant_scope(USER, user_scope(USER_ADDR))
    s = adapter.scope_for(USER)
    assert s is not None and USER_ADDR in s.withdraw_allowlist and s.revoked is False


@respx.mock
def test_revoke_rewrites_policy_to_deny_all_and_reflects(privy_client: PrivyClient) -> None:
    respx.post(f"{_BASE}/v1/wallets").mock(return_value=httpx.Response(200, json=_wallet_body()))
    respx.post(f"{_BASE}/v1/policies").mock(return_value=httpx.Response(200, json=_policy_body()))
    respx.patch(f"{_BASE}/v1/wallets/{_WALLET_ID}").mock(
        return_value=httpx.Response(200, json=_wallet_body())
    )
    revoke_route = respx.patch(f"{_BASE}/v1/policies/{_POLICY_ID}").mock(
        return_value=httpx.Response(200, json=_policy_body())
    )
    adapter = PrivyWalletAdapter(privy_client, store=GrantStore())
    adapter.link(USER, USER_ADDR)
    adapter.grant_scope(USER, user_scope(USER_ADDR))

    adapter.revoke(USER)

    # Revoke genuinely removes authority on Privy: the attached policy's rules
    # are rewritten to a single deny-all (method "*", DENY). The policy STAYS
    # attached (no detach → no permissionless-signing widening).
    assert revoke_route.called
    import json as _json

    sent_rules = _json.loads(revoke_route.calls.last.request.content)["rules"]
    assert sent_rules == [
        {"name": "revoked-deny-all", "method": "*", "conditions": [], "action": "DENY"}
    ]
    # locally observable
    assert adapter.scope_for(USER).revoked is True


@respx.mock
def test_revoke_noop_without_grant(privy_client: PrivyClient) -> None:
    respx.post(f"{_BASE}/v1/wallets").mock(return_value=httpx.Response(200, json=_wallet_body()))
    policy_patch = respx.patch(f"{_BASE}/v1/policies/{_POLICY_ID}").mock(
        return_value=httpx.Response(200, json=_policy_body())
    )
    adapter = PrivyWalletAdapter(privy_client, store=GrantStore())
    adapter.link(USER, USER_ADDR)

    adapter.revoke(USER)  # linked but never granted → no policy to touch

    assert not policy_patch.called


@respx.mock
def test_execute_is_signing_gated(privy_client: PrivyClient) -> None:
    adapter = _make_adapter(privy_client, granted=True)
    with pytest.raises(NotImplementedError, match="privy signing — gated task D4"):
        adapter.execute(USER, "kamino_deposit", 100.0)


@respx.mock
def test_withdraw_to_self_is_signing_gated(privy_client: PrivyClient) -> None:
    adapter = _make_adapter(privy_client, granted=True)
    # withdraw-to-self passes the allowlist guard, then hits the signing gate.
    with pytest.raises(NotImplementedError, match="privy signing — gated task D4"):
        adapter.withdraw(USER, 50.0, USER_ADDR)


@respx.mock
def test_execute_out_of_scope_blocks_before_gate(privy_client: PrivyClient) -> None:
    adapter = _make_adapter(privy_client, granted=True)
    # Out-of-scope action is a ScopeError (guard runs BEFORE the signing gate).
    with pytest.raises(ScopeError):
        adapter.execute(USER, "send_to_anyone", 100.0)


@respx.mock
def test_withdraw_to_other_blocks_before_gate(privy_client: PrivyClient) -> None:
    adapter = _make_adapter(privy_client, granted=True)
    with pytest.raises(ScopeError):
        adapter.withdraw(USER, 50.0, EVIL_ADDR)


# ---------------------------------------------------------------------------
# 2. Conformance — same non-custodial invariants as the stub, over BOTH impls.
#
# The stub's `execute`/`withdraw` SUCCEED; the adapter's signing path is gated
# (NotImplementedError). So the shared invariants are the SAFETY ones (block
# out-of-scope, block non-self withdraw, revoke removes authority, custody
# user-owned). The "happy-path signing succeeds" assertions are stub-only and
# intentionally NOT parametrized — the adapter ships no half-real signing.
# ---------------------------------------------------------------------------


def _linked_stub() -> StubWalletProvider:
    p = StubWalletProvider()
    p.link(USER, USER_ADDR)
    p.grant_scope(USER, user_scope(USER_ADDR))
    return p


def _register_privy_routes(router: respx.Router) -> None:
    """Register every Privy endpoint the adapter touches across link/grant/
    revoke/re-link, so conformance test bodies can drive the adapter freely."""
    router.post(f"{_BASE}/v1/wallets").mock(return_value=httpx.Response(200, json=_wallet_body()))
    router.post(f"{_BASE}/v1/policies").mock(return_value=httpx.Response(200, json=_policy_body()))
    router.patch(f"{_BASE}/v1/wallets/{_WALLET_ID}").mock(
        return_value=httpx.Response(200, json=_wallet_body())
    )
    router.patch(f"{_BASE}/v1/policies/{_POLICY_ID}").mock(
        return_value=httpx.Response(200, json=_policy_body())
    )


@pytest.fixture(params=["stub", "privy"])
def provider(request: pytest.FixtureRequest, privy_client: PrivyClient) -> Iterator[WalletProvider]:
    """A linked+granted provider of each kind, for shared-invariant tests.

    For the privy param, respx stays active for the WHOLE test body so the
    adapter's revoke/re-link Privy calls are mocked too — never the network.
    """
    if request.param == "stub":
        yield _linked_stub()
        return
    with respx.mock as router:
        _register_privy_routes(router)
        adapter = PrivyWalletAdapter(privy_client, store=GrantStore())
        adapter.link(USER, USER_ADDR)
        adapter.grant_scope(USER, user_scope(USER_ADDR))
        yield adapter


def test_conformance_satisfies_protocol(provider: WalletProvider) -> None:
    assert isinstance(provider, WalletProvider)


def test_conformance_custody_is_user_owned(provider: WalletProvider) -> None:
    link = provider.link(USER, USER_ADDR)
    assert link.custody == "user-owned"
    assert not any("key" in f.lower() or "secret" in f.lower() for f in vars(link))


def test_conformance_out_of_scope_blocked(provider: WalletProvider) -> None:
    # Both impls block an out-of-scope action with ScopeError, BEFORE any sign.
    with pytest.raises(ScopeError):
        provider.execute(USER, "send_to_anyone", 100.0)


def test_conformance_withdraw_to_other_blocked(provider: WalletProvider) -> None:
    # Allowlist-only: exfiltration to a foreign address is a ScopeError on both.
    with pytest.raises(ScopeError):
        provider.withdraw(USER, 50.0, EVIL_ADDR)


def test_conformance_revoke_blocks_execute_and_withdraw(provider: WalletProvider) -> None:
    provider.revoke(USER)
    # After revoke, BOTH impls raise RevokedError from the live-scope guard
    # (which runs before the signing gate), so the contract holds identically.
    with pytest.raises(RevokedError):
        provider.execute(USER, "kamino_deposit", 1.0)
    with pytest.raises(RevokedError):
        provider.withdraw(USER, 1.0, USER_ADDR)


def test_conformance_scope_for_reflects_revoke(provider: WalletProvider) -> None:
    s = provider.scope_for(USER)
    assert s is not None and s.revoked is False
    provider.revoke(USER)
    after = provider.scope_for(USER)
    assert after is not None and after.revoked is True
