"""Integration tests for the credit-pack mint + redeem flow (S20-B4).

Covers:
  1. Buy credit pack via X-PAYMENT → response carries credit_token + 1.5M.
  2. Use credit_token via Authorization: Bearer for retrieve-* skill →
     200 + Mongo decrement reflected.
  3. Replay (same X-PAYMENT) → idempotent, no double-mint.
  4. Tampered JWT → 402 with "invalid signature" detail.
"""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


def _purge_modules() -> None:
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Generate a fresh Ed25519 signing key per test fixture
    from gecko_core.payments import credit_token as ct
    from gecko_core.payments.credit_token import generate_signing_key

    priv, _ = generate_signing_key()
    monkeypatch.setenv("GECKO_CREDIT_SIGNING_KEY", base64.b64encode(priv).decode("ascii"))
    monkeypatch.delenv("GECKO_CREDIT_SIGNING_KEY_PREVIOUS", raising=False)
    ct._signing_key_cache_clear()

    # x402 stub mode + devnet
    monkeypatch.setenv("X402_MODE", "stub")
    monkeypatch.setenv("X402_NETWORK", "solana-devnet")
    monkeypatch.setenv("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")
    monkeypatch.setenv("GECKO_SKILLS_DISPATCH_ENABLED", "true")
    monkeypatch.delenv("X402_CHAIN", raising=False)

    # Stub the Mongo credit_tokens collection
    from gecko_core.db import mongo_credit_tokens
    from gecko_core.db.mongo_credit_tokens import StubCreditTokenCollection

    stub = StubCreditTokenCollection()
    monkeypatch.setattr(mongo_credit_tokens, "credit_tokens_collection", lambda: stub)

    # Reset the dispatcher idempotency cache
    from gecko_core.payments.dispatch import _idempotency_clear

    _idempotency_clear()

    _purge_modules()
    from gecko_api.main import app

    with TestClient(app) as c:
        c.stub_collection = stub  # type: ignore[attr-defined]
        yield c

    ct._signing_key_cache_clear()


def _build_x_payment(transaction: str = "stub-tx-credit-pack") -> str:
    payload = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": transaction},
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


def test_buy_credit_pack_returns_jwt(client: TestClient) -> None:
    x_payment = _build_x_payment(transaction="tx-buy-1")
    r = client.post(
        "/skills/credit-pack",
        headers={"X-PAYMENT": x_payment, "X-Wallet-Address": "solana:wallet1"},
        json={},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skill"] == "credit-pack"
    assert body["tokens_remaining"] == 1_500_000
    assert "credit_token" in body
    # JWT shape — three base64url segments
    parts = body["credit_token"].split(".")
    assert len(parts) == 3
    assert body["tx_signature"] == "tx-buy-1"
    assert "expires_at" in body


def test_redeem_credit_token_decrements_balance(client: TestClient) -> None:
    # Buy pack
    x_payment = _build_x_payment(transaction="tx-buy-2")
    buy = client.post(
        "/skills/credit-pack",
        headers={"X-PAYMENT": x_payment, "X-Wallet-Address": "solana:wallet2"},
        json={},
    )
    assert buy.status_code == 200, buy.text
    jwt = buy.json()["credit_token"]

    # Redeem against retrieve-market-intelligence (50_000 bundled)
    r = client.post(
        "/skills/retrieve-market-intelligence",
        headers={"Authorization": f"Bearer {jwt}"},
        json={},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tx_signature"] == "tx-buy-2"  # jti reused for telemetry
    assert body["chain"] == "solana"

    # Balance dropped to 1_500_000 - 50_000
    import asyncio

    from gecko_core.db.mongo_credit_tokens import get_credit_pack

    doc = asyncio.run(get_credit_pack("tx-buy-2"))
    assert doc is not None
    assert doc["tokens_remaining"] == 1_500_000 - 50_000


def test_replay_buy_is_idempotent(client: TestClient) -> None:
    x_payment = _build_x_payment(transaction="tx-buy-replay")
    r1 = client.post(
        "/skills/credit-pack",
        headers={"X-PAYMENT": x_payment, "X-Wallet-Address": "solana:wallet3"},
        json={},
    )
    assert r1.status_code == 200

    # Spend some of the pack via the JWT
    jwt = r1.json()["credit_token"]
    spend = client.post(
        "/skills/retrieve-market-intelligence",
        headers={"Authorization": f"Bearer {jwt}"},
        json={},
    )
    assert spend.status_code == 200

    # Replay the buy — must NOT reset the balance
    r2 = client.post(
        "/skills/credit-pack",
        headers={"X-PAYMENT": x_payment, "X-Wallet-Address": "solana:wallet3"},
        json={},
    )
    assert r2.status_code == 200
    # Same tx_signature on both responses
    assert r1.json()["tx_signature"] == r2.json()["tx_signature"]

    import asyncio

    from gecko_core.db.mongo_credit_tokens import get_credit_pack

    doc = asyncio.run(get_credit_pack("tx-buy-replay"))
    assert doc is not None
    # 1.5M - 50K spent on the retrieve-market-intelligence call
    assert doc["tokens_remaining"] == 1_500_000 - 50_000


def test_tampered_jwt_returns_402(client: TestClient) -> None:
    # Buy pack to get a valid JWT
    x_payment = _build_x_payment(transaction="tx-buy-tamper")
    buy = client.post(
        "/skills/credit-pack",
        headers={"X-PAYMENT": x_payment, "X-Wallet-Address": "solana:wallet4"},
        json={},
    )
    jwt = buy.json()["credit_token"]
    # Tamper with the signature segment
    h, p, s = jwt.split(".")
    sig_bytes = bytearray(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
    sig_bytes[0] ^= 0xFF
    bad_s = base64.urlsafe_b64encode(bytes(sig_bytes)).rstrip(b"=").decode("ascii")
    bad_jwt = f"{h}.{p}.{bad_s}"

    r = client.post(
        "/skills/retrieve-market-intelligence",
        headers={"Authorization": f"Bearer {bad_jwt}"},
        json={},
    )
    assert r.status_code == 402, r.text
    assert "invalid signature" in r.json()["detail"].lower()
