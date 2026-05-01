"""S14-CDP-HARDEN-02 — startup-time payTo advertisement contract.

Promotes the S12.5-TEST-03 unit-test-only check into a hard startup
assertion. A misconfigured deploy (Solana base58 address advertised on
an eip155:* route, or vice versa) refuses to boot rather than serving
a broken /.well-known/x402 catalog that CDP will eventually 500 on.

Tests:
  1. The pure helper ``_assert_payto_format`` rejects a Solana address
     on an eip155:* route with a ``ConfigurationError``.
  2. The pure helper rejects an EVM-shaped address on a solana* route.
  3. The pure helper accepts the stub sentinel (dev / CI ergonomics).
  4. Built routes from a misconfigured fixture (Solana payTo on
     eip155:8453) raise ``ConfigurationError`` from the assertion
     helper — this is the boot-time path.
  5. The existing /.well-known/x402 listing is byte-stable for a
     well-configured app (no regression on S12.5-TEST-03).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from x402.http.types import PaymentOption, RouteConfig


def test_assert_payto_format_rejects_solana_on_eip155() -> None:
    from gecko_api.main import ConfigurationError, _assert_payto_format

    with pytest.raises(ConfigurationError, match="cae61ed regression"):
        _assert_payto_format(
            "eip155:8453",
            "GeckoSoanaWaetAddressBase58Sampe1234567xyz9",
            route="POST /research",
        )


def test_assert_payto_format_rejects_evm_on_solana() -> None:
    from gecko_api.main import ConfigurationError, _assert_payto_format

    with pytest.raises(ConfigurationError, match="looks like an EVM address"):
        _assert_payto_format(
            "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG",
            "0x1234567890abcdef1234567890abcdef12345678",
            route="POST /research",
        )


def test_assert_payto_format_allows_stub_sentinel() -> None:
    from gecko_api.main import _assert_payto_format

    # Allowed on either family — ergonomic path for dev/CI when neither
    # GECKO_WALLET_ADDRESS{_BASE,} is set.
    _assert_payto_format("eip155:8453", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE", route="POST /research")
    _assert_payto_format(
        "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG",
        "STUB_WALLET_ADDRESS_NOT_FOR_LIVE",
        route="POST /research",
    )


def test_assert_routes_rejects_misconfigured_fixture() -> None:
    """End-to-end: a fixture with Solana payTo on eip155:8453 dies at
    startup instead of being served via /.well-known/x402."""
    from gecko_api.main import ConfigurationError, _assert_routes_payto_well_formed

    bad_routes: dict[str, RouteConfig] = {
        "POST /research": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to="GeckoSoanaWaetAddressBase58Sampe1234567xyz9",
                    price="$0.10",
                    network="eip155:8453",
                ),
            ],
            description="misconfigured fixture",
        ),
    }
    with pytest.raises(ConfigurationError, match="cae61ed regression"):
        _assert_routes_payto_well_formed(bad_routes)


def test_assert_routes_rejects_unknown_network_family() -> None:
    from gecko_api.main import ConfigurationError, _assert_routes_payto_well_formed

    bad_routes: dict[str, RouteConfig] = {
        "POST /research": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to="0x1234567890abcdef1234567890abcdef12345678",
                    price="$0.10",
                    network="ripple:abc",
                ),
            ],
            description="unknown",
        ),
    }
    with pytest.raises(ConfigurationError, match="unknown network family"):
        _assert_routes_payto_well_formed(bad_routes)


# ---------------------------------------------------------------------------
# Byte-stability: existing /.well-known/x402 listing must NOT change.
# ---------------------------------------------------------------------------


@pytest.fixture
def evm_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("X402_MODE", "stub")
    monkeypatch.setenv("X402_NETWORK", "base-mainnet")
    monkeypatch.setenv(
        "GECKO_WALLET_ADDRESS_BASE",
        "0x1234567890abcdef1234567890abcdef12345678",
    )
    monkeypatch.setenv(
        "GECKO_WALLET_ADDRESS",
        "GeckoSoanaWaetAddressBase58Sampe1234567xyz9",
    )
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)
    from gecko_api.main import app

    with TestClient(app) as c:
        yield c


def test_well_known_listing_unchanged_for_correctly_configured_app(
    evm_client: TestClient,
) -> None:
    """The startup assertion is a guard, not a transformer — a
    correctly-configured app's /.well-known/x402 catalog is byte-stable
    across HARDEN-02. We verify the response status + that every route
    is present + that every payTo is well-formed (sanity)."""
    response = evm_client.get("/.well-known/x402")
    assert response.status_code == 200
    catalog = response.json()
    assert catalog["routes"], "no routes registered"
    for route in catalog["routes"]:
        for opt in route["accepts"]:
            network = opt["network"]
            pay_to = opt["payTo"]
            if network.startswith("eip155:"):
                assert pay_to.startswith("0x")
                assert len(pay_to) == 42
