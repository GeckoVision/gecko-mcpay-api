"""S13-COMMO-01 — paid POST /advise route registers + carries default $0.05."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


def _purge_gecko_api_modules() -> None:
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    os.environ["X402_MODE"] = "stub"
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_TEST_WALLET"
    # Force a Solana network so the x402 lib's scheme-registration check
    # passes — `_build_resource_server` only registers `solana:*`. Without
    # this an env-leaked base-mainnet from a sibling test trips
    # RouteConfigurationError on app import.
    os.environ["X402_NETWORK"] = "solana-devnet"
    os.environ.pop("ADVISOR_VOICE_PRICE", None)
    _purge_gecko_api_modules()

    from gecko_api.main import app

    with TestClient(app) as c:
        yield c


def test_advise_route_advertised_in_well_known(client: TestClient) -> None:
    r = client.get("/.well-known/x402")
    assert r.status_code == 200
    body = r.json()
    routes = {entry["route"]: entry for entry in body["routes"]}
    assert "POST /advise" in routes
    prices = {a["price"] for a in routes["POST /advise"]["accepts"]}
    assert "$0.05" in prices


def test_advise_route_carries_bazaar_extension(client: TestClient) -> None:
    r = client.get("/.well-known/x402")
    body = r.json()
    routes = {entry["route"]: entry for entry in body["routes"]}
    ext = routes["POST /advise"].get("bazaarExtension")
    assert ext is not None
    assert ext["description"]
    assert "advisor-voice" in ext["tags"]


def test_advise_route_returns_402_without_payment(client: TestClient) -> None:
    r = client.post(
        "/advise",
        json={
            "session_id": "00000000-0000-0000-0000-000000000000",
            "voice": "cto",
        },
    )
    assert r.status_code == 402
