"""End-to-end pipeline behavior with mocked extractors, embedder, store."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from gecko_core.ingestion import pipeline
from gecko_core.models import SourceCandidate


class FakeStore:
    """In-memory stand-in for SessionStore — tracks idempotency."""

    def __init__(self) -> None:
        self.sources: dict[tuple[str, str], UUID] = {}
        self.chunks: list[tuple[UUID, int]] = []
        self.counts: dict[UUID, int] = {}

    async def insert_source(
        self, session_id: UUID, url: str, url_hash: str, type_: str
    ) -> UUID | None:
        key = (str(session_id), url_hash)
        if key in self.sources:
            return None
        sid = uuid4()
        self.sources[key] = sid
        return sid

    async def insert_chunks(
        self,
        session_id: UUID,
        source_id: UUID,
        chunks: list[tuple[int, str, list[float]]],
    ) -> int:
        self.chunks.append((source_id, len(chunks)))
        return len(chunks)

    async def set_source_chunk_count(self, source_id: UUID, count: int) -> None:
        self.counts[source_id] = count

    async def add_cost(self, session_id: UUID, kind: str, amount_usd: float) -> None:
        # No-op for the pipeline tests; cost tracking is verified separately.
        pass


def _candidate(url: str, type_: str = "web") -> SourceCandidate:
    return SourceCandidate(url=url, type=type_, score=0.5)


@pytest.fixture
def fake_embed() -> Any:
    async def _embed(texts: list[str], **_: Any) -> tuple[list[list[float]], int]:
        return [[0.0] * 1536 for _ in texts], 0

    return _embed


@pytest.mark.asyncio
async def test_mixed_batch_isolates_failures(fake_embed: Any) -> None:
    yt_with = _candidate("https://www.youtube.com/watch?v=aaaaaaaaaaa", "youtube")
    yt_without = _candidate("https://www.youtube.com/watch?v=bbbbbbbbbbb", "youtube")
    web_ok = _candidate("https://example.com/post", "web")
    web_bad = _candidate("https://example.com/broken", "web")

    async def fake_yt(url: str, providers: Any = None) -> tuple[str | None, float]:
        text = "captions text " * 100 if "aaaaaaaaaaa" in url else None
        return text, 0.0

    async def fake_web(url: str, **_: Any) -> tuple[str, float]:
        if "broken" in url:
            raise RuntimeError("network exploded")
        return "article body " * 200, 0.0

    store = FakeStore()
    sid = uuid4()

    with (
        patch.object(pipeline.youtube_extractor, "extract", side_effect=fake_yt),
        patch.object(pipeline.web_extractor, "extract", side_effect=fake_web),
        patch.object(pipeline, "embed_texts", side_effect=fake_embed),
    ):
        result = await pipeline.ingest(
            sid,
            [yt_with, yt_without, web_ok, web_bad],
            store,  # type: ignore[arg-type]
        )

    assert result.indexed == 2  # yt_with + web_ok
    assert result.skipped == 1  # yt_without (no captions)
    assert result.failed == 1  # web_bad (extractor raised)
    assert result.total_chunks > 0
    statuses = {o.url: o.status for o in result.outcomes}
    assert statuses[str(yt_with.url)] == "indexed"
    assert statuses[str(yt_without.url)] == "skipped"
    assert statuses[str(web_ok.url)] == "indexed"
    assert statuses[str(web_bad.url)] == "failed"


@pytest.mark.asyncio
async def test_reingest_same_url_yields_one_source(fake_embed: Any) -> None:
    cand = _candidate("https://example.com/post", "web")
    store = FakeStore()
    sid = uuid4()

    fake_web = AsyncMock(return_value=("article body " * 200, 0.0))

    with (
        patch.object(pipeline.web_extractor, "extract", new=fake_web),
        patch.object(pipeline, "embed_texts", side_effect=fake_embed),
    ):
        first = await pipeline.ingest(sid, [cand], store)  # type: ignore[arg-type]
        second = await pipeline.ingest(sid, [cand], store)  # type: ignore[arg-type]

    assert first.indexed == 1
    assert second.indexed == 0
    assert second.skipped == 1
    assert second.outcomes[0].reason == "duplicate"
    assert len(store.sources) == 1


@pytest.mark.asyncio
async def test_empty_source_list() -> None:
    store = FakeStore()
    result = await pipeline.ingest(uuid4(), [], store)  # type: ignore[arg-type]
    assert result.indexed == 0
    assert result.outcomes == []
