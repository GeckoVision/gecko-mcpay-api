"""S12-CDP-01 / S12-CDP-03 — CDPX402Client contract tests.

We never make real CDP API calls. Every charge() path goes through an
injected fake facilitator (``FakeFacilitator``) that records the
``settle()`` arguments and returns a canned ``SettleResponse``.

Covers:
  * Happy-path charge → ``PaymentResult.success`` with the EVM tx hash
    surfaced as ``tx_signature`` (parity with frames.ag's tx_signature
    field so ``bb economics --verify`` works uniformly).
  * Settle returning ``success=false`` → ``CDPSettleError`` with the
    facilitator's reason verbatim (no rephrase).
  * Missing Base treasury → ``CDPNotConfiguredError`` before any IO.
  * Unconfigured CDP creds without an injected facilitator →
    ``CDPNotConfiguredError`` (sentinel detection rides on
    ``cdp.is_unconfigured``).
  * Payload building: amount in 6-decimal smallest units, asset is the
    canonical Base USDC contract, network defaults to ``eip155:8453``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from gecko_core.payments import (
    BASE_MAINNET_NETWORK_ID,
    BASE_MAINNET_USDC_CONTRACT,
    CDPNotConfiguredError,
    CDPSettleError,
    CDPX402Client,
    PaymentIntent,
)

# ---------------------------------------------------------------------------
# Fake facilitator + canned response shapes.
# ---------------------------------------------------------------------------


@dataclass
class _FakeSettleResponse:
    """Mirrors the public surface of ``x402.schemas.SettleResponse``."""

    success: bool
    transaction: str = ""
    error_reason: str | None = None
    error_message: str | None = None
    network: str = BASE_MAINNET_NETWORK_ID
    payer: str | None = None
    amount: str | None = None


@dataclass
class _FakeFacilitator:
    """Records settle calls; returns the canned ``response``."""

    response: _FakeSettleResponse
    raise_exc: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def settle(self, payload: Any, requirements: Any) -> _FakeSettleResponse:
        self.calls.append({"payload": payload, "requirements": requirements})
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response


def _intent(amount: str = "0.10") -> PaymentIntent:
    return PaymentIntent(
        intent_id="cdp-test-1",
        session_id=uuid4(),
        tier="basic",
        amount_usd=Decimal(amount),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_success_returns_payment_result_with_tx_hash() -> None:
    fake = _FakeFacilitator(
        response=_FakeSettleResponse(success=True, transaction="0xabc123"),
    )
    client = CDPX402Client(
        facilitator=fake,
        treasury_address="0xTreasuryBase",
    )

    result = await client.charge(_intent())

    assert result.status == "success"
    assert result.tx_signature == "0xabc123"
    assert result.error is None
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_charge_uses_base_mainnet_usdc_and_six_decimals() -> None:
    """Payload + requirements: USDC contract, eip155:8453, 6-decimal units."""
    fake = _FakeFacilitator(
        response=_FakeSettleResponse(success=True, transaction="0xdeadbeef"),
    )
    client = CDPX402Client(
        facilitator=fake,
        treasury_address="0xTreasuryBase",
    )

    await client.charge(_intent("1.234567"))

    req = fake.calls[0]["requirements"]
    # 1.234567 USD * 1e6 = 1234567 smallest units (6 decimals).
    assert req.amount == "1234567"
    assert req.asset == BASE_MAINNET_USDC_CONTRACT
    assert req.network == BASE_MAINNET_NETWORK_ID
    assert req.pay_to == "0xTreasuryBase"
    assert req.scheme == "exact"


@pytest.mark.asyncio
async def test_charge_payload_carries_intent_id() -> None:
    """Idempotency — facilitator sees the intent_id in the payload."""
    fake = _FakeFacilitator(
        response=_FakeSettleResponse(success=True, transaction="0x1"),
    )
    client = CDPX402Client(facilitator=fake, treasury_address="0xTreasuryBase")
    intent = _intent()

    await client.charge(intent)

    payload = fake.calls[0]["payload"]
    assert payload.payload["intent_id"] == intent.intent_id


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_settle_failure_raises_with_message_verbatim() -> None:
    fake = _FakeFacilitator(
        response=_FakeSettleResponse(
            success=False,
            transaction="",
            error_reason="insufficient_funds",
            error_message="payer balance below required amount",
        ),
    )
    client = CDPX402Client(facilitator=fake, treasury_address="0xTreasuryBase")

    with pytest.raises(CDPSettleError) as exc:
        await client.charge(_intent())
    # Verbatim — facilitator's own message is in the exception text.
    assert "payer balance below required amount" in str(exc.value)


@pytest.mark.asyncio
async def test_charge_success_without_tx_hash_raises() -> None:
    """Defensive: a 2xx + success=True without ``transaction`` is an error."""
    fake = _FakeFacilitator(response=_FakeSettleResponse(success=True, transaction=""))
    client = CDPX402Client(facilitator=fake, treasury_address="0xTreasuryBase")

    with pytest.raises(CDPSettleError, match="without transaction hash"):
        await client.charge(_intent())


@pytest.mark.asyncio
async def test_charge_missing_treasury_raises_before_any_io() -> None:
    fake = _FakeFacilitator(
        response=_FakeSettleResponse(success=True, transaction="0x1"),
    )
    # No treasury_address; should fail before settle is ever called.
    client = CDPX402Client(facilitator=fake)

    with pytest.raises(CDPNotConfiguredError, match="GECKO_WALLET_ADDRESS_BASE"):
        await client.charge(_intent())
    assert fake.calls == [], "facilitator must not be called when treasury missing"


@pytest.mark.asyncio
async def test_charge_zero_amount_after_quantize_raises() -> None:
    fake = _FakeFacilitator(
        response=_FakeSettleResponse(success=True, transaction="0x1"),
    )
    client = CDPX402Client(facilitator=fake, treasury_address="0xTreasuryBase")

    with pytest.raises(Exception, match="rounds to 0 USDC"):
        await client.charge(_intent("0.0000001"))  # < 1 smallest unit


@pytest.mark.asyncio
async def test_charge_facilitator_exception_propagates_verbatim() -> None:
    fake = _FakeFacilitator(
        response=_FakeSettleResponse(success=True, transaction=""),
        raise_exc=RuntimeError("network exploded"),
    )
    client = CDPX402Client(facilitator=fake, treasury_address="0xTreasuryBase")

    with pytest.raises(RuntimeError, match="network exploded"):
        await client.charge(_intent())


@pytest.mark.asyncio
async def test_unconfigured_creds_without_injected_facilitator_raises() -> None:
    """No injected facilitator + sentinel creds → typed error, no IO."""
    client = CDPX402Client(
        treasury_address="0xTreasuryBase",
        api_key_id="__unset__",
        api_key_secret="__unset__",
    )

    with pytest.raises(CDPNotConfiguredError, match="CDP_API_KEY_ID"):
        await client.charge(_intent())
