"""Unit tests for `voyage_rerank_batch` (S20-RERANKER-BATCH-01).

The batch helper fans out N per-(query,chunks) reranks concurrently via
``asyncio.gather``. These tests pin:

* parallel dispatch semantics (one ``gather`` call wrapping N coroutines)
* per-item failure isolation (one bad item degrades to passthrough; the
  rest still get reranked)
* input-order preservation
* empty-input fast path
* flag-off short-circuit (no Voyage import / call)

We stub ``voyage_rerank`` itself so no real API call ever fires.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import pytest
from gecko_core.rag import voyage_rerank as voyage_mod
from gecko_core.rag.query import RagChunk
from gecko_core.rag.voyage_rerank import voyage_rerank_batch


def _make_chunk(idx: int, sim: float = 0.8, kind: str = "web") -> RagChunk:
    return RagChunk(
        source_id=uuid4(),
        source_url=f"https://example.com/doc/{idx}",
        chunk_index=idx,
        text=f"chunk {idx} content",
        similarity=sim,
        provider_kind=kind,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_batch_empty_list_returns_empty() -> None:
    """`voyage_rerank_batch([])` short-circuits to `[]`, no Voyage touch."""
    out = await voyage_rerank_batch([])
    assert out == []


@pytest.mark.asyncio
async def test_batch_no_voyage_dep_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag off -> per-item passthrough; voyage_rerank is never invoked."""
    monkeypatch.delenv("GECKO_RERANKER", raising=False)

    invoked = {"count": 0}

    async def _spy(*args: Any, **kwargs: Any) -> list[RagChunk]:
        invoked["count"] += 1
        return []

    monkeypatch.setattr(voyage_mod, "voyage_rerank", _spy)

    items = [
        ("q1", [_make_chunk(i) for i in range(5)]),
        ("q2", [_make_chunk(i) for i in range(3)]),
    ]
    out = await voyage_rerank_batch(items, top_n=4)
    assert invoked["count"] == 0
    # Item 0 has 5 chunks -> truncated to 4. Item 1 has 3 -> all 3.
    assert [c.chunk_index for c in out[0]] == [0, 1, 2, 3]
    assert [c.chunk_index for c in out[1]] == [0, 1, 2]


@pytest.mark.asyncio
async def test_batch_parallel_dispatches_one_gather(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag on -> exactly one `asyncio.gather` wraps all N coroutines."""
    monkeypatch.setenv("GECKO_RERANKER", "voyage")

    async def _stub(query: str, chunks: list[RagChunk], top_n: int = 8) -> list[RagChunk]:
        return chunks[:top_n]

    monkeypatch.setattr(voyage_mod, "voyage_rerank", _stub)

    gather_calls: list[int] = []
    real_gather = voyage_mod.asyncio.gather

    def _spy_gather(*aws: Any, **kwargs: Any) -> Any:
        gather_calls.append(len(aws))
        return real_gather(*aws, **kwargs)

    monkeypatch.setattr(voyage_mod.asyncio, "gather", _spy_gather)

    items = [(f"q{i}", [_make_chunk(j) for j in range(4)]) for i in range(5)]
    out = await voyage_rerank_batch(items, top_n=2)

    assert gather_calls == [5]  # exactly one gather, exactly N=5 awaitables
    assert len(out) == 5
    assert all(len(slate) == 2 for slate in out)


@pytest.mark.asyncio
async def test_batch_per_item_failure_degrades_only_that_item(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One coroutine raises -> only that slot falls back to chunks[:top_n];
    sibling items still surface their (mocked) reranked output."""
    monkeypatch.setenv("GECKO_RERANKER", "voyage")

    async def _stub(query: str, chunks: list[RagChunk], top_n: int = 8) -> list[RagChunk]:
        if query == "boom":
            raise RuntimeError("voyage 503")
        # Reverse order so a real rerank is observable in the output.
        return list(reversed(chunks[:top_n]))

    monkeypatch.setattr(voyage_mod, "voyage_rerank", _stub)

    good_a = [_make_chunk(i) for i in range(4)]
    bad = [_make_chunk(100 + i) for i in range(4)]
    good_b = [_make_chunk(200 + i) for i in range(4)]
    items = [("q-a", good_a), ("boom", bad), ("q-b", good_b)]

    with caplog.at_level(logging.WARNING, logger="gecko_core.rag.voyage_rerank"):
        out = await voyage_rerank_batch(items, top_n=3)

    # Good slots reversed (rerank observed); bad slot unchanged truncation.
    assert [c.chunk_index for c in out[0]] == [2, 1, 0]
    assert [c.chunk_index for c in out[1]] == [100, 101, 102]
    assert [c.chunk_index for c in out[2]] == [202, 201, 200]
    assert any("batch.item_failed" in rec.message for rec in caplog.records)
    assert any("idx=1" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_batch_preserves_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`asyncio.gather` returns in input order regardless of completion
    order; pin that contract here so re-ordering bugs trip immediately."""
    import asyncio as _asyncio

    monkeypatch.setenv("GECKO_RERANKER", "voyage")

    async def _stub(query: str, chunks: list[RagChunk], top_n: int = 8) -> list[RagChunk]:
        # Earlier-index queries sleep longer -> finish later than later
        # ones. Forces gather to actually preserve input order rather
        # than completion order.
        delay = 0.01 * (10 - int(query.removeprefix("q")))
        await _asyncio.sleep(delay)
        return chunks[:top_n]

    monkeypatch.setattr(voyage_mod, "voyage_rerank", _stub)

    items = [(f"q{i}", [_make_chunk(i * 10 + j) for j in range(3)]) for i in range(4)]
    out = await voyage_rerank_batch(items, top_n=3)

    assert len(out) == 4
    # output[i] must correspond to items[i].
    for i, slate in enumerate(out):
        assert [c.chunk_index for c in slate] == [i * 10, i * 10 + 1, i * 10 + 2]


@pytest.mark.asyncio
async def test_batch_emits_latency_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One structured INFO line per batch with n_items + voyage_calls + wall_ms."""
    monkeypatch.setenv("GECKO_RERANKER", "voyage")

    async def _stub(query: str, chunks: list[RagChunk], top_n: int = 8) -> list[RagChunk]:
        return chunks[:top_n]

    monkeypatch.setattr(voyage_mod, "voyage_rerank", _stub)

    items = [(f"q{i}", [_make_chunk(j) for j in range(4)]) for i in range(3)]
    with caplog.at_level(logging.INFO, logger="gecko_core.rag.voyage_rerank"):
        await voyage_rerank_batch(items, top_n=2)

    msgs = [rec.message for rec in caplog.records]
    assert any(
        "voyage_rerank.batch.done" in m and "n_items=3" in m and "voyage_calls=3" in m for m in msgs
    )
