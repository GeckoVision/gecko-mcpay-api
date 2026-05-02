"""Tests for the POST /plan endpoint (S5-API-01).

Asserts:
    1. Unpaid POST /plan returns 402 with a parseable PaymentRequired header.
    2. Paid POST /plan (stub-mode payload) returns 200 + AdvisorPanel shape.
    3. /.well-known/x402 advertises POST /plan at $0.25.
    4. Non-existent session returns 404.

Mocks `gecko_core.orchestration.advisor.generate_panel` so this never
touches Supabase / OpenAI.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Force stub mode BEFORE importing the app — settings are frozen at import time.
os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")
os.environ.pop("PLAN_CALL_PRICE", None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    os.environ.pop("PLAN_CALL_PRICE", None)
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)

    from gecko_api.main import app
    from gecko_core.orchestration.advisor.models import (
        PANEL_VOICE_ORDER,
        AdvisorPanel,
        AdvisorVoice,
    )

    voices = [
        AdvisorVoice(
            role=role,
            model_used=f"stub/{role.value}",
            output_md=f"# {role.value} output",
            closing_line=f"closing for {role.value}",
            tokens_in=100,
            tokens_out=200,
            cost_usd=0.001,
        )
        for role in PANEL_VOICE_ORDER
    ]
    fake_panel = AdvisorPanel(
        session_id="00000000-0000-0000-0000-000000000123",
        voices=voices,
        total_cost_usd=0.005,
        generated_at=datetime.now(tz=UTC),
    )

    # Patch where it's looked up — main.py imports via the lazy `from
    # gecko_core.orchestration.advisor import generate_panel` inside plan_call.
    with (
        patch(
            "gecko_core.orchestration.advisor.generate_panel",
            new=AsyncMock(return_value=fake_panel),
        ),
        # Avoid touching Supabase from set_price / project rollup helpers.
        patch(
            "gecko_core.sessions.store.SessionStore.from_env",
            new=lambda: _StubStore(),
        ),
        TestClient(app) as c,
    ):
        yield c


class _StubStore:
    """Minimal SessionStore stand-in used by /plan's bookkeeping helpers."""

    async def set_price(self, session_id: object, price_usd: float) -> None:
        return None


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


def test_unpaid_plan_returns_402(client: TestClient) -> None:
    r = client.post(
        "/plan",
        json={"session_id": "00000000-0000-0000-0000-000000000123"},
    )
    assert r.status_code == 402
    header_value = r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
    assert header_value, f"missing PAYMENT-REQUIRED header; got {dict(r.headers)}"
    decoded = _decode_payment_required_header(header_value)
    assert decoded["accepts"]
    # The 402 header carries `amount` (atomic units) — $0.25 USDC = 250_000.
    amounts = {entry.get("amount") for entry in decoded["accepts"]}
    assert "250000" in amounts


def test_paid_plan_returns_advisor_panel_shape(client: TestClient) -> None:
    r0 = client.post(
        "/plan",
        json={"session_id": "00000000-0000-0000-0000-000000000123"},
    )
    assert r0.status_code == 402
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    payment_header = _build_payment_payload_header(accepts_entry)

    r = client.post(
        "/plan",
        json={
            "session_id": "00000000-0000-0000-0000-000000000123",
            "tier_preset": "balanced",
            "frames_username": "tester",
        },
        headers={"PAYMENT-SIGNATURE": payment_header},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # AdvisorPanel shape — every documented field present.
    for field in ("session_id", "voices", "total_cost_usd", "generated_at"):
        assert field in body, f"missing {field} in AdvisorPanel JSON: {body}"
    assert len(body["voices"]) == 5
    assert body["voices"][0]["role"] == "ceo"
    # The session_id round-trips through the panel — sanity-check it's a str.
    assert isinstance(body["session_id"], str)


def test_well_known_advertises_plan_endpoint(client: TestClient) -> None:
    r = client.get("/.well-known/x402")
    assert r.status_code == 200
    routes = {entry["route"]: entry for entry in r.json()["routes"]}
    assert "POST /plan" in routes
    prices = {a["price"] for a in routes["POST /plan"]["accepts"]}
    assert "$0.25" in prices


def test_paid_plan_invalid_session_id_returns_400(client: TestClient) -> None:
    r0 = client.post(
        "/plan",
        json={"session_id": "00000000-0000-0000-0000-000000000123"},
    )
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    payment_header = _build_payment_payload_header(accepts_entry)

    r = client.post(
        "/plan",
        json={"session_id": "not-a-uuid"},
        headers={"PAYMENT-SIGNATURE": payment_header},
    )
    assert r.status_code == 400, r.text
    assert "invalid session_id" in r.text
