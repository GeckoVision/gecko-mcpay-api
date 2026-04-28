"""Unit tests for `gecko_core.rag.query.rag_query`.

Mocks the supabase RPC seam and the embedder. No network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


class _FakeRpcResp:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _FakeRpc:
    def __init__(self, resp: _FakeRpcResp) -> None:
        self._resp = resp
        self.last_args: tuple[str, dict[str, Any]] | None = None

    def __call__(self, name: str, params: dict[str, Any]) -> _FakeRpc:
        self.last_args = (name, params)
        return self

    def execute(self) -> _FakeRpcResp:
        return self._resp


class _FakeClient:
    def __init__(self, resp: _FakeRpcResp) -> None:
        self.rpc = _FakeRpc(resp)


@pytest.mark.asyncio
async def test_rag_query_returns_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    from gecko_core.rag import query as q

    sid = uuid4()
    chunk_source_id = uuid4()
    fake_resp = _FakeRpcResp(
        [
            {
                "id": str(uuid4()),
                "source_id": str(chunk_source_id),
                "source_url": "https://example.com/a",
                "chunk_index": 0,
                "text": "hello",
                "similarity": 0.91,
            },
            {
                "id": str(uuid4()),
                "source_id": str(chunk_source_id),
                "source_url": "https://example.com/b",
                "chunk_index": 3,
                "text": "world",
                "similarity": 0.72,
            },
        ]
    )

    fake_store = MagicMock()
    fake_store._client = _FakeClient(fake_resp)

    async def _fake_embed(texts: list[str]) -> tuple[list[list[float]], int]:
        return [[0.1] * 1536], 0

    monkeypatch.setattr(q, "embed", _fake_embed)

    chunks = await q.rag_query(sid, "what is x?", top_k=5, store=fake_store)

    assert len(chunks) == 2
    assert chunks[0].similarity == pytest.approx(0.91)
    assert str(chunks[0].source_url) == "https://example.com/a"
    assert chunks[1].chunk_index == 3
    name, params = fake_store._client.rpc.last_args
    assert name == "match_chunks"
    assert params["p_session_id"] == str(sid)
    assert params["match_count"] == 5


@pytest.mark.asyncio
async def test_rag_query_empty_question() -> None:
    from gecko_core.rag import query as q

    fake_store = MagicMock()
    fake_store._client = _FakeClient(_FakeRpcResp([]))
    chunks = await q.rag_query(uuid4(), "   ", top_k=5, store=fake_store)
    assert chunks == []


@pytest.mark.asyncio
async def test_rag_query_zero_top_k() -> None:
    from gecko_core.rag import query as q

    fake_store = MagicMock()
    fake_store._client = _FakeClient(_FakeRpcResp([]))
    chunks = await q.rag_query(uuid4(), "x", top_k=0, store=fake_store)
    assert chunks == []
