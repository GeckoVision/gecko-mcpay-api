"""Payment gate sequencing.

Mocks the SessionStore + X402Client. No Supabase, no network.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from gecko_core.models import SessionStatus, Tier
from gecko_core.payments import PaymentRequiredError, run_payment_gate
from gecko_core.payments.models import PaymentIntent, PaymentResult
from gecko_core.sessions.store import SessionRecord


class FakeStore:
    """In-memory SessionStore stand-in. Records every state transition."""

    def __init__(
        self,
        session_id: UUID,
        tier: Tier = "basic",
        status: SessionStatus = "pending",
        payment_intent_id: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.record = SessionRecord(
            id=session_id,
            idea="test idea",
            tier=tier,
            status=status,
            payment_intent_id=payment_intent_id,
            payment_mode="stub",
            created_at=datetime.now().astimezone(),
        )
        self.status_calls: list[SessionStatus] = []
        self.intent_calls: list[str] = []

    async def get(self, session_id: UUID) -> SessionRecord | None:
        if session_id != self.session_id:
            return None
        return self.record

    async def set_payment_intent(self, session_id: UUID, intent_id: str) -> None:
        self.intent_calls.append(intent_id)
        self.record = self.record.model_copy(update={"payment_intent_id": intent_id})

    async def update_status(self, session_id: UUID, status: SessionStatus) -> None:
        self.status_calls.append(status)
        self.record = self.record.model_copy(update={"status": status})


class StaticClient:
    """Returns a fixed PaymentResult, ignoring the intent."""

    def __init__(self, result: PaymentResult) -> None:
        self.result = result
        self.calls: list[PaymentIntent] = []

    async def charge(self, intent: PaymentIntent) -> PaymentResult:
        self.calls.append(intent)
        # Echo intent_id so result lines up with the gate's invariant.
        return self.result.model_copy(update={"intent_id": intent.intent_id})


@pytest.mark.asyncio
async def test_gate_success_transitions_to_indexing() -> None:
    sid = uuid4()
    store = FakeStore(sid)
    client = StaticClient(
        PaymentResult(intent_id="x", status="success", tx_signature=None, error=None)
    )

    result = await run_payment_gate(sid, "basic", store, client)  # type: ignore[arg-type]

    assert result.status == "success"
    assert store.status_calls == ["indexing"]
    assert len(store.intent_calls) == 1
    assert len(client.calls) == 1
    assert client.calls[0].tier == "basic"


@pytest.mark.asyncio
async def test_gate_failure_marks_failed_and_raises() -> None:
    sid = uuid4()
    store = FakeStore(sid)
    client = StaticClient(
        PaymentResult(intent_id="x", status="failed", tx_signature=None, error="card declined")
    )

    with pytest.raises(PaymentRequiredError) as exc_info:
        await run_payment_gate(sid, "basic", store, client)  # type: ignore[arg-type]

    # NO state mutation past update_status('failed').
    assert store.status_calls == ["failed"]
    assert "card declined" in exc_info.value.reason
    assert exc_info.value.session_id == sid


@pytest.mark.asyncio
async def test_gate_charge_exception_marks_failed() -> None:
    sid = uuid4()
    store = FakeStore(sid)

    class BoomClient:
        async def charge(self, intent: PaymentIntent) -> PaymentResult:
            raise RuntimeError("rpc timeout")

    with pytest.raises(PaymentRequiredError) as exc_info:
        await run_payment_gate(sid, "pro", store, BoomClient())  # type: ignore[arg-type]

    assert store.status_calls == ["failed"]
    assert "rpc timeout" in exc_info.value.reason


@pytest.mark.asyncio
async def test_gate_missing_session_raises_value_error() -> None:
    store = FakeStore(uuid4())

    with pytest.raises(ValueError, match="session not found"):
        await run_payment_gate(
            uuid4(),
            "basic",
            store,
            StaticClient(  # type: ignore[arg-type]
                PaymentResult(intent_id="x", status="success", tx_signature=None, error=None)
            ),
        )
