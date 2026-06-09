"""Tests for gecko_core.wallets.privy (S2-05).

No live network calls. We mock Privy's REST surface with respx so the
tests assert request shape (method/path/headers/body) rather than relying
on the real API.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime

import httpx
import pytest
import respx
from gecko_core.wallets.privy import (
    PrivyClient,
    PrivyClientError,
    PrivyNotConfiguredError,
    PrivyPolicy,
    PrivyWallet,
    is_privy_configured,
)

PRIVY_BASE = "https://api.privy.io"


# ---------------------------------------------------------------------------
# Sentinel detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "app_id, app_secret, expected",
    [
        ("app123", "secret123", True),
        ("", "secret123", False),
        ("app123", "", False),
        ("__unset__", "secret123", False),
        ("app123", "__unset__", False),
        ("__dev_change_me__", "secret", False),
        ("  app123  ", "  secret  ", True),  # stripped before check
    ],
)
def test_is_privy_configured_sentinels(
    app_id: str | None,
    app_secret: str | None,
    expected: bool,
) -> None:
    assert is_privy_configured(app_id=app_id, app_secret=app_secret) is expected


def test_is_privy_configured_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Args=None falls back to the process environment; sentinels still detected."""
    monkeypatch.delenv("PRIVY_APP_ID", raising=False)
    monkeypatch.delenv("PRIVY_APP_SECRET", raising=False)
    assert is_privy_configured(app_id=None, app_secret=None) is False
    monkeypatch.setenv("PRIVY_APP_ID", "real-id")
    monkeypatch.setenv("PRIVY_APP_SECRET", "real-secret")
    assert is_privy_configured(app_id=None, app_secret=None) is True
    monkeypatch.setenv("PRIVY_APP_SECRET", "__unset__")
    assert is_privy_configured(app_id=None, app_secret=None) is False


def test_constructor_refuses_sentinel() -> None:
    with pytest.raises(PrivyNotConfiguredError):
        PrivyClient(app_id="__unset__", app_secret="real-secret")
    with pytest.raises(PrivyNotConfiguredError):
        PrivyClient(app_id="real-app", app_secret="")


# ---------------------------------------------------------------------------
# Auth header construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_headers_basic_plus_privy_app_id() -> None:
    client = PrivyClient(app_id="cmapp123", app_secret="topsecret")
    try:
        headers = client._auth_headers()
    finally:
        await client.aclose()

    expected = base64.b64encode(b"cmapp123:topsecret").decode()
    assert headers["Authorization"] == f"Basic {expected}"
    assert headers["privy-app-id"] == "cmapp123"
    assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# create_solana_wallet — request shape + response parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_solana_wallet_sends_external_id_no_owner() -> None:
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        route = router.post("/v1/wallets").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "wallet-abc",
                    "address": "SoLaNa1111111111111111111111111111111111111",
                    "chain_type": "solana",
                    "created_at": "2026-04-28T12:00:00Z",
                },
            )
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            wallet = await client.create_solana_wallet(owner_label="proj-uuid-123")

    assert isinstance(wallet, PrivyWallet)
    assert wallet.wallet_id == "wallet-abc"
    assert wallet.address.startswith("SoLaNa")
    assert wallet.chain_type == "solana"
    assert isinstance(wallet.created_at, datetime)

    # Inspect the request shape: app-owned wallet, no `owner` field.
    call = route.calls.last
    body = call.request.read()
    import json as _json

    parsed = _json.loads(body)
    assert parsed == {"chain_type": "solana", "external_id": "proj-uuid-123"}
    assert "owner" not in parsed
    # Auth headers present.
    assert call.request.headers["privy-app-id"] == "cmapp"
    assert call.request.headers["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_create_solana_wallet_propagates_4xx_verbatim() -> None:
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        router.post("/v1/wallets").mock(
            return_value=httpx.Response(
                409,
                json={"error": "external_id already exists"},
            )
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            with pytest.raises(PrivyClientError) as excinfo:
                await client.create_solana_wallet(owner_label="dup")

    # Body preserved verbatim — callers above key off this message.
    assert "409" in str(excinfo.value)
    assert "external_id" in str(excinfo.value)


@pytest.mark.asyncio
async def test_get_wallet_returns_parsed_model() -> None:
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        router.get("/v1/wallets/wallet-abc").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "wallet-abc",
                    "address": "Sol123",
                    "chain_type": "solana",
                },
            )
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            wallet = await client.get_wallet("wallet-abc")

    assert wallet.wallet_id == "wallet-abc"
    assert wallet.address == "Sol123"


