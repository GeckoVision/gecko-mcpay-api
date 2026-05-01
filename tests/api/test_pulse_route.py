"""S14-PULSE-01 / S14-PULSE-04 — POST /pulse route + Bazaar listing.

Covers:
  * /pulse is registered on x402 at $0.50 in stub mode.
  * /.well-known/x402 advertises the route.
  * The Bazaar extension is attached with the right tags.
  * 402 path: an unpaid POST returns 402.
"""

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
    # Unset wallet so settings falls through to the stub sentinel that the
    # well-formed-payTo assertion bypasses.
    os.environ.pop("GECKO_WALLET_ADDRESS", None)
    os.environ.pop("GECKO_WALLET_ADDRESS_BASE", None)
    os.environ["X402_NETWORK"] = "solana-devnet"
    # S14-PULSE-01 — flip pulse to a non-zero price so the route is x402-gated.
    os.environ["PULSE_CALL_PRICE"] = "$0.50"
    _purge_gecko_api_modules()

    from gecko_api.main import app

    with TestClient(app) as c:
        yield c


def test_pulse_route_advertised_in_well_known(client: TestClient) -> None:
    r = client.get("/.well-known/x402")
    assert r.status_code == 200
    body = r.json()
    routes = {entry["route"]: entry for entry in body["routes"]}
    assert "POST /pulse" in routes
    prices = {a["price"] for a in routes["POST /pulse"]["accepts"]}
    assert "$0.50" in prices


def test_pulse_route_carries_bazaar_extension(client: TestClient) -> None:
    """S14-PULSE-04: Bazaar extension surfaces description + tags."""
    r = client.get("/.well-known/x402")
    body = r.json()
    routes = {entry["route"]: entry for entry in body["routes"]}
    ext = routes["POST /pulse"].get("bazaarExtension")
    assert ext is not None
    assert ext["description"]
    # Tags speak the lifecycle-monetization story Sprint 14 ships.
    assert "pulse" in ext["tags"]
    assert "recurring-validation" in ext["tags"]
    assert "during-build" in ext["tags"]


def test_pulse_route_returns_402_without_payment(client: TestClient) -> None:
    r = client.post(
        "/pulse",
        json={"session_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 402


def test_bazaar_extension_describes_pulse_input_output() -> None:
    """The static Bazaar registry carries the v14 PulseResult shape."""
    from gecko_api.bazaar import BAZAAR_EXTENSIONS

    ext = BAZAAR_EXTENSIONS["POST /pulse"]
    schema = ext.schema_
    assert "input" in schema["properties"]
    assert "output" in schema["properties"]
    output_props = schema["properties"]["output"]["properties"]
    assert "verdict" in output_props
    assert "gap_classification" in output_props
    assert "parent_session_id" in output_props
    assert "pulse_session_id" in output_props
    assert "summary_bullets" in output_props
