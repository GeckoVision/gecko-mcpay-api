"""S12-CDP-03 — per-call confirmation + receipt unification.

The reconcile claim: ``bb economics <session_id> --verify`` works
uniformly across frames.ag (Solana) and CDP (Base) settled sessions
because both clients return the same ``PaymentResult`` shape with the
chain's transaction identifier in ``tx_signature``.

Tests assert the unification directly:
  * Stub mode → ``tx_signature is None`` (skip-stub branch in verifier).
  * CDP mode (success) → ``tx_signature`` carries the EVM tx hash.
  * Both end up in the same ``PaymentResult`` Pydantic model with the
    same field names (``intent_id``, ``status``, ``tx_signature``,
    ``error``).

We don't run the verifier here — that's covered separately. This test
just locks the cross-facilitator receipt shape so a future facilitator
(Cloudflare in Sprint 15 per the web3-engineer memo) inherits the same
contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from gecko_core.payments import (
    BASE_MAINNET_NETWORK_ID,
    CDPX402Client,
    PaymentIntent,
    PaymentResult,
    StubX402Client,
)


@dataclass
class _FakeSettleResponse:
    success: bool
    transaction: str = ""
    error_reason: str | None = None
    error_message: str | None = None
    network: str = BASE_MAINNET_NETWORK_ID


@dataclass
class _FakeFacilitator:
    response: _FakeSettleResponse

    async def settle(self, payload: Any, requirements: Any) -> _FakeSettleResponse:
        return self.response


def _intent() -> PaymentIntent:
    return PaymentIntent(
        intent_id="reconcile-test",
        session_id=uuid4(),
        tier="basic",
        amount_usd=Decimal("0.10"),
    )


@pytest.mark.asyncio
async def test_stub_and_cdp_results_share_payment_result_schema() -> None:
    """Both clients return the same ``PaymentResult`` model — same fields."""
    stub = StubX402Client()
    cdp = CDPX402Client(
        facilitator=_FakeFacilitator(
            response=_FakeSettleResponse(success=True, transaction="0xabc"),
        ),
        treasury_address="0xTreasuryBase",
    )

    stub_result = await stub.charge(_intent())
    cdp_result = await cdp.charge(_intent())

    # Same Pydantic model class — caught by mypy too, but assert at runtime
    # so the cross-facilitator contract is locked.
    assert isinstance(stub_result, PaymentResult)
    assert isinstance(cdp_result, PaymentResult)

    # Same field names. Fan future facilitators inherit this exact set.
    assert set(stub_result.model_dump().keys()) == set(cdp_result.model_dump().keys())
    assert set(stub_result.model_dump().keys()) == {
        "intent_id",
        "status",
        "tx_signature",
        "error",
    }


@pytest.mark.asyncio
async def test_cdp_tx_signature_is_evm_tx_hash() -> None:
    """``tx_signature`` carries the on-chain identifier — EVM hash for CDP."""
    cdp = CDPX402Client(
        facilitator=_FakeFacilitator(
            response=_FakeSettleResponse(
                success=True,
                transaction="0xfeedface00000000000000000000000000000000000000000000000000000001",
            ),
        ),
        treasury_address="0xTreasuryBase",
    )

    result = await cdp.charge(_intent())
    # bb economics --verify reads tx_signature and dispatches RPC by network.
    assert result.tx_signature is not None
    assert result.tx_signature.startswith("0x")
    assert result.status == "success"
    assert result.error is None


@pytest.mark.asyncio
async def test_stub_signature_is_none_for_skip_stub_branch() -> None:
    """Stub never produces a tx_signature — verifier short-circuits."""
    stub = StubX402Client()
    result = await stub.charge(_intent())
    assert result.tx_signature is None
    assert result.status == "success"
