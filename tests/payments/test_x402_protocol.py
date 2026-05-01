"""S13-PAY-01 — formal X402Client Protocol conformance.

Asserts every concrete client honors the runtime-checkable Protocol +
carries the expected ``supported_networks`` and ``facilitator_id`` class
attrs. New facilitators (S15 Cloudflare, V2 frames+ policy layer) must
add a row here before they merge.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from gecko_core.payments import (
    CDPX402Client,
    FramesX402Client,
    LiveX402Client,
    PaymentIntent,
    StubX402Client,
    X402Client,
)
from gecko_core.payments.protocol import ConfirmationStatus
from pydantic import SecretStr


def _all_clients() -> list[X402Client]:
    """Construct one of each concrete client.

    Constructors must succeed without live env — the gate-side configure
    checks fire on ``charge()``, not at construction. This invariant
    keeps the Protocol-conformance assertions cheap.
    """
    return [
        StubX402Client(),
        LiveX402Client(facilitator_url="", wallet_secret=SecretStr("")),
        FramesX402Client(api_key=SecretStr("")),
        CDPX402Client(treasury_address="0xdeadbeef"),
    ]


@pytest.mark.parametrize("client", _all_clients(), ids=lambda c: type(c).__name__)
def test_runtime_protocol_conformance(client: X402Client) -> None:
    """Every concrete client passes the runtime-checkable Protocol."""
    assert isinstance(client, X402Client)


@pytest.mark.parametrize("client", _all_clients(), ids=lambda c: type(c).__name__)
def test_facilitator_id_present_and_nonempty(client: X402Client) -> None:
    """Every client carries a stable, non-empty ``facilitator_id``."""
    assert isinstance(client.facilitator_id, str)
    assert client.facilitator_id != ""


@pytest.mark.parametrize("client", _all_clients(), ids=lambda c: type(c).__name__)
def test_supported_networks_is_tuple_of_str(client: X402Client) -> None:
    """``supported_networks`` is a (possibly empty) tuple of strings."""
    assert isinstance(client.supported_networks, tuple)
    for entry in client.supported_networks:
        assert isinstance(entry, str)


def test_facilitator_ids_match_spec() -> None:
    """The four shipped clients use the documented facilitator_ids."""
    assert StubX402Client().facilitator_id == "stub"
    assert (
        LiveX402Client(facilitator_url="", wallet_secret=SecretStr("")).facilitator_id
        == "frames-solana"
    )
    assert FramesX402Client(api_key=SecretStr("")).facilitator_id == "frames"
    assert CDPX402Client(treasury_address="0xdeadbeef").facilitator_id == "cdp-base"


def test_supported_networks_match_spec() -> None:
    """Each client advertises the right network set per S13-PAY-01."""
    assert StubX402Client().supported_networks == ()  # any-network sentinel
    assert LiveX402Client(facilitator_url="", wallet_secret=SecretStr("")).supported_networks == (
        "solana-mainnet",
        "solana-devnet",
    )
    assert FramesX402Client(api_key=SecretStr("")).supported_networks == (
        "solana-mainnet",
        "solana-devnet",
    )
    cdp = CDPX402Client(treasury_address="0xdeadbeef").supported_networks
    assert "base-mainnet" in cdp
    assert "base-sepolia" in cdp


@pytest.mark.asyncio
async def test_stub_charge_and_verify_round_trip() -> None:
    """Stub honors both Protocol methods end to end without IO."""
    client = StubX402Client()
    intent = PaymentIntent(
        intent_id=str(uuid4()),
        session_id=uuid4(),
        tier="basic",
        amount_usd=Decimal("0.10"),
    )
    result = await client.charge(intent)
    assert result.status == "success"
    assert result.intent_id == intent.intent_id

    status: ConfirmationStatus = await client.verify(result.tx_signature or "")
    assert status == "confirmed"
