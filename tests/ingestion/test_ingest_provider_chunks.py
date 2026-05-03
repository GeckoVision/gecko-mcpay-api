"""S17-WEDGE-WIRE-02 — ``ingest_provider_chunks`` end-to-end against a fake store.

Mirrors the in-memory pattern in ``tests/orchestration/test_workflows_persistence.py``.
Asserts:
  - ``insert_source`` called with the correct synthetic_uri + provider_kind
  - Embedder called for each chunk (cache miss path)
  - ``insert_chunks`` called with provider_kind kwarg
  - Returns the count
  - Cache hit path skips embed entirely
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

import pytest
from gecko_core.ingestion import pipeline
from gecko_core.ingestion.types import ProviderChunk


class _FakeStore:
    EMBED_DIM = 1024

    def __init__(self) -> None:
        self.insert_source_calls: list[dict[str, Any]] = []
        self.insert_chunks_calls: list[dict[str, Any]] = []
        self.cache_get_calls: list[tuple[str, list[int], str | None]] = []
        self.cache_put_calls: list[tuple[str, list[tuple[int, str, list[float]]], str | None]] = []
        self.set_chunk_count_calls: list[tuple[UUID, int]] = []
        self.audit_calls: list[dict[str, Any]] = []
        self.costs: list[tuple[UUID, str, float]] = []
        self._cache: dict[str, dict[int, list[float]]] = {}
        self._next_source_id: UUID | None = uuid4()
        self._dedup_urls: set[str] = set()

    async def insert_source(
        self,
        *,
        session_id: UUID,
        url: str,
        url_hash: str,
        type_: str,
        provider_kind: str = "web",
    ) -> UUID | None:
        self.insert_source_calls.append(
            {
                "session_id": session_id,
                "url": url,
                "url_hash": url_hash,
                "type_": type_,
                "provider_kind": provider_kind,
            }
        )
        if url in self._dedup_urls:
            return None
        self._dedup_urls.add(url)
        return self._next_source_id

    async def insert_chunks(
        self,
        session_id: UUID,
        source_id: UUID,
        chunks: list[tuple[int, str, list[float]]],
        *,
        provider_kind: str = "web",
        source_url: str | None = None,
    ) -> int:
        self.insert_chunks_calls.append(
            {
                "session_id": session_id,
                "source_id": source_id,
                "rows": list(chunks),
                "provider_kind": provider_kind,
            }
        )
        return len(chunks)

    async def get_chunk_cache(
        self,
        url_hash: str,
        indices: list[int],
        *,
        embed_model: str | None = None,
    ) -> dict[int, list[float]]:
        self.cache_get_calls.append((url_hash, list(indices), embed_model))
        return dict(self._cache.get(url_hash, {}))

    async def put_chunk_cache(
        self,
        url_hash: str,
        rows: list[tuple[int, str, list[float]]],
        *,
        embed_model: str | None = None,
    ) -> None:
        self.cache_put_calls.append((url_hash, list(rows), embed_model))
        bucket = self._cache.setdefault(url_hash, {})
        for idx, _text, vec in rows:
            bucket[idx] = vec

    async def set_source_chunk_count(self, source_id: UUID, count: int) -> None:
        self.set_chunk_count_calls.append((source_id, count))

    async def add_cost(self, session_id: UUID, kind: str, amount_usd: float) -> None:
        self.costs.append((session_id, kind, float(amount_usd)))

    async def insert_chunks_write_audit(self, **kwargs: Any) -> None:
        self.audit_calls.append(dict(kwargs))


def _seed_cache_hit(store: _FakeStore, synthetic_uri: str, n: int) -> None:
    uhash = hashlib.sha256(synthetic_uri.encode("utf-8")).hexdigest()
    store._cache[uhash] = {i: [0.0] * store.EMBED_DIM for i in range(n)}


@pytest.mark.asyncio
async def test_ingest_provider_chunks_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _FakeStore()
    sid = uuid4()
    chunks = [
        ProviderChunk(resource_id="r1", chunk_index=0, text="alpha", metadata={}),
        ProviderChunk(resource_id="r1", chunk_index=1, text="beta", metadata={}),
    ]
    synthetic_uri = "bazaar://crypto-onramp/coinbase"

    embed_calls: list[list[str]] = []

    async def _fake_embed(texts: list[str], **_kw: Any) -> tuple[list[list[float]], int]:
        embed_calls.append(list(texts))
        return [[0.1] * store.EMBED_DIM for _ in texts], 12

    monkeypatch.setattr(pipeline, "embed_texts", _fake_embed)

    inserted = await pipeline.ingest_provider_chunks(
        session_id=sid,
        provider_kind="bazaar",
        resource_id="crypto-onramp",
        synthetic_uri=synthetic_uri,
        chunks=chunks,
        store=store,  # type: ignore[arg-type]
    )

    assert inserted == 2
    assert len(store.insert_source_calls) == 1
    src = store.insert_source_calls[0]
    assert src["url"] == synthetic_uri
    assert src["provider_kind"] == "bazaar"
    assert src["type_"] == "provider"

    assert len(embed_calls) == 1
    assert embed_calls[0] == ["alpha", "beta"]

    assert len(store.insert_chunks_calls) == 1
    ic = store.insert_chunks_calls[0]
    assert ic["provider_kind"] == "bazaar"
    assert [row[1] for row in ic["rows"]] == ["alpha", "beta"]

    # Audit row emitted on success.
    assert len(store.audit_calls) == 1
    assert store.audit_calls[0]["error_kind"] == "none"
    assert store.audit_calls[0]["succeeded"] == 2


@pytest.mark.asyncio
async def test_ingest_provider_chunks_cache_hit_skips_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FakeStore()
    sid = uuid4()
    synthetic_uri = "https://arxiv.org/abs/2401.12345"
    _seed_cache_hit(store, synthetic_uri, n=1)

    chunks = [
        ProviderChunk(
            resource_id="2401.12345",
            chunk_index=0,
            text="abstract text",
            metadata={"abs_url": synthetic_uri},
        )
    ]

    embed_calls: list[list[str]] = []

    async def _fake_embed(texts: list[str], **_kw: Any) -> tuple[list[list[float]], int]:
        embed_calls.append(list(texts))
        return [[0.0] * store.EMBED_DIM], 0

    monkeypatch.setattr(pipeline, "embed_texts", _fake_embed)

    inserted = await pipeline.ingest_provider_chunks(
        session_id=sid,
        provider_kind="arxiv",
        resource_id="2401.12345",
        synthetic_uri=synthetic_uri,
        chunks=chunks,
        store=store,  # type: ignore[arg-type]
    )

    assert inserted == 1
    assert embed_calls == []  # full cache hit -> embedder NOT called
    assert store.insert_chunks_calls[0]["provider_kind"] == "arxiv"


@pytest.mark.asyncio
async def test_ingest_provider_chunks_dedup_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FakeStore()
    sid = uuid4()
    synthetic_uri = f"twitsh://session/{sid}"
    # First call: write succeeds; second call hits the dedup path.
    store._dedup_urls.add(synthetic_uri)

    async def _fake_embed(texts: list[str], **_kw: Any) -> tuple[list[list[float]], int]:
        return [[0.0] * store.EMBED_DIM for _ in texts], 0

    monkeypatch.setattr(pipeline, "embed_texts", _fake_embed)

    inserted = await pipeline.ingest_provider_chunks(
        session_id=sid,
        provider_kind="twitsh",
        resource_id=str(sid),
        synthetic_uri=synthetic_uri,
        chunks=[ProviderChunk(resource_id="x", chunk_index=0, text="hi", metadata={})],
        store=store,  # type: ignore[arg-type]
    )
    assert inserted == 0
    assert store.insert_chunks_calls == []


@pytest.mark.asyncio
async def test_ingest_provider_chunks_filters_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FakeStore()
    sid = uuid4()

    async def _fake_embed(texts: list[str], **_kw: Any) -> tuple[list[list[float]], int]:
        return [[0.0] * store.EMBED_DIM for _ in texts], 0

    monkeypatch.setattr(pipeline, "embed_texts", _fake_embed)

    inserted = await pipeline.ingest_provider_chunks(
        session_id=sid,
        provider_kind="bazaar",
        resource_id="r1",
        synthetic_uri="bazaar://r1",
        chunks=[
            ProviderChunk(resource_id="r1", chunk_index=0, text="   ", metadata={}),
            ProviderChunk(resource_id="r1", chunk_index=1, text="", metadata={}),
        ],
        store=store,  # type: ignore[arg-type]
    )
    assert inserted == 0
    # Empty filter applied before insert_source — no calls at all.
    assert store.insert_source_calls == []
