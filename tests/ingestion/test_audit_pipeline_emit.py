"""S16-INGEST-01 — verify `_process_one` emits exactly one audit row per
source-batch exit, with the right `error_kind` bucket.

Stub mode only — no live Supabase. The FakeStore records every audit
call so the test can assert the bucket directly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from gecko_core.ingestion import pipeline
from gecko_core.models import SourceCandidate


class _AuditingFakeStore:
    """FakeStore that records audit emissions and can be told to fail
    `insert_chunks` on demand (FM-1 simulation)."""

    def __init__(self, *, raise_exc: Exception | None = None) -> None:
        self.audit_rows: list[dict[str, Any]] = []
        self.sources: dict[tuple[str, str], UUID] = {}
        self._raise_exc = raise_exc

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
        *,
        provider_kind: str = "web",
        source_url: str | None = None,
    ) -> int:
        if self._raise_exc is not None:
            raise self._raise_exc
        # S16-INGEST-02 — `insert_chunks` is now transactional: every
        # row commits or none do. The fake mirrors that contract.
        return len(chunks)

    async def set_source_chunk_count(self, source_id: UUID, count: int) -> None:
        pass

    async def add_cost(self, session_id: UUID, kind: str, amount_usd: float) -> None:
        pass

    async def insert_chunks_write_audit(self, **kwargs: Any) -> None:
        self.audit_rows.append(kwargs)


def _candidate(url: str = "https://example.com/post") -> SourceCandidate:
    return SourceCandidate(url=url, type="web", score=0.5)


async def _fake_embed(texts: list[str], **_: Any) -> tuple[list[list[float]], int]:
    return [[0.0] * 1024 for _ in texts], 0


async def _fake_web(url: str, **_: Any) -> tuple[str, float]:
    return "article body " * 200, 0.0


@pytest.mark.asyncio
async def test_audit_emitted_on_clean_success() -> None:
    store = _AuditingFakeStore()
    sid = uuid4()
    with (
        patch.object(pipeline.web_extractor, "extract", side_effect=_fake_web),
        patch.object(pipeline, "embed_texts", side_effect=_fake_embed),
    ):
        await pipeline.ingest(sid, [_candidate()], store)  # type: ignore[arg-type]

    assert len(store.audit_rows) == 1
    row = store.audit_rows[0]
    assert row["error_kind"] == "none"
    assert row["succeeded"] == row["batch_size"]
    assert row["failed"] == 0


@pytest.mark.asyncio
async def test_audit_partial_batch_bucket_unreachable_post_s16_ingest_02() -> None:
    """S16-INGEST-02 tombstone test. With transactional `insert_chunks`,
    a no-exception short-write outcome is unreachable — the bucket itself
    was dropped from `ErrorKind`. This test pins that contract: a clean
    success run never produces a `partial_batch` audit row.
    """
    from gecko_core.ingestion.audit import ERROR_KINDS

    assert "partial_batch" not in ERROR_KINDS
    store = _AuditingFakeStore()
    sid = uuid4()
    with (
        patch.object(pipeline.web_extractor, "extract", side_effect=_fake_web),
        patch.object(pipeline, "embed_texts", side_effect=_fake_embed),
    ):
        await pipeline.ingest(sid, [_candidate()], store)  # type: ignore[arg-type]
    assert all(r["error_kind"] != "partial_batch" for r in store.audit_rows)


@pytest.mark.asyncio
async def test_audit_classifies_supabase_5xx_on_upsert_failure() -> None:
    class _SbExc(Exception):
        def __init__(self) -> None:
            super().__init__("upstream gateway")
            self.status_code = 503

    store = _AuditingFakeStore(raise_exc=_SbExc())
    sid = uuid4()
    with (
        patch.object(pipeline.web_extractor, "extract", side_effect=_fake_web),
        patch.object(pipeline, "embed_texts", side_effect=_fake_embed),
    ):
        await pipeline.ingest(sid, [_candidate()], store)  # type: ignore[arg-type]

    assert len(store.audit_rows) == 1
    assert store.audit_rows[0]["error_kind"] == "supabase_5xx"


@pytest.mark.asyncio
async def test_audit_skipped_paths_do_not_emit() -> None:
    """Duplicate / no-content / empty-after-chunk cases never reach the
    chunk-write path; they must not pollute the audit table."""
    store = _AuditingFakeStore()
    sid = uuid4()

    async def _no_text(_url: str, **_: Any) -> tuple[str | None, float]:
        return None, 0.0

    with patch.object(pipeline.web_extractor, "extract", side_effect=_no_text):
        await pipeline.ingest(sid, [_candidate()], store)  # type: ignore[arg-type]

    assert store.audit_rows == []
