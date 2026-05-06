"""Tests for the single x402-gated /skills/{name} dispatcher (S20-B3).

Asserts:
    1. Flag off / unset → 503 + X-Gecko-Skills-Status: draft.
    2. Flag on, unknown skill → 404.
    3. Flag on, valid skill, no X-PAYMENT → 402 + decodable PAYMENT-REQUIRED
       with accepts[0].amount = price_usd × 10^6 (USDC wire amount).
    4. Flag on, valid skill, valid stubbed X-PAYMENT → 200 + tx_signature
       in body and X-Payment-Tx-Signature header.
    5. Flag on, valid skill, malformed X-PAYMENT → 402 + error_detail.
    6. Idempotent replay — same X-PAYMENT twice returns same tx_signature
       and only one verify() call hits the underlying client.
    7. Schema-drift: research-market is reachable via /skills/research-market.
    8. Facilitator neutrality — solana network → solana CAIP-2; base
       network → eip155:8453.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Force stub mode + devnet BEFORE importing the app — gecko-api freezes
# settings at module import. Individual tests opt into base-mainnet via
# the dedicated fixture below.
os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("X402_NETWORK", "solana-devnet")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _purge_gecko_modules() -> None:
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Default Solana-devnet client. Flag is left to the individual test."""
    os.environ["X402_MODE"] = "stub"
    os.environ["X402_NETWORK"] = "solana-devnet"
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_WALLET_ADDRESS_NOT_FOR_LIVE"
    os.environ.pop("X402_CHAIN", None)
    os.environ.pop("X402_OPERATOR_WALLET", None)
    os.environ.pop("GECKO_SKILLS_DISPATCH_ENABLED", None)
    _purge_gecko_modules()

    from gecko_core.payments.dispatch import _idempotency_clear

    _idempotency_clear()
    from gecko_api.main import app

    with TestClient(app) as c:
        yield c

    os.environ.pop("GECKO_SKILLS_DISPATCH_ENABLED", None)


