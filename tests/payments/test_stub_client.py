"""StubX402Client always succeeds, fast, with tx_signature=None."""

from __future__ import annotations

import time
from decimal import Decimal
from uuid import uuid4

import pytest
from gecko_core.payments import PaymentIntent, StubX402Client


@pytest.mark.asyncio
async def test_stub_returns_success_under_200ms() -> None:
    client = StubX402Client()
    intent = PaymentIntent(
        intent_id="test-1",
        session_id=uuid4(),
        tier="basic",
        amount_usd=Decimal("10.00"),
    )

    t0 = time.perf_counter()
    result = await client.charge(intent)
    elapsed = time.perf_counter() - t0

    assert result.status == "success"
    assert result.tx_signature is None
    assert result.error is None
    assert result.intent_id == "test-1"
    assert elapsed < 0.2