@pytest.mark.asyncio
async def test_create_rejects_non_solana_chain_response() -> None:
    """Defensive: if Privy somehow returns chain_type != solana, fail loud."""
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        router.post("/v1/wallets").mock(
            return_value=httpx.Response(
                200,
                json={"id": "w1", "address": "0xabc", "chain_type": "ethereum"},
            )
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            with pytest.raises(PrivyClientError, match="chain_type"):
                await client.create_solana_wallet(owner_label="x")


@pytest.mark.asyncio
async def test_get_wallet_balance_not_implemented() -> None:
    """Balance reads must go via Solana RPC, not Privy — until that wires up."""
    async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
        with pytest.raises(NotImplementedError):
            await client.get_wallet_balance("wallet-abc")


# ---------------------------------------------------------------------------
# S26-B — Scoped policies (create_policy + attach_policy_to_wallet)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_policy_sends_rules_verbatim() -> None:
    """Rules are passed through to Privy without local validation."""
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        route = router.post("/v1/policies").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "policy-abc",
                    "name": "gecko-trade-agent-scope",
                    "chain_type": "solana",
                    "created_at": "2026-05-31T08:00:00Z",
                },
            )
        )
        rules = [
            {"action": "signAndSendTransaction", "method": "allow"},
            {
                "action": "transfer",
                "asset": "USDC",
                "max_amount_per_session": 50.0,
            },
        ]
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            policy = await client.create_policy(
                name="gecko-trade-agent-scope",
                rules=rules,
            )

    assert isinstance(policy, PrivyPolicy)
    assert policy.policy_id == "policy-abc"
    assert policy.name == "gecko-trade-agent-scope"
    assert policy.chain_type == "solana"

    call = route.calls.last
    import json as _json

    body = _json.loads(call.request.read())
    assert body == {
        "version": "1.0",
        "name": "gecko-trade-agent-scope",
        "chain_type": "solana",
        "rules": rules,
    }
    assert call.request.headers["privy-app-id"] == "cmapp"


@pytest.mark.asyncio
async def test_create_policy_rejects_non_solana_chain() -> None:
    """gecko-core is Solana-only per S2-05; create_policy enforces it."""
    async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
        with pytest.raises(PrivyClientError, match="chain_type"):
            await client.create_policy(
                name="evm-scope",
                rules=[{"action": "allow"}],
                chain_type="ethereum",
            )


@pytest.mark.asyncio
async def test_create_policy_propagates_4xx_verbatim() -> None:
    """Privy validation errors (e.g. malformed rule) surface to the caller."""
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        router.post("/v1/policies").mock(
            return_value=httpx.Response(
                400,
                json={"error": "rule schema invalid"},
            )
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            with pytest.raises(PrivyClientError) as excinfo:
                await client.create_policy(name="bad", rules=[{}])

    assert "400" in str(excinfo.value)
    assert "rule schema invalid" in str(excinfo.value)


@pytest.mark.asyncio
async def test_attach_policy_patches_wallet_with_policy_ids() -> None:
    """PATCH /v1/wallets/{wallet_id} with the FULL policy list (not delta)."""
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        route = router.patch("/v1/wallets/wallet-abc").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "wallet-abc",
                    "address": "SoLaNa11111111111111111111111111111111111",
                    "chain_type": "solana",
                    "policy_ids": ["policy-1", "policy-2"],
                },
            )
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            wallet = await client.attach_policy_to_wallet(
                wallet_id="wallet-abc",
                policy_ids=["policy-1", "policy-2"],
            )

    assert isinstance(wallet, PrivyWallet)
    assert wallet.wallet_id == "wallet-abc"

    call = route.calls.last
    import json as _json

    body = _json.loads(call.request.read())
    assert body == {"policy_ids": ["policy-1", "policy-2"]}
    assert call.request.method == "PATCH"


