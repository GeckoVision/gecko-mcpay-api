"""Unit tests for SessionStore. Mocks the supabase client — no real DB."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
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

    def rpc(self, name: str, params: dict[str, Any]) -> FakeQuery:
        # Reuse the queue map keyed by `rpc:<name>` for symmetry with table().
        q = self.queries.get(f"rpc:{name}") or FakeQuery(_make_response([]))
        q.calls.append(("rpc", (name, params), {}))
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
        "phase": "pre_product",
    }


@pytest.mark.asyncio
async def test_create_with_phase_and_parent_session_id() -> None:
    """S13-PHASE-01 — create() threads phase + parent_session_id into the row."""
    sid = uuid4()
    parent_id = uuid4()
    fake = FakeClient()
    fake.queue("sessions", [{"id": str(sid)}])
    store = SessionStore(client=fake)  # type: ignore[arg-type]

    result = await store.create(
        idea="pulse on hotel guide",
        tier="pro",
        phase="during_build",
        parent_session_id=parent_id,
    )

    assert result == sid
    payload = fake.queries["sessions"].calls[0][1][0]
    assert payload["phase"] == "during_build"
    assert payload["parent_session_id"] == str(parent_id)


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


@pytest.mark.asyncio
async def test_match_chunks_windowed_mongo_dispatches_vectorsearch() -> None:
    """match_chunks_windowed_mongo issues a $vectorSearch pipeline with the
    correct project_id filter and returns rows shaped like the Supabase RPC."""
    from gecko_core.db.mongo_reads import match_chunks_windowed_mongo

    project_id = uuid4()
    chunk_id = uuid4()
    source_id = uuid4()
    captured = datetime.now(UTC)

    result_doc = {
        "_id": chunk_id,
        "source_id": str(source_id),
        "source_url": "https://example.com/x",
        "chunk_index": 0,
        "text": "hello",
        "captured_at": captured,
        "provider_kind": "web",
        "score": 0.91,
    }

    class _AsyncAggCursor:
        def __init__(self, docs: list[dict[str, Any]]) -> None:
            self._docs = list(docs)

        def __aiter__(self) -> _AsyncAggCursor:
            return self

        async def __anext__(self) -> dict[str, Any]:
            if not self._docs:
                raise StopAsyncIteration
            return self._docs.pop(0)

    captured_pipeline: list[list[dict[str, Any]]] = []

    fake_coll = MagicMock()

    def _aggregate(pipeline: list[dict[str, Any]]) -> _AsyncAggCursor:
        captured_pipeline.append(pipeline)
        return _AsyncAggCursor([result_doc])

    fake_coll.aggregate = _aggregate

    with patch("gecko_core.db.mongo_reads.chunks_collection", return_value=fake_coll):
        rows = await match_chunks_windowed_mongo(
            query_embedding=[0.0] * 1024,
            window_days=14,
            project_id=project_id,
            match_count=5,
        )

    assert len(rows) == 1
    assert rows[0]["similarity"] == pytest.approx(0.91)
    assert rows[0]["text"] == "hello"

    # The pipeline must contain a $vectorSearch stage with project_id filter.
    assert captured_pipeline, "aggregate() was never called"
    pipeline = captured_pipeline[0]
    vs_stage = pipeline[0]["$vectorSearch"]
    assert vs_stage["filter"]["project_id"] == str(project_id)
