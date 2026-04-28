"""Same intent_id charged twice → second is a no-op."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from gecko_core.models import SessionStatus, Tier
from gecko_core.payments import run_payment_gate
from gecko_core.payments.models import PaymentIntent, PaymentResult
from gecko_core.sessions.store import SessionRecord


class FakeStore:
    def __init__(self, session_id: UUID, tier: Tier = "basic") -> None:
        self.session_id = session_id
        self.record = SessionRecord(
            id=session_id,
            idea="idem test",
            tier=tier,
            status="pending",
            payment_intent_id=None,
            payment_mode="stub",
            created_at=datetime.now().astimezone(),
        )
        self.status_calls: list[SessionStatus] = []
        self.intent_calls: list[str] = []

    async def get(self, session_id: UUID) -> SessionRecord | None:
        return self.record if session_id == self.session_id else None

    async def set_payment_intent(self, session_id: UUID, intent_id: str) -> None:
        self.intent_calls.append(intent_id)
        self.record = self.record.model_copy(update={"payment_intent_id": intent_id})

    async def update_status(self, session_id: UUID, status: SessionStatus) -> None:
        self.status_calls.append(status)
        self.record = self.record.model_copy(update={"status": status})


class CountingClient:
    def __init__(self) -> None:
        self.charge_count = 0

    async def charge(self, intent: PaymentIntent) -> PaymentResult:
        self.charge_count += 1
        return PaymentResult(
            intent_id=intent.intent_id,
            status="success",
            tx_signature=None,
            error=None,
        )


@pytest.mark.asyncio
async def test_second_call_is_noop_after_success() -> None:
    sid = uuid4()
    store = FakeStore(sid)
    client = CountingClient()

    first = await run_payment_gate(sid, "basic", store, client)  # type: ignore[arg-type]
    assert first.status == "success"
    assert client.charge_count == 1
    assert store.status_calls == ["indexing"]
    assert len(store.intent_calls) == 1

    # Status is now 'indexing' — second invocation must short-circuit.
    second = await run_payment_gate(sid, "basic", store, client)  # type: ignore[arg-type]

    assert second.status == "success"
    # No additional charge, no additional status mutation, no second intent write.
    assert client.charge_count == 1
    assert store.status_calls == ["indexing"]
    assert len(store.intent_calls) == 1
    # Same intent_id reused.
    assert second.intent_id == first.intent_id