@pytest.mark.asyncio
async def test_attach_policy_refuses_empty_list_footgun() -> None:
    """Empty policy_ids would silently remove all enforcement — refuse."""
    async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
        with pytest.raises(PrivyClientError, match="empty policy_ids"):
            await client.attach_policy_to_wallet(
                wallet_id="wallet-abc",
                policy_ids=[],
            )


@pytest.mark.asyncio
async def test_attach_policy_propagates_404_unknown_wallet() -> None:
    """Privy 404 on unknown wallet_id surfaces verbatim."""
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        router.patch("/v1/wallets/nope").mock(
            return_value=httpx.Response(
                404,
                json={"error": "wallet not found"},
            )
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            with pytest.raises(PrivyClientError) as excinfo:
                await client.attach_policy_to_wallet(
                    wallet_id="nope",
                    policy_ids=["policy-1"],
                )

    assert "404" in str(excinfo.value)


@pytest.mark.asyncio
async def test_create_policy_handles_missing_optional_fields() -> None:
    """name + created_at are optional in the response; parser tolerates absence."""
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        router.post("/v1/policies").mock(
            return_value=httpx.Response(
                200,
                json={"id": "policy-xyz", "chain_type": "solana"},
            )
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            policy = await client.create_policy(name="x", rules=[])

    assert policy.policy_id == "policy-xyz"
    assert policy.name is None
    assert policy.created_at is None


# ---------------------------------------------------------------------------
# L2 — devnet-gated signing (sign_and_send_solana_devnet)
#
# Production signing stays gated; this method is ONLY armed by the explicit
# GECKO_PRIVY_SIGNING_DEVNET=1 env flag and ONLY targets Solana devnet.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sign_and_send_devnet_refuses_without_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent GECKO_PRIVY_SIGNING_DEVNET=1, signing refuses BEFORE any network."""
    from gecko_core.wallets.privy import PrivySigningNotArmedError

    monkeypatch.delenv("GECKO_PRIVY_SIGNING_DEVNET", raising=False)
    # No respx mock: a network call would error loudly, proving the guard
    # short-circuits before the POST.
    async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
        with pytest.raises(PrivySigningNotArmedError):
            await client.sign_and_send_solana_devnet(wallet_id="w1", b64_tx="AAAA")


@pytest.mark.asyncio
async def test_sign_and_send_devnet_posts_to_rpc_with_devnet_caip2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Armed: POSTs signAndSendTransaction to /rpc with the DEVNET caip2."""
    from gecko_core.wallets.privy import SOLANA_DEVNET_CAIP2

    monkeypatch.setenv("GECKO_PRIVY_SIGNING_DEVNET", "1")
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        route = router.post("/v1/wallets/w1/rpc").mock(
            return_value=httpx.Response(200, json={"hash": "sig123"})
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            resp = await client.sign_and_send_solana_devnet(wallet_id="w1", b64_tx="AAAA")

    assert resp == {"hash": "sig123"}
    sent = json.loads(route.calls.last.request.content)
    assert sent["method"] == "signAndSendTransaction"
    assert sent["caip2"] == SOLANA_DEVNET_CAIP2
    assert sent["params"] == {"transaction": "AAAA", "encoding": "base64"}


@pytest.mark.asyncio
async def test_sign_and_send_devnet_propagates_policy_deny_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A policy DENY (non-2xx) surfaces as PrivyClientError with the body intact."""
    monkeypatch.setenv("GECKO_PRIVY_SIGNING_DEVNET", "1")
    async with respx.mock(base_url=PRIVY_BASE, assert_all_called=True) as router:
        router.post("/v1/wallets/w1/rpc").mock(
            return_value=httpx.Response(403, text="transaction violates policy")
        )
        async with PrivyClient(app_id="cmapp", app_secret="sec") as client:
            with pytest.raises(PrivyClientError, match="transaction violates policy"):
                await client.sign_and_send_solana_devnet(wallet_id="w1", b64_tx="AAAA")
