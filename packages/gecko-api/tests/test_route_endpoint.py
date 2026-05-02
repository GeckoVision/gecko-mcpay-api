"""Tests for the POST /route endpoint (S4-ROUTE-02).

Asserts:
    1. Unpaid POST /route returns 402 with a parseable PaymentRequired header.
    2. Paid POST /route (stub-mode payload) returns 200 + RouteResult shape.
    3. /.well-known/x402 advertises POST /route at the configured flat price.
    4. Bad task_hint returns 400 (after settle — the validation runs in the
       handler).

Mocks `gecko_core.routing.route` so this never touches OpenAI / OpenRouter.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Force stub mode BEFORE importing the app — settings are frozen at import time.
os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")
os.environ.pop("RESEARCH_BASIC_PRICE", None)
os.environ.pop("RESEARCH_PRO_PRICE", None)
os.environ.pop("ROUTE_CALL_PRICE", None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Purge cached gecko_api modules so the price defaults take effect.
    os.environ.pop("RESEARCH_BASIC_PRICE", None)
    os.environ.pop("RESEARCH_PRO_PRICE", None)
    os.environ.pop("ROUTE_CALL_PRICE", None)
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)

    from gecko_api.main import app
    from gecko_core.routing.models import RouteResult

    fake_result = RouteResult(
        response="hello",
        model_used="gpt-4o-mini",
        model_requested="gpt-4o-mini",
        cost_usd=0.0009,
        usage_cost_usd=0.0010,
        upstream_cost_usd=None,
        tokens_in=50,
        tokens_out=80,
        savings_vs_premium=0.005,
    )

    with (
        patch(
            "gecko_core.routing.route",
            new=AsyncMock(return_value=fake_result),
        ),
        TestClient(app) as c,
    ):
        yield c


def _decode_payment_required_header(value: str) -> dict:
    return json.loads(base64.b64decode(value).decode("utf-8"))


def _build_payment_payload_header(accepts_entry: dict) -> str:
    payload_obj = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
        "accepted": accepts_entry,
    }
    return base64.b64encode(json.dumps(payload_obj).encode("utf-8")).decode("utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unpaid_route_returns_402(client: TestClient) -> None:
    r = client.post("/route", json={"prompt": "hello there"})
    assert r.status_code == 402
    header_value = r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
    assert header_value, f"missing PAYMENT-REQUIRED header; got {dict(r.headers)}"
    decoded = _decode_payment_required_header(header_value)
    assert decoded["accepts"]
    networks = {entry.get("network") for entry in decoded["accepts"]}
    assert any("solana" in n for n in networks if n)


def test_paid_route_returns_route_result_shape(client: TestClient) -> None:
    r0 = client.post("/route", json={"prompt": "hello there"})
    assert r0.status_code == 402
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    payment_header = _build_payment_payload_header(accepts_entry)

    r = client.post(
        "/route",
        json={
            "prompt": "hello there",
            "task_hint": "default",
            "max_cost_usd": 0.05,
            "prefer_premium": False,
        },
        headers={"PAYMENT-SIGNATURE": payment_header},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # RouteResult shape — every documented field present.
    for field in (
        "response",
        "model_used",
        "model_requested",
        "cost_usd",
        "usage_cost_usd",
        "upstream_cost_usd",
        "tokens_in",
        "tokens_out",
        "savings_vs_premium",
    ):
        assert field in body, f"missing {field} in RouteResult JSON: {body}"
    assert body["response"] == "hello"
    assert body["model_used"] == "gpt-4o-mini"
    assert body["usage_cost_usd"] == pytest.approx(0.0010)


def test_well_known_advertises_route_endpoint(client: TestClient) -> None:
    """S5-API-03: three /route paths advertised at three different prices.

    Default tier $0.01, premium tier $0.05, upgrade tier $0.20 — heavy
    callers (prefer_premium) pay the most, light callers (default) pay
    the least. Sprint 4 shipped a single $0.02 flat; this is the
    Sprint 5 split.
    """
    r = client.get("/.well-known/x402")
    assert r.status_code == 200
    routes = {entry["route"]: entry for entry in r.json()["routes"]}
    assert "POST /route" in routes
    assert "POST /route/premium" in routes
    assert "POST /route/upgrade" in routes
    default_prices = {a["price"] for a in routes["POST /route"]["accepts"]}
    premium_prices = {a["price"] for a in routes["POST /route/premium"]["accepts"]}
    upgrade_prices = {a["price"] for a in routes["POST /route/upgrade"]["accepts"]}
    assert "$0.01" in default_prices
    assert "$0.05" in premium_prices
    assert "$0.20" in upgrade_prices


def test_paid_route_premium_returns_route_result_with_tier(client: TestClient) -> None:
    """S5-API-03: /route/premium charges $0.05 + surfaces tier_charged."""
    r0 = client.post("/route/premium", json={"prompt": "refactor this"})
    assert r0.status_code == 402
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    # x402 atomic units: $0.05 USDC = 50_000.
    assert accepts_entry["amount"] == "50000"
    payment_header = _build_payment_payload_header(accepts_entry)

    r = client.post(
        "/route/premium",
        json={"prompt": "refactor this", "task_hint": "code"},
        headers={"PAYMENT-SIGNATURE": payment_header},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier_charged"] == "premium"
    assert body["prepay_usd"] == pytest.approx(0.05)


def test_paid_route_upgrade_returns_route_result_with_tier(client: TestClient) -> None:
    """S5-API-03: /route/upgrade charges $0.20 + surfaces tier_charged."""
    r0 = client.post("/route/upgrade", json={"prompt": "deep think"})
    assert r0.status_code == 402
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    # x402 atomic units: $0.20 USDC = 200_000.
    assert accepts_entry["amount"] == "200000"
    payment_header = _build_payment_payload_header(accepts_entry)

    r = client.post(
        "/route/upgrade",
        json={
            "prompt": "deep think",
            "task_hint": "reasoning",
            "prefer_premium": True,
        },
        headers={"PAYMENT-SIGNATURE": payment_header},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier_charged"] == "upgrade"
    assert body["prepay_usd"] == pytest.approx(0.20)


def test_paid_route_default_includes_tier_charged(client: TestClient) -> None:
    """S5-API-03: legacy /route path tags the response with `default` tier."""
    r0 = client.post("/route", json={"prompt": "hello there"})
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    payment_header = _build_payment_payload_header(accepts_entry)
    r = client.post(
        "/route",
        json={"prompt": "hello there", "task_hint": "default"},
        headers={"PAYMENT-SIGNATURE": payment_header},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier_charged"] == "default"
    assert body["prepay_usd"] == pytest.approx(0.01)


def test_paid_route_rejects_unknown_task_hint(client: TestClient) -> None:
    r0 = client.post("/route", json={"prompt": "hello there"})
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    payment_header = _build_payment_payload_header(accepts_entry)

    r = client.post(
        "/route",
        json={"prompt": "hello there", "task_hint": "bogus"},
        headers={"PAYMENT-SIGNATURE": payment_header},
    )
    # Pydantic accepts the string (we don't enum-validate at request layer
    # to keep wire-shape forgiving); the handler returns 400.
    assert r.status_code == 400, r.text
    assert "task_hint" in r.text
