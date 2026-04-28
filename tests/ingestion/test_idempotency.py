"""Same URL ingested twice → only one source row."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from gecko_core.sessions.store import SessionStore


class _Resp:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _UpsertChain:
    """Records the upsert payload and on_conflict args, returns canned data."""

    def __init__(self, response_data: list[dict[str, Any]]) -> None:
        self.captured: dict[str, Any] = {}
        self._response = _Resp(response_data)

    def upsert(self, payload: dict[str, Any], **kwargs: Any) -> _UpsertChain:
        self.captured["payload"] = payload
        self.captured["kwargs"] = kwargs
        return self

    def execute(self) -> _Resp:
        return self._response


class _Client:
    def __init__(self, chain: _UpsertChain) -> None:
        self._chain = chain

    def table(self, _name: str) -> _UpsertChain:
        return self._chain


@pytest.mark.asyncio
async def test_first_insert_returns_uuid() -> None:
    new_id = uuid4()
    chain = _UpsertChain([{"id": str(new_id)}])
    store = SessionStore(client=_Client(chain))  # type: ignore[arg-type]

    sid = await store.insert_source(
        session_id=uuid4(),
        url="https://example.com/x",
        url_hash="abc123",
        type_="web",
    )
    assert sid == new_id
    assert chain.captured["kwargs"]["on_conflict"] == "session_id,url_hash"
    assert chain.captured["kwargs"]["ignore_duplicates"] is True


@pytest.mark.asyncio
async def test_duplicate_returns_none() -> None:
    chain = _UpsertChain([])  # ignore_duplicates → empty data on conflict
    store = SessionStore(client=_Client(chain))  # type: ignore[arg-type]

    sid = await store.insert_source(
        session_id=uuid4(),
        url="https://example.com/x",
        url_hash="abc123",
        type_="web",
    )
    assert sid is None


def test_url_hash_is_stable() -> None:
    from gecko_core.ingestion.pipeline import url_hash

    h1 = url_hash("https://example.com/a")
    h2 = url_hash("https://example.com/a")
    h3 = url_hash("https://example.com/b")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_insert_source_payload_shape() -> None:
    new_id = uuid4()
    chain = _UpsertChain([{"id": str(new_id)}])
    store = SessionStore(client=_Client(chain))  # type: ignore[arg-type]
    session_id = UUID("11111111-1111-1111-1111-111111111111")

    await store.insert_source(
        session_id=session_id,
        url="https://youtube.com/watch?v=abc",
        url_hash="hash",
        type_="youtube",
    )
    payload = chain.captured["payload"]
    assert payload["session_id"] == str(session_id)
    assert payload["url"] == "https://youtube.com/watch?v=abc"
    assert payload["url_hash"] == "hash"
    assert payload["type"] == "youtube"


# Silence unused-import nag from MagicMock
_ = MagicMock
