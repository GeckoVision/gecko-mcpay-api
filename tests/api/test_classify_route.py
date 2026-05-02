"""S13-COMMO-03 — paid POST /classify route registers + Bazaar metadata."""

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
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_WALLET_ADDRESS_NOT_FOR_LIVE"
    os.environ["X402_NETWORK"] = "solana-devnet"
    os.environ.pop("CLASSIFY_CALL_PRICE", None)
    _purge_gecko_api_modules()

    from gecko_api.main import app

    with TestClient(app) as c:
        yield c


def test_classify_route_advertised_with_default_price(client: TestClient) -> None:
    r = client.get("/.well-known/x402")
    body = r.json()
    routes = {entry["route"]: entry for entry in body["routes"]}
    assert "POST /classify" in routes
    prices = {a["price"] for a in routes["POST /classify"]["accepts"]}
    assert "$0.10" in prices


def test_classify_route_carries_bazaar_extension(client: TestClient) -> None:
    r = client.get("/.well-known/x402")
    body = r.json()
    routes = {entry["route"]: entry for entry in body["routes"]}
    ext = routes["POST /classify"].get("bazaarExtension")
    assert ext is not None
    assert "classification" in ext["tags"]
    # Output schema must declare the required keys for the paid surface.
    output_props = ext["schema"]["properties"]["output"]["properties"]
    assert "categories" in output_props
    assert "suggested_sources" in output_props
    assert "priority_weights" in output_props


def test_classify_route_returns_402_without_payment(client: TestClient) -> None:
    r = client.post(
        "/classify",
        json={"idea": "An on-chain reputation system for autonomous AI agents"},
    )
    assert r.status_code == 402
