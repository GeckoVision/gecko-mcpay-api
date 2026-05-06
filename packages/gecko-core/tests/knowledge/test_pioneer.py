"""S20-A7 — Pioneer-cell signal tests.

Stub-collection only (no live Atlas). The collection seam is the
``collection`` kwarg on each pioneer fn — pass a fake that records
calls and exposes a synthetic count. The fake also gates the schema
the production code will see (``count_documents`` filters by
``vertical``, ``category``, and ``metadata.deprecated``).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from gecko_core.knowledge import pioneer


class _FakeCellCollection:
    """Records ``count_documents`` calls and returns a fixed count."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.calls: list[dict[str, Any]] = []

    async def count_documents(self, query: dict[str, Any]) -> int:
        self.calls.append(dict(query))
        return self._count


# ---------------------------------------------------------------------------
# count_cell_chunks
# ---------------------------------------------------------------------------


class TestCountCellChunks:
    @pytest.mark.asyncio
    async def test_returns_stub_count(self) -> None:
        coll = _FakeCellCollection(count=3)
        n = await pioneer.count_cell_chunks("neobank", "business_financial", collection=coll)
        assert n == 3
        assert coll.calls[0]["vertical"] == "neobank"
        assert coll.calls[0]["category"] == "business_financial"
        assert coll.calls[0]["metadata.deprecated"] == {"$ne": True}


# ---------------------------------------------------------------------------
# is_pioneer_cell
# ---------------------------------------------------------------------------


class TestIsPioneerCell:
    @pytest.mark.asyncio
    async def test_true_when_count_below_threshold(self) -> None:
        coll = _FakeCellCollection(count=4)  # boundary: 4 < 5 → pioneer
        assert (
            await pioneer.is_pioneer_cell("neobank", "business_financial", collection=coll) is True
        )

    @pytest.mark.asyncio
    async def test_false_when_count_at_threshold(self) -> None:
        coll = _FakeCellCollection(count=5)  # boundary: 5 < 5 is False
        assert (
            await pioneer.is_pioneer_cell("neobank", "business_financial", collection=coll) is False
        )

    @pytest.mark.asyncio
    async def test_false_when_count_above_threshold(self) -> None:
        coll = _FakeCellCollection(count=99)
        assert await pioneer.is_pioneer_cell("ai_startup", "ai_ml", collection=coll) is False

    @pytest.mark.asyncio
    async def test_threshold_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GECKO_PIONEER_THRESHOLD", "10")
        coll = _FakeCellCollection(count=7)  # 7 < 10 → pioneer with override
        assert (
            await pioneer.is_pioneer_cell("neobank", "business_financial", collection=coll) is True
        )
        # And dense relative to override:
        coll2 = _FakeCellCollection(count=12)
        assert (
            await pioneer.is_pioneer_cell("neobank", "business_financial", collection=coll2)
            is False
        )

    @pytest.mark.asyncio
    async def test_emits_check_log(self, caplog: pytest.LogCaptureFixture) -> None:
        coll = _FakeCellCollection(count=2)
        with caplog.at_level(logging.INFO, logger="gecko_core.knowledge.pioneer"):
            await pioneer.is_pioneer_cell("neobank", "business_financial", collection=coll)
        recs = [r for r in caplog.records if r.message == "knowledge.pioneer.check"]
        assert recs, "expected a knowledge.pioneer.check log record"
        rec = recs[-1]
        assert rec.vertical == "neobank"  # type: ignore[attr-defined]
        assert rec.category == "business_financial"  # type: ignore[attr-defined]
        assert rec.count == 2  # type: ignore[attr-defined]
        assert rec.threshold == 5  # type: ignore[attr-defined]
        assert rec.is_pioneer is True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# mark_pioneer_chunks
# ---------------------------------------------------------------------------


class TestMarkPioneerChunks:
    @pytest.mark.asyncio
    async def test_flips_pioneer_true_when_sparse(self) -> None:
        coll = _FakeCellCollection(count=0)
        chunks: list[dict[str, Any]] = [
            {"chunk_index": 0, "metadata": {"pioneer": False}},
            {"chunk_index": 1, "metadata": {"pioneer": False}},
            {"chunk_index": 2, "metadata": {"pioneer": False}},
        ]
        out = await pioneer.mark_pioneer_chunks(
            chunks, "neobank", "business_financial", collection=coll
        )
        assert all(c["metadata"]["pioneer"] is True for c in out)

    @pytest.mark.asyncio
    async def test_leaves_pioneer_false_when_dense(self) -> None:
        coll = _FakeCellCollection(count=10)
        chunks: list[dict[str, Any]] = [
            {"chunk_index": 0, "metadata": {"pioneer": False}},
            {"chunk_index": 1, "metadata": {"pioneer": False}},
        ]
        out = await pioneer.mark_pioneer_chunks(
            chunks, "neobank", "business_financial", collection=coll
        )
        assert all(c["metadata"]["pioneer"] is False for c in out)

    @pytest.mark.asyncio
    async def test_count_check_runs_once_per_call(self) -> None:
        coll = _FakeCellCollection(count=1)
        chunks: list[dict[str, Any]] = [
            {"chunk_index": i, "metadata": {"pioneer": False}} for i in range(20)
        ]
        await pioneer.mark_pioneer_chunks(chunks, "neobank", "business_financial", collection=coll)
        # 20 chunks but only ONE count_documents call.
        assert len(coll.calls) == 1

    @pytest.mark.asyncio
    async def test_empty_list_short_circuits(self) -> None:
        coll = _FakeCellCollection(count=0)
        out = await pioneer.mark_pioneer_chunks(
            [], "neobank", "business_financial", collection=coll
        )
        assert out == []
        # No DB call when there's nothing to mark.
        assert coll.calls == []


# ---------------------------------------------------------------------------
# Constants surface
# ---------------------------------------------------------------------------


def test_public_exports() -> None:
    assert pioneer.PIONEER_THRESHOLD == 5
    assert "PIONEER_THRESHOLD" in pioneer.__all__
    assert "count_cell_chunks" in pioneer.__all__
    assert "is_pioneer_cell" in pioneer.__all__
    assert "mark_pioneer_chunks" in pioneer.__all__
