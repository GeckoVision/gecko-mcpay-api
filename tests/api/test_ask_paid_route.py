"""S13-COMMO-02 — paid POST /ask route + free-quota guard on /sessions/{id}/ask."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _purge_gecko_api_modules() -> None:
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    os.environ["X402_MODE"] = "stub"
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_TEST_WALLET"
    os.environ["X402_NETWORK"] = "solana-devnet"
    os.environ.pop("ASK_CALL_PRICE", None)
    os.environ.pop("ASK_FREE_QUOTA_PER_SESSION", None)
    _purge_gecko_api_modules()

    from gecko_api.main import app

    with TestClient(app) as c:
        yield c


def test_paid_ask_route_advertised(client: TestClient) -> None:
    r = client.get("/.well-known/x402")
    assert r.status_code == 200
    body = r.json()
    routes = {entry["route"]: entry for entry in body["routes"]}
    assert "POST /ask" in routes
    prices = {a["price"] for a in routes["POST /ask"]["accepts"]}
    assert "$0.01" in prices


def test_paid_ask_route_carries_bazaar_extension(client: TestClient) -> None:
    r = client.get("/.well-known/x402")
    body = r.json()
    routes = {entry["route"]: entry for entry in body["routes"]}
    ext = routes["POST /ask"].get("bazaarExtension")
    assert ext is not None
    assert "follow-up" in ext["tags"]


def test_paid_ask_route_returns_402_without_payment(client: TestClient) -> None:
    r = client.post(
        "/ask",
        json={
            "session_id": "00000000-0000-0000-0000-000000000000",
            "question": "what next?",
        },
    )
    assert r.status_code == 402


def test_free_ask_under_quota_passes_through() -> None:
    """Under quota, the free `/sessions/{id}/ask` returns the AskResult."""
    os.environ["X402_MODE"] = "stub"
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_TEST_WALLET"
    os.environ["X402_NETWORK"] = "solana-devnet"
    _purge_gecko_api_modules()

    from gecko_api.main import app
    from gecko_core.models import AskResult

    fake_econ = type(
        "Econ",
        (),
        {
            "ask_calls_count": 5,
            "advisor_calls_count": 0,
        },
    )()
    fake_store = AsyncMock()
    fake_store.get_economics = AsyncMock(return_value=fake_econ)

    fake_ask_result = AskResult(
        session_id="00000000-0000-0000-0000-000000000000",
        answer="42",
        citations=[],
    )

    with (
        patch("gecko_api.main.SessionStore.from_env", return_value=fake_store),
        patch("gecko_api.main.gecko_core.ask", new=AsyncMock(return_value=fake_ask_result)),
        patch("gecko_api.main._bump_ask_count", new=AsyncMock(return_value=None)),
        TestClient(app) as c,
    ):
        sid = "00000000-0000-0000-0000-000000000000"
        r = c.post(f"/sessions/{sid}/ask", json={"question": "what next?"})
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "42"


def test_free_ask_over_quota_returns_402_with_paid_route_pointer() -> None:
    """Over quota, returns 402 carrying the paid_route hint."""
    os.environ["X402_MODE"] = "stub"
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_TEST_WALLET"
    os.environ["X402_NETWORK"] = "solana-devnet"
    _purge_gecko_api_modules()

    from gecko_api.main import app

    fake_econ = type("Econ", (), {"ask_calls_count": 100, "advisor_calls_count": 0})()
    fake_store = AsyncMock()
    fake_store.get_economics = AsyncMock(return_value=fake_econ)

    with (
        patch("gecko_api.main.SessionStore.from_env", return_value=fake_store),
        TestClient(app) as c,
    ):
        sid = "00000000-0000-0000-0000-000000000000"
        r = c.post(f"/sessions/{sid}/ask", json={"question": "what next?"})
    assert r.status_code == 402
    body = r.json()
    detail = body.get("detail")
    assert isinstance(detail, dict)
    assert detail["paid_route"] == "POST /ask"
    assert detail["error"] == "ask_quota_exceeded"
