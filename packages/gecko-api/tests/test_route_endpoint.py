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
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_TEST_WALLET")
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
    r = client.get("/.well-known/x402")
    assert r.status_code == 200
    routes = {entry["route"]: entry for entry in r.json()["routes"]}
    assert "POST /route" in routes
    prices = {a["price"] for a in routes["POST /route"]["accepts"]}
    assert "$0.02" in prices


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
