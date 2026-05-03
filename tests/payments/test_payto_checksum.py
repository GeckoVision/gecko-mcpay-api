"""S14-CDP-HARDEN-03 — EIP-55 checksum encoding for EVM payTo / asset.

Some strict EIP-712 facilitators reject non-checksummed `to` addresses
inside the signed message. We checksum-encode at PaymentRequirements
build time so every CDP settle sees a stable, EIP-55-correct address
regardless of how the operator wrote the env var (lowercase, mixed
case, sentinel).

Mixed-case Solana base58 is unaffected — the helper gates on the `0x`
prefix and the caller gates on network family.
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
    CDPX402Client,
    PaymentIntent,
)
from gecko_core.payments.cdp_x402_client import to_evm_checksum_address

# A famously mixed-case canonical example from the EIP-55 reference
# vector (vitalik.eth's original address). Lowercased + checksummed
# forms differ only in case; the byte content is identical.
_LOWERCASE = "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359"
_CHECKSUMMED = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"


def test_to_evm_checksum_address_returns_eip55() -> None:
    assert to_evm_checksum_address(_LOWERCASE) == _CHECKSUMMED


def test_to_evm_checksum_address_idempotent_on_already_checksummed() -> None:
    assert to_evm_checksum_address(_CHECKSUMMED) == _CHECKSUMMED


def test_to_evm_checksum_address_passes_through_solana_base58() -> None:
    """Solana base58 (no 0x prefix) is left untouched — the helper is
    gated on prefix so a Solana address that happens to share characters
    with hex doesn't get mangled."""
    base58 = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
    assert to_evm_checksum_address(base58) == base58


def test_to_evm_checksum_address_passes_through_empty() -> None:
    assert to_evm_checksum_address("") == ""


def test_to_evm_checksum_address_passes_through_stub_sentinel() -> None:
    assert (
        to_evm_checksum_address("STUB_WALLET_ADDRESS_NOT_FOR_LIVE")
        == "STUB_WALLET_ADDRESS_NOT_FOR_LIVE"
    )


# ---------------------------------------------------------------------------
# CDPX402Client.charge — payment requirements carry checksummed payTo.
# ---------------------------------------------------------------------------


@dataclass
class _FakeSettleResponse:
    success: bool
    transaction: str = ""


@dataclass
class _FakeFacilitator:
    response: _FakeSettleResponse
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def settle(self, payload: Any, requirements: Any) -> _FakeSettleResponse:
        self.calls.append({"payload": payload, "requirements": requirements})
        return self.response


def _intent() -> PaymentIntent:
    return PaymentIntent(
        intent_id="checksum-test",
        session_id=uuid4(),
        tier="basic",
        amount_usd=Decimal("0.10"),
    )


@pytest.mark.asyncio
async def test_charge_emits_checksummed_payto_on_eip155() -> None:
    fake = _FakeFacilitator(_FakeSettleResponse(success=True, transaction="0x1"))
    client = CDPX402Client(
        facilitator=fake,
        treasury_address=_LOWERCASE,  # operator wrote it lowercase
        network=BASE_MAINNET_NETWORK_ID,
    )
    await client.charge(_intent())
    req = fake.calls[0]["requirements"]
    # The on-the-wire payTo is checksummed even though we passed the
    # lowercase form into the constructor — byte-stable regardless of
    # operator capitalization.
    assert req.pay_to == _CHECKSUMMED
    # The asset (USDC contract) is also checksummed for the same reason.
    assert req.asset.lower() == BASE_MAINNET_USDC_CONTRACT.lower()
    assert req.asset == to_evm_checksum_address(BASE_MAINNET_USDC_CONTRACT)


@pytest.mark.asyncio
async def test_charge_payto_byte_stable_across_capitalizations() -> None:
    """Two clients built with different capitalizations of the same
    address produce identical PaymentRequirements.pay_to. This is the
    `/.well-known/x402` byte-stability acceptance criterion at the
    settle layer."""
    upper = "0xFB6916095CA1DF60BB79CE92CE3EA74C37C5D359"
    fake_a = _FakeFacilitator(_FakeSettleResponse(success=True, transaction="0x1"))
    fake_b = _FakeFacilitator(_FakeSettleResponse(success=True, transaction="0x1"))

    a = CDPX402Client(
        facilitator=fake_a, treasury_address=_LOWERCASE, network=BASE_MAINNET_NETWORK_ID
    )
    b = CDPX402Client(facilitator=fake_b, treasury_address=upper, network=BASE_MAINNET_NETWORK_ID)
    await a.charge(_intent())
    await b.charge(_intent())
    assert fake_a.calls[0]["requirements"].pay_to == fake_b.calls[0]["requirements"].pay_to
    assert fake_a.calls[0]["requirements"].pay_to == _CHECKSUMMED
