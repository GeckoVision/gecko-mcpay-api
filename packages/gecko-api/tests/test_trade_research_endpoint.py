"""Tests for POST /trade_research (Phase 8b + 10A).

Phase 10A flipped this from a free endpoint to an x402-gated one
($0.25 basic / $0.75 pro) plus a 10/min/IP unauthenticated rate limit.
Mocks ``run_trade_panel_with_retrieval`` so this never fires AG2 or
touches Mongo / OpenAI.
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

# Force stub mode + a stub wallet BEFORE importing the app — settings are
# frozen at import time. Mirrors the test_route_endpoint.py fixture.
os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")


def _decode_payment_required_header(value: str) -> dict:
    return json.loads(base64.b64decode(value).decode("utf-8"))


def _build_payment_payload_header(accepts_entry: dict) -> str:
    """Mirrors test_plan_endpoint's helper — stub-mode signed payload."""
    payload_obj = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
        "accepted": accepts_entry,
    }
    return base64.b64encode(json.dumps(payload_obj).encode("utf-8")).decode("utf-8")


@pytest.fixture
def client() -> Iterator[TestClient]:
    os.environ["X402_NETWORK"] = "solana-devnet"
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)

    from gecko_api.main import app
    from gecko_core.orchestration.trade_panel import TradePanelTurn, TradePanelVerdict

    fake_verdict = TradePanelVerdict(
        verdict="act",
        confidence=0.7,
        key_drivers=["technical alignment", "TVL growth"],
        dissent_count=1,
        blocker_questions=["Does Pyth uptime hold?"],
        turns=[
            TradePanelTurn(
                agent="technical_analyst",
                content="bullish trend",
                parsed_verdict={"trend_verdict": "bullish"},
            ),
            TradePanelTurn(
                agent="coordinator",
                content='```json\n{"verdict": "act"}\n```',
                parsed_verdict={"verdict": "act"},
            ),
        ],
    )

    with (
        patch(
            "gecko_core.orchestration.trade_panel.run_trade_panel_with_retrieval",
            new=AsyncMock(return_value=fake_verdict),
        ),
        TestClient(app) as c,
    ):
        yield c


def _paid_post(
    client: TestClient,
    *,
    path: str = "/trade_research",
    body: dict | None = None,
) -> tuple[int, dict]:
    """Run the 402 → paid retry dance once; return (status_code, json_body)."""
    body = body or {"idea": "Should I open a JTO long?", "protocol": "jito"}
    r0 = client.post(path, json=body)
    assert r0.status_code == 402, r0.text
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    payment_header = _build_payment_payload_header(accepts_entry)
    r = client.post(path, json=body, headers={"PAYMENT-SIGNATURE": payment_header})
    out: dict = {}
    try:
        out = r.json()
    except Exception:
        out = {}
    return r.status_code, out


def test_unpaid_request_returns_402(client: TestClient) -> None:
    """Phase 10A — without a payment header the gate must 402."""
    r = client.post(
        "/trade_research",
        json={"idea": "Should I act here?", "protocol": "jito"},
    )
    assert r.status_code == 402, r.text
    header_value = r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
    assert header_value, f"missing PAYMENT-REQUIRED header; got {dict(r.headers)}"
    decoded = _decode_payment_required_header(header_value)
    assert decoded["accepts"]
    # Basic price is $0.25 → 250_000 atomic units of USDC.
    amounts = {entry.get("amount") for entry in decoded["accepts"]}
    assert "250000" in amounts


def test_paid_request_returns_200(client: TestClient) -> None:
    """Stub-mode payment header → handler runs and returns the verdict."""
    status, body = _paid_post(client)
    assert status == 200, body
    assert body["verdict"] == "act"
    assert body["confidence"] == pytest.approx(0.7)
    assert body["dissent_count"] == 1
    assert "TVL growth" in body["key_drivers"]
    assert isinstance(body["turns"], list)


def test_pro_route_advertises_higher_price(client: TestClient) -> None:
    """The /trade_research/pro route should advertise $0.75 in its 402."""
    r = client.post(
        "/trade_research/pro",
        json={"idea": "Should I act here?", "protocol": "jito"},
    )
    assert r.status_code == 402
    decoded = _decode_payment_required_header(r.headers["payment-required"])
    amounts = {entry.get("amount") for entry in decoded["accepts"]}
    assert "750000" in amounts  # $0.75 USDC = 750_000


def test_trade_research_missing_protocol_returns_422(client: TestClient) -> None:
    """Pydantic validation rejects requests without the required protocol field.

    Validation runs after x402 settle, so we send a paid request to reach it.
    """
    r0 = client.post(
        "/trade_research",
        json={"idea": "Should I act?", "vertical": "dex"},
    )
    assert r0.status_code == 402
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    payment_header = _build_payment_payload_header(accepts_entry)
    r = client.post(
        "/trade_research",
        json={"idea": "Should I act here?", "vertical": "dex"},
        headers={"PAYMENT-SIGNATURE": payment_header},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    missing = [d for d in detail if d.get("loc", [])[-1] == "protocol"]
    assert missing, f"expected 'protocol' in 422 detail, got {detail!r}"


def test_rate_limit_per_ip(client: TestClient) -> None:
    """11 unpaid calls from the same IP in 60s → the 11th returns 429.

    Per-IP rate limit lives in front of the x402 middleware so attempts
    that never pay still consume budget. The TestClient defaults to a
    fixed client IP, so successive calls share the bucket.
    """
    body = {"idea": "Should I act?", "protocol": "jito"}
    # First 10 calls: each returns 402 (unpaid).
    for i in range(10):
        r = client.post("/trade_research", json=body)
        assert r.status_code == 402, f"call {i + 1} got {r.status_code}: {r.text}"
    # 11th call: rate-limit middleware fires before x402 → 429.
    r = client.post("/trade_research", json=body)
    assert r.status_code == 429, r.text


def test_well_known_advertises_trade_research(client: TestClient) -> None:
    """Phase 10A — the /trade_research routes must show up in /.well-known/x402."""
    r = client.get("/.well-known/x402")
    assert r.status_code == 200
    routes = {entry["route"]: entry for entry in r.json()["routes"]}
    assert "POST /trade_research" in routes
    assert "POST /trade_research/pro" in routes
    basic_prices = {a["price"] for a in routes["POST /trade_research"]["accepts"]}
    pro_prices = {a["price"] for a in routes["POST /trade_research/pro"]["accepts"]}
    assert "$0.25" in basic_prices
    assert "$0.75" in pro_prices