@pytest.fixture
def base_client() -> Iterator[TestClient]:
    """Same app, but with X402_NETWORK=base-mainnet for chain-neutrality test."""
    os.environ["X402_MODE"] = "stub"
    os.environ["X402_NETWORK"] = "base-mainnet"
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_WALLET_ADDRESS_NOT_FOR_LIVE"
    os.environ["GECKO_WALLET_ADDRESS_BASE"] = "0x000000000000000000000000000000000000dEaD"
    os.environ.pop("X402_CHAIN", None)
    os.environ.pop("X402_OPERATOR_WALLET", None)
    os.environ.pop("GECKO_SKILLS_DISPATCH_ENABLED", None)
    _purge_gecko_modules()

    from gecko_core.payments.dispatch import _idempotency_clear

    _idempotency_clear()
    from gecko_api.main import app

    with TestClient(app) as c:
        yield c

    # Restore devnet defaults so other tests in the session aren't surprised.
    os.environ["X402_NETWORK"] = "solana-devnet"
    os.environ.pop("GECKO_SKILLS_DISPATCH_ENABLED", None)
    os.environ.pop("GECKO_WALLET_ADDRESS_BASE", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_payment_required(value: str) -> dict:
    return json.loads(base64.b64decode(value).decode("utf-8"))


def _build_x_payment(*, transaction: str = "stub-tx") -> str:
    payload = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": transaction},
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_flag_off_returns_503_draft(client: TestClient) -> None:
    r = client.post("/skills/retrieve-market-intelligence", json={})
    assert r.status_code == 503
    assert r.headers.get("X-Gecko-Skills-Status") == "draft"
    assert "DRAFT" in r.json()["detail"] or "draft" in r.json()["detail"]


def test_flag_on_unknown_skill_returns_404(client: TestClient) -> None:
    os.environ["GECKO_SKILLS_DISPATCH_ENABLED"] = "true"
    r = client.post("/skills/does-not-exist", json={})
    assert r.status_code == 404
    assert "Unknown skill" in r.json()["detail"]


def test_flag_on_valid_skill_no_payment_returns_402(client: TestClient) -> None:
    os.environ["GECKO_SKILLS_DISPATCH_ENABLED"] = "true"
    r = client.post("/skills/retrieve-market-intelligence", json={})
    assert r.status_code == 402

    header = r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
    assert header, f"missing PAYMENT-REQUIRED header; got {dict(r.headers)}"
    decoded = _decode_payment_required(header)
    assert decoded["x402_version"] == 2
    assert len(decoded["accepts"]) == 1
    entry = decoded["accepts"][0]
    # retrieve-* skills are priced at $0.01 → 10_000 wire (USDC, 6dp).
    assert entry["amount"] == int(Decimal("0.01") * Decimal(10**6))
    assert entry["asset"] == "USDC"
    assert entry["skill"] == "retrieve-market-intelligence"


def test_flag_on_valid_payment_returns_200_with_tx_header(client: TestClient) -> None:
    os.environ["GECKO_SKILLS_DISPATCH_ENABLED"] = "true"
    x_payment = _build_x_payment(transaction="stub-tx-aaa")

    # StubX402Client.verify already returns "confirmed"; no extra patch needed.
    r = client.post(
        "/skills/retrieve-market-intelligence",
        headers={"X-PAYMENT": x_payment},
        json={},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Payment-Tx-Signature") == "stub-tx-aaa"
    body = r.json()
    assert body["skill"] == "retrieve-market-intelligence"
    assert body["tx_signature"] == "stub-tx-aaa"
    assert body["status"] == "ok"


def test_flag_on_malformed_payment_returns_402(client: TestClient) -> None:
    os.environ["GECKO_SKILLS_DISPATCH_ENABLED"] = "true"
    # Not base64 → decode error
    r = client.post(
        "/skills/retrieve-market-intelligence",
        headers={"X-PAYMENT": "not-valid-base64-!!!"},
        json={},
    )
    assert r.status_code == 402
    assert "verify failed" in r.json()["detail"]


def test_flag_on_verify_returns_failed_status(client: TestClient) -> None:
    os.environ["GECKO_SKILLS_DISPATCH_ENABLED"] = "true"
    x_payment = _build_x_payment(transaction="stub-tx-bbb")

    # Force the stub client to return a failure verdict.
    with patch(
        "gecko_core.payments.x402_client.StubX402Client.verify",
        new=AsyncMock(return_value="failed"),
    ):
        r = client.post(
            "/skills/retrieve-market-intelligence",
            headers={"X-PAYMENT": x_payment},
            json={},
        )
    assert r.status_code == 402
    assert "facilitator returned status='failed'" in r.json()["detail"]


def test_idempotent_replay_uses_cache(client: TestClient) -> None:
    os.environ["GECKO_SKILLS_DISPATCH_ENABLED"] = "true"
    x_payment = _build_x_payment(transaction="stub-tx-replay")

    verify_mock = AsyncMock(return_value="confirmed")
    with patch(
        "gecko_core.payments.x402_client.StubX402Client.verify",
        new=verify_mock,
    ):
        r1 = client.post(
            "/skills/retrieve-market-intelligence",
            headers={"X-PAYMENT": x_payment},
            json={},
        )
        r2 = client.post(
            "/skills/retrieve-market-intelligence",
            headers={"X-PAYMENT": x_payment},
            json={},
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["tx_signature"] == r2.json()["tx_signature"] == "stub-tx-replay"
    # Verify only on the first call; second call hits the LRU cache.
    assert verify_mock.await_count == 1


def test_research_market_skill_reachable(client: TestClient) -> None:
    """Schema-drift smoke — research-market is one of the 12 registered."""
    os.environ["GECKO_SKILLS_DISPATCH_ENABLED"] = "true"
    r = client.post("/skills/research-market", json={})
    # Without a payment header it 402s — the assertion is that the route
    # exists (i.e. NOT 404) and the dispatcher recognized the skill.
    assert r.status_code == 402
    header = r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
    assert header
    decoded = _decode_payment_required(header)
    assert decoded["accepts"][0]["skill"] == "research-market"
    # research-market is $0.10 → 100_000 wire.
    assert decoded["accepts"][0]["amount"] == int(Decimal("0.10") * Decimal(10**6))


def test_facilitator_neutrality_solana_network(client: TestClient) -> None:
    os.environ["GECKO_SKILLS_DISPATCH_ENABLED"] = "true"
    r = client.post("/skills/retrieve-market-intelligence", json={})
    assert r.status_code == 402
    decoded = _decode_payment_required(r.headers["payment-required"])
    entry = decoded["accepts"][0]
    assert entry["chain"] == "solana"
    assert entry["network"].startswith("solana:")


def test_facilitator_neutrality_base_network(base_client: TestClient) -> None:
    os.environ["GECKO_SKILLS_DISPATCH_ENABLED"] = "true"
    r = base_client.post("/skills/retrieve-market-intelligence", json={})
    assert r.status_code == 402
    decoded = _decode_payment_required(r.headers["payment-required"])
    entry = decoded["accepts"][0]
    assert entry["chain"] == "base"
    assert entry["network"] == "eip155:8453"
