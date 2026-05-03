"""Contract test for _embed_voyage — fake voyageai module, no real API calls."""

from __future__ import annotations

import sys
from typing import Any

import pytest
from gecko_core.ingestion.embedder import _embed_voyage

FAKE_DIM = 1024


class _FakeEmbeddingsObject:
    def __init__(self, texts: list[str]) -> None:
        self.embeddings = [[float(i)] * FAKE_DIM for i in range(len(texts))]
        self.total_tokens = len(texts) * 4


class _FakeVoyageAsyncClient:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key
        self.calls: list[dict[str, Any]] = []

    async def embed(
        self,
        *,
        texts: list[str],
        model: str,
        input_type: Any = None,
        **_: Any,
    ) -> _FakeEmbeddingsObject:
        self.calls.append({"texts": list(texts), "model": model})
        return _FakeEmbeddingsObject(texts)


class _FakeVoyageModule:
    def AsyncClient(self, *, api_key: str) -> _FakeVoyageAsyncClient:
        return _FakeVoyageAsyncClient(api_key=api_key)


@pytest.fixture(autouse=True)
def inject_fake_voyageai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "voyageai", _FakeVoyageModule())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_embed_voyage_returns_correct_shape() -> None:
    vecs, tokens = await _embed_voyage(["hello", "world"], api_key="pa-test", model="voyage-3")
    assert len(vecs) == 2
    assert len(vecs[0]) == FAKE_DIM
    assert tokens == 8  # 2 texts * 4 tokens each


@pytest.mark.asyncio
async def test_embed_voyage_empty_returns_empty() -> None:
    # _embed_voyage is NOT called when texts is empty — embed() handles that.
    # But if called directly it should return empty gracefully.
    vecs, tokens = await _embed_voyage([], api_key="pa-test", model="voyage-3")
    assert vecs == []
    assert tokens == 0


@pytest.mark.asyncio
async def test_embed_voyage_batches_at_batch_size() -> None:
    call_log: list[list[str]] = []

    class _TrackingClient:
        async def embed(
            self,
            *,
            texts: list[str],
            model: str,
            **_: Any,
        ) -> _FakeEmbeddingsObject:
            call_log.append(list(texts))
            return _FakeEmbeddingsObject(texts)

    class _TrackingModule:
        def AsyncClient(self, *, api_key: str) -> _TrackingClient:
            return _TrackingClient()

    sys.modules["voyageai"] = _TrackingModule()  # type: ignore[assignment]

    vecs, _ = await _embed_voyage(
        ["a", "b", "c"],
        api_key="pa-test",
        model="voyage-3",
        batch_size=1,
    )
    assert len(vecs) == 3
    assert len(call_log) == 3  # one call per text


@pytest.mark.asyncio
async def test_embed_voyage_order_preserving() -> None:
    """Vectors come back in the same order as input texts."""
    vecs, _ = await _embed_voyage(
        ["first", "second", "third"],
        api_key="pa-test",
        model="voyage-3",
    )
    # The fake assigns index-based vectors: vec[0][0] = 0.0, vec[1][0] = 1.0, etc.
    assert vecs[0][0] == pytest.approx(0.0)
    assert vecs[1][0] == pytest.approx(1.0)
    assert vecs[2][0] == pytest.approx(2.0)
