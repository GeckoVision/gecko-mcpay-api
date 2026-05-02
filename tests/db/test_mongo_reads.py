"""Tests for the Mongo read paths (S18-MONGO-READ-01).

Two layers of testing:
1. **Unit tests** — fake $vectorSearch backend that returns canned rows, used
   to verify the per-kind quota / global top-N union logic in
   :func:`match_chunks_hybrid_mongo`. This is the parity-critical path.
2. **Dispatch tests** — confirm ``rag_query`` and ``SessionStore.match_chunks_windowed``
   route to the Mongo reads when ``GECKO_CHUNK_STORE=mongo``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from gecko_core.db import mongo_reads

# ---------------------------------------------------------------------------
# Fake collection that simulates $vectorSearch by returning canned ranked docs
# ---------------------------------------------------------------------------


class _FakeAggCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = list(docs)

    def __aiter__(self) -> _FakeAggCursor:
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


class _FakeChunksColl:
    """Fakes ``$vectorSearch`` by reading docs sorted by injected ``score``.

    The fake doesn't actually compute cosine — it sorts the seeded docs by
    their pre-set ``score`` and applies the pipeline's ``filter`` (filters by
    ``session_id`` / ``project_id`` / ``captured_at`` if present) and ``limit``.
    """

    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []
        self.last_pipeline: list[dict[str, Any]] | None = None

    def aggregate(self, pipeline: list[dict[str, Any]]) -> _FakeAggCursor:
        self.last_pipeline = pipeline
        vs = pipeline[0]["$vectorSearch"]
        flt = vs.get("filter", {})
        limit = int(vs.get("limit", 10))

        def _matches(doc: dict[str, Any]) -> bool:
            for k, v in flt.items():
                got = doc.get(k)
                if isinstance(v, dict) and "$gte" in v:
                    if got is None or got < v["$gte"]:
                        return False
                elif got != v:
                    return False
            return True

        ranked = sorted(
            (d for d in self.docs if _matches(d)),
            key=lambda d: d.get("score", 0.0),
            reverse=True,
        )[:limit]
        # Project: pass `score` through as `score` and copy other fields.
        out: list[dict[str, Any]] = []
        for d in ranked:
            row = {
                "_id": d.get("_id"),
                "source_id": d.get("source_id"),
                "source_url": d.get("source_url"),
                "chunk_index": d.get("chunk_index"),
                "text": d.get("text"),
                "provider_kind": d.get("provider_kind", "web"),
                "captured_at": d.get("captured_at"),
                "score": d.get("score", 0.0),
            }
            out.append(row)
        return _FakeAggCursor(out)


@pytest.fixture
def fake_coll(monkeypatch: pytest.MonkeyPatch) -> _FakeChunksColl:
    coll = _FakeChunksColl()
    monkeypatch.setattr(mongo_reads, "chunks_collection", lambda: coll)
    return coll


def _seed_chunk(
    coll: _FakeChunksColl,
    *,
    session_id: UUID,
    chunk_id: str,
    score: float,
    provider_kind: str = "web",
    project_id: UUID | None = None,
) -> None:
    coll.docs.append(
        {
            "_id": chunk_id,
            "session_id": str(session_id),
            "source_id": str(uuid4()),
            "source_url": f"https://example.com/{chunk_id}",
            "chunk_index": 0,
            "text": f"text-{chunk_id}",
            "provider_kind": provider_kind,
            "project_id": str(project_id) if project_id else None,
            "score": score,
        }
    )


# ---------------------------------------------------------------------------
# match_chunks_mongo
# ---------------------------------------------------------------------------


class TestMatchChunksMongo:
    @pytest.mark.asyncio
    async def test_returns_top_k_by_score(self, fake_coll: _FakeChunksColl) -> None:
        sid = uuid4()
        _seed_chunk(fake_coll, session_id=sid, chunk_id="a", score=0.9)
        _seed_chunk(fake_coll, session_id=sid, chunk_id="b", score=0.7)
        _seed_chunk(fake_coll, session_id=sid, chunk_id="c", score=0.5)
        rows = await mongo_reads.match_chunks_mongo(
            session_id=sid, query_embedding=[0.0] * 1536, match_count=2
        )
        assert [r["text"] for r in rows] == ["text-a", "text-b"]
        assert rows[0]["similarity"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_filters_by_session(self, fake_coll: _FakeChunksColl) -> None:
        sid_a = uuid4()
        sid_b = uuid4()
        _seed_chunk(fake_coll, session_id=sid_a, chunk_id="a", score=0.9)
        _seed_chunk(fake_coll, session_id=sid_b, chunk_id="b", score=0.99)
        rows = await mongo_reads.match_chunks_mongo(
            session_id=sid_a, query_embedding=[0.0] * 1536, match_count=10
        )
        assert [r["text"] for r in rows] == ["text-a"]

    @pytest.mark.asyncio
    async def test_unconfigured_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mongo_reads, "chunks_collection", lambda: None)
        rows = await mongo_reads.match_chunks_mongo(
            session_id=uuid4(), query_embedding=[0.0] * 1536
        )
        assert rows == []


# ---------------------------------------------------------------------------
# match_chunks_windowed_mongo
# ---------------------------------------------------------------------------


class TestMatchChunksWindowedMongo:
    @pytest.mark.asyncio
    async def test_project_filter(self, fake_coll: _FakeChunksColl) -> None:
        proj_a = uuid4()
        proj_b = uuid4()
        sid = uuid4()
        _seed_chunk(
            fake_coll,
            session_id=sid,
            chunk_id="a",
            score=0.9,
            project_id=proj_a,
        )
        _seed_chunk(
            fake_coll,
            session_id=sid,
            chunk_id="b",
            score=0.99,
            project_id=proj_b,
        )
        rows = await mongo_reads.match_chunks_windowed_mongo(
            query_embedding=[0.0] * 1536,
            window_days=None,
            project_id=proj_a,
            match_count=10,
        )
        assert [r["text"] for r in rows] == ["text-a"]

    @pytest.mark.asyncio
    async def test_temporal_filter_disabled_when_window_days_zero(
        self, fake_coll: _FakeChunksColl
    ) -> None:
        sid = uuid4()
        _seed_chunk(fake_coll, session_id=sid, chunk_id="a", score=0.9)
        rows = await mongo_reads.match_chunks_windowed_mongo(
            query_embedding=[0.0] * 1536,
            window_days=0,
            project_id=None,
            match_count=10,
        )
        assert len(rows) == 1
        # Confirm no $gte filter was emitted in the pipeline
        flt = fake_coll.last_pipeline[0]["$vectorSearch"].get("filter", {})  # type: ignore[index]
        assert "captured_at" not in flt

    @pytest.mark.asyncio
    async def test_temporal_filter_applied(self, fake_coll: _FakeChunksColl) -> None:
        from datetime import UTC, datetime, timedelta

        sid = uuid4()
        old = datetime.now(UTC) - timedelta(days=30)
        recent = datetime.now(UTC) - timedelta(days=1)
        fake_coll.docs.append(
            {
                "_id": "old",
                "session_id": str(sid),
                "source_url": "u",
                "chunk_index": 0,
                "text": "old-doc",
                "captured_at": old,
                "score": 0.9,
                "provider_kind": "web",
            }
        )
        fake_coll.docs.append(
            {
                "_id": "recent",
                "session_id": str(sid),
                "source_url": "u",
                "chunk_index": 0,
                "text": "recent-doc",
                "captured_at": recent,
                "score": 0.5,
                "provider_kind": "web",
            }
        )
        rows = await mongo_reads.match_chunks_windowed_mongo(
            query_embedding=[0.0] * 1536,
            window_days=7,
            project_id=None,
            match_count=10,
        )
        assert [r["text"] for r in rows] == ["recent-doc"]


# ---------------------------------------------------------------------------
# match_chunks_hybrid_mongo — the parity-critical case
# ---------------------------------------------------------------------------


class TestMatchChunksHybridMongo:
    @pytest.mark.asyncio
    async def test_quota_includes_minority_in_candidate_pool(
        self, fake_coll: _FakeChunksColl
    ) -> None:
        """Verifies the hybrid SQL semantics: per-kind quota + global top-N
        UNION → sort by similarity → cap at match_count.

        With 5 web chunks (scores 0.9..0.86) and 1 bazaar at 0.5, and
        match_count=10, the UNION = quota(2 web + 1 baz) ∪ global(top 10
        of 6 docs) = 6 docs total. Sort + cap 10 returns all 6 including
        bazaar. This tests that the minority provider reaches the final
        slate when match_count is wide enough.

        Note: when match_count is *narrower* than the union, similarity
        sort drops minority providers — Postgres SQL has the same shape.
        The rescue happens in ``rag/query.py::_rerank_by_provider`` via
        the ``reserve_quota`` parameter, which is M4's caller, not M4
        itself.
        """
        sid = uuid4()
        for i in range(5):
            _seed_chunk(
                fake_coll,
                session_id=sid,
                chunk_id=f"web-{i}",
                score=0.9 - i * 0.01,
                provider_kind="web",
            )
        _seed_chunk(
            fake_coll,
            session_id=sid,
            chunk_id="baz",
            score=0.5,
            provider_kind="bazaar",
        )

        rows = await mongo_reads.match_chunks_hybrid_mongo(
            session_id=sid,
            query_embedding=[0.0] * 1536,
            match_count=10,
            per_kind_quota=2,
        )
        kinds = [r["provider_kind"] for r in rows]
        assert "bazaar" in kinds
        # Bazaar is sub-similarity, so it should appear last.
        assert kinds[-1] == "bazaar"

    @pytest.mark.asyncio
    async def test_minority_dropped_when_match_count_narrow(
        self, fake_coll: _FakeChunksColl
    ) -> None:
        """Negative case mirroring the SQL: with 20 web + 1 low-sim bazaar
        and match_count=8, the post-union similarity sort drops bazaar.
        Caller (rag_query) is responsible for the structural rescue via
        ``_rerank_by_provider(reserve_quota=...)``.
        """
        sid = uuid4()
        for i in range(20):
            _seed_chunk(
                fake_coll,
                session_id=sid,
                chunk_id=f"web-{i}",
                score=0.9 - i * 0.01,
                provider_kind="web",
            )
        _seed_chunk(
            fake_coll,
            session_id=sid,
            chunk_id="baz",
            score=0.5,
            provider_kind="bazaar",
        )
        rows = await mongo_reads.match_chunks_hybrid_mongo(
            session_id=sid,
            query_embedding=[0.0] * 1536,
            match_count=8,
            per_kind_quota=2,
        )
        kinds = [r["provider_kind"] for r in rows]
        assert kinds == ["web"] * 8

    @pytest.mark.asyncio
    async def test_dedup_by_id(self, fake_coll: _FakeChunksColl) -> None:
        """A doc that satisfies both quota and global must appear once."""
        sid = uuid4()
        _seed_chunk(
            fake_coll,
            session_id=sid,
            chunk_id="a",
            score=0.99,
            provider_kind="bazaar",
        )
        _seed_chunk(
            fake_coll,
            session_id=sid,
            chunk_id="b",
            score=0.5,
            provider_kind="web",
        )
        rows = await mongo_reads.match_chunks_hybrid_mongo(
            session_id=sid,
            query_embedding=[0.0] * 1536,
            match_count=8,
            per_kind_quota=2,
        )
        ids = [r["text"] for r in rows]
        assert ids.count("text-a") == 1

    @pytest.mark.asyncio
    async def test_capped_at_match_count(self, fake_coll: _FakeChunksColl) -> None:
        sid = uuid4()
        for kind in ("web", "bazaar", "arxiv", "twitsh"):
            for i in range(5):
                _seed_chunk(
                    fake_coll,
                    session_id=sid,
                    chunk_id=f"{kind}-{i}",
                    score=0.9 - i * 0.01,
                    provider_kind=kind,
                )
        rows = await mongo_reads.match_chunks_hybrid_mongo(
            session_id=sid,
            query_embedding=[0.0] * 1536,
            match_count=8,
            per_kind_quota=2,
        )
        assert len(rows) == 8

    @pytest.mark.asyncio
    async def test_quota_each_kind_gets_at_least_one(self, fake_coll: _FakeChunksColl) -> None:
        """All four kinds present → each must get quota=1 floor."""
        sid = uuid4()
        for i, kind in enumerate(("web", "bazaar", "arxiv", "twitsh")):
            _seed_chunk(
                fake_coll,
                session_id=sid,
                chunk_id=f"{kind}",
                score=0.9 - i * 0.1,
                provider_kind=kind,
            )
        rows = await mongo_reads.match_chunks_hybrid_mongo(
            session_id=sid,
            query_embedding=[0.0] * 1536,
            match_count=4,
            per_kind_quota=1,
        )
        kinds = {r["provider_kind"] for r in rows}
        assert kinds == {"web", "bazaar", "arxiv", "twitsh"}

    @pytest.mark.asyncio
    async def test_empty_pool(self, fake_coll: _FakeChunksColl) -> None:
        rows = await mongo_reads.match_chunks_hybrid_mongo(
            session_id=uuid4(),
            query_embedding=[0.0] * 1536,
            match_count=8,
            per_kind_quota=2,
        )
        assert rows == []


# ---------------------------------------------------------------------------
# rag_query dispatch
# ---------------------------------------------------------------------------


class TestRagQueryDispatch:
    @pytest.mark.asyncio
    async def test_rag_query_routes_to_mongo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_coll: _FakeChunksColl,
    ) -> None:
        from gecko_core.db import chunk_store as cs_mod

        monkeypatch.setenv("GECKO_CHUNK_STORE", "mongo")
        cs_mod.get_chunk_store.cache_clear()

        # Stub the embedder so we don't hit OpenAI
        async def _fake_embed(texts: list[str]) -> tuple[list[list[float]], int]:
            return [[0.0] * 1536 for _ in texts], 0

        from gecko_core.rag import query as query_mod

        monkeypatch.setattr(query_mod, "embed", _fake_embed)

        sid = uuid4()
        _seed_chunk(fake_coll, session_id=sid, chunk_id="a", score=0.9)
        _seed_chunk(
            fake_coll,
            session_id=sid,
            chunk_id="b",
            score=0.5,
            provider_kind="bazaar",
        )

        # SessionStore stub — store argument bypasses real Supabase init
        class _StubStore:
            _client = None

            async def add_cost(self, *a: Any, **kw: Any) -> None:
                pass

        chunks = await query_mod.rag_query(sid, "any", top_k=8, store=_StubStore())  # type: ignore[arg-type]
        kinds = [c.provider_kind for c in chunks]
        assert "bazaar" in kinds

        cs_mod.get_chunk_store.cache_clear()


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    from gecko_core.db import chunk_store as cs_mod

    cs_mod.get_chunk_store.cache_clear()
    yield
    cs_mod.get_chunk_store.cache_clear()
