"""Unit tests for SessionStore. Mocks the supabase client — no real DB."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from gecko_core.sessions import SessionRecord, SessionStore


def _make_response(data: list[dict[str, Any]]) -> MagicMock:
    resp = MagicMock()
    resp.data = data
    return resp


class FakeQuery:
    """Chainable stub that records calls and returns canned responses on execute()."""

    def __init__(self, response: MagicMock) -> None:
        self._response = response
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> FakeQuery:
        self.calls.append((name, args, kwargs))
        return self

    def insert(self, *a: Any, **kw: Any) -> FakeQuery:
        return self._record("insert", *a, **kw)

    def update(self, *a: Any, **kw: Any) -> FakeQuery:
        return self._record("update", *a, **kw)

    def select(self, *a: Any, **kw: Any) -> FakeQuery:
        return self._record("select", *a, **kw)

    def eq(self, *a: Any, **kw: Any) -> FakeQuery:
        return self._record("eq", *a, **kw)

    def is_(self, *a: Any, **kw: Any) -> FakeQuery:
        return self._record("is_", *a, **kw)

    def order(self, *a: Any, **kw: Any) -> FakeQuery:
        return self._record("order", *a, **kw)

    def limit(self, *a: Any, **kw: Any) -> FakeQuery:
        return self._record("limit", *a, **kw)

    def execute(self) -> MagicMock:
        return self._response


class FakeClient:
    """Minimal stand-in for supabase.Client.table()."""

    def __init__(self) -> None:
        self.queries: dict[str, FakeQuery] = {}
        self.last_query: FakeQuery | None = None

    def queue(self, table: str, data: list[dict[str, Any]]) -> FakeQuery:
        q = FakeQuery(_make_response(data))
        self.queries[table] = q
        return q

    def table(self, name: str) -> FakeQuery:
        q = self.queries.get(name) or FakeQuery(_make_response([]))
        self.last_query = q
        return q


@pytest.mark.asyncio
async def test_create_returns_uuid_and_persists_payload() -> None:
    sid = uuid4()
    fake = FakeClient()
    fake.queue(
        "sessions",
        [{"id": str(sid)}],
    )
    store = SessionStore(client=fake)  # type: ignore[arg-type]

    result = await store.create(idea="hotel guide", tier="basic")

    assert result == sid
    calls = fake.queries["sessions"].calls
    assert calls[0][0] == "insert"
    payload = calls[0][1][0]
    assert payload == {
        "idea": "hotel guide",
        "tier": "basic",
        "payment_mode": "stub",
        "status": "pending",
    }


@pytest.mark.asyncio
async def test_create_then_get_round_trip() -> None:
    sid = uuid4()
    now = datetime.now(UTC)
    fake = FakeClient()
    fake.queue("sessions", [{"id": str(sid)}])

    store = SessionStore(client=fake)  # type: ignore[arg-type]
    new_id = await store.create(idea="x", tier="pro", payment_mode="live")
    assert new_id == sid

    # Re-queue for the get() call.
    fake.queue(
        "sessions",
        [
            {
                "id": str(sid),
                "idea": "x",
                "tier": "pro",
                "status": "pending",
                "payment_intent_id": None,
                "payment_mode": "live",
                "created_at": now.isoformat(),
                "completed_at": None,
                "deleted_at": None,
            }
        ],
    )
    record = await store.get(sid)
    assert isinstance(record, SessionRecord)
    assert record.id == sid
    assert record.tier == "pro"
    assert record.payment_mode == "live"
    assert record.status == "pending"


@pytest.mark.asyncio
async def test_get_returns_none_when_missing() -> None:
    fake = FakeClient()
    fake.queue("sessions", [])
    store = SessionStore(client=fake)  # type: ignore[arg-type]

    result = await store.get(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_update_status_sends_status_patch() -> None:
    sid = uuid4()
    fake = FakeClient()
    fake.queue("sessions", [])
    store = SessionStore(client=fake)  # type: ignore[arg-type]

    await store.update_status(sid, "indexing")

    calls = fake.queries["sessions"].calls
    assert calls[0][0] == "update"
    assert calls[0][1][0] == {"status": "indexing"}
    assert ("eq", ("id", str(sid)), {}) in calls


@pytest.mark.asyncio
async def test_update_status_complete_stamps_completed_at() -> None:
    sid = uuid4()
    fake = FakeClient()
    fake.queue("sessions", [])
    store = SessionStore(client=fake)  # type: ignore[arg-type]

    await store.update_status(sid, "complete")

    patch = fake.queries["sessions"].calls[0][1][0]
    assert patch["status"] == "complete"
    assert "completed_at" in patch


@pytest.mark.asyncio
async def test_list_sources_empty() -> None:
    fake = FakeClient()
    fake.queue("sources", [])
    store = SessionStore(client=fake)  # type: ignore[arg-type]

    sources = await store.list_sources(uuid4())
    assert sources == []


@pytest.mark.asyncio
async def test_list_sources_returns_source_info() -> None:
    sid = UUID("11111111-1111-1111-1111-111111111111")
    indexed = datetime.now(UTC).isoformat()
    fake = FakeClient()
    fake.queue(
        "sources",
        [
            {
                "url": "https://example.com/a",
                "type": "web",
                "chunk_count": 3,
                "indexed_at": indexed,
            }
        ],
    )
    store = SessionStore(client=fake)  # type: ignore[arg-type]

    sources = await store.list_sources(sid)
    assert len(sources) == 1
    assert sources[0].type == "web"
    assert sources[0].chunk_count == 3
