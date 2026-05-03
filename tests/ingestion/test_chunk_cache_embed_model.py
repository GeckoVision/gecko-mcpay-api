"""S16-INGEST-03 (Mongo rewrite) — chunk_embedding_cache model isolation.

Same three scenarios as the original Supabase-path test, now exercised
against put_chunk_cache_mongo / get_chunk_cache_mongo directly.

The fake async cursor mirrors Motor's find() interface so the real
function body can iterate with ``async for`` without needing a real Atlas
connection.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from gecko_core.db.mongo_chunks import EMBED_DIM, get_chunk_cache_mongo, put_chunk_cache_mongo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AsyncCursor:
    """Minimal Motor-compatible async iterable cursor."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = list(docs)

    def __aiter__(self) -> _AsyncCursor:
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


def _embed(value: float = 0.0) -> list[float]:
    return [value] * EMBED_DIM


# ---------------------------------------------------------------------------
# test_put_and_get_under_default_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_and_get_under_default_model() -> None:
    """Write one cache row, read it back — embedding returned at expected dim."""
    stored: list[dict[str, Any]] = []

    # --- put side ---
    put_coll = AsyncMock()
    put_coll.bulk_write = AsyncMock()

    with patch("gecko_core.db.mongo_chunks.cache_collection", return_value=put_coll):
        await put_chunk_cache_mongo(
            "h1",
            [(0, "hello", _embed(0.1))],
            embed_model="text-embedding-3-small",
        )

    assert put_coll.bulk_write.called
    ops = put_coll.bulk_write.call_args[0][0]
    assert len(ops) == 1
    doc = ops[0]._doc["$setOnInsert"]
    stored.append(
        {
            "url_hash": doc["url_hash"],
            "chunk_index": doc["chunk_index"],
            "embedding": doc["embedding"],
            "embed_model": doc["embed_model"],
        }
    )

    # --- get side ---
    get_coll = MagicMock()
    get_coll.find = MagicMock(return_value=_AsyncCursor(list(stored)))
    get_coll.delete_many = AsyncMock()

    with patch("gecko_core.db.mongo_chunks.cache_collection", return_value=get_coll):
        out = await get_chunk_cache_mongo("h1", [0], embed_model="text-embedding-3-small")

    assert 0 in out
    assert len(out[0]) == EMBED_DIM


# ---------------------------------------------------------------------------
# test_model_change_isolates_cache_lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_change_isolates_cache_lookup() -> None:
    """Row stored under model-A is a miss for model-B; after caching under
    model-B both rows coexist."""
    stored: list[dict[str, Any]] = []

    async def _do_put(model: str) -> None:
        coll = AsyncMock()
        coll.bulk_write = AsyncMock()
        with patch("gecko_core.db.mongo_chunks.cache_collection", return_value=coll):
            await put_chunk_cache_mongo(
                "h1",
                [(0, "hello", _embed())],
                embed_model=model,
            )
        ops = coll.bulk_write.call_args[0][0]
        doc = ops[0]._doc["$setOnInsert"]
        stored.append(
            {
                "url_hash": doc["url_hash"],
                "chunk_index": doc["chunk_index"],
                "embedding": doc["embedding"],
                "embed_model": doc["embed_model"],
            }
        )

    async def _do_get(model: str) -> dict[int, list[float]]:
        # Only return rows matching the requested model (mimics Mongo query filter).
        matching = [r for r in stored if r.get("embed_model") == model]
        coll = MagicMock()
        coll.find = MagicMock(return_value=_AsyncCursor(list(matching)))
        coll.delete_many = AsyncMock()
        with patch("gecko_core.db.mongo_chunks.cache_collection", return_value=coll):
            return await get_chunk_cache_mongo("h1", [0], embed_model=model)

    # Step 1 — cache under small model
    await _do_put("text-embedding-3-small")

    # Step 2 — lookup under large model: miss
    out_large = await _do_get("text-embedding-3-large")
    assert out_large == {}

    # Step 3 — cache under large model, then lookup: hit
    await _do_put("text-embedding-3-large")
    out_large2 = await _do_get("text-embedding-3-large")
    assert 0 in out_large2

    # Two distinct PK rows coexist
    keys = {(r["url_hash"], r["chunk_index"], r["embed_model"]) for r in stored}
    assert keys == {
        ("h1", 0, "text-embedding-3-small"),
        ("h1", 0, "text-embedding-3-large"),
    }


# ---------------------------------------------------------------------------
# test_no_embed_model_filter_returns_legacy_rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_embed_model_filter_returns_legacy_rows() -> None:
    """get_chunk_cache_mongo with embed_model=None returns rows regardless
    of their stored model (legacy / backwards-compat path)."""
    # Pre-seed a row tagged with a model string
    seeded = [
        {
            "url_hash": "h1",
            "chunk_index": 0,
            "embedding": _embed(),
            "embed_model": "text-embedding-3-small",
        }
    ]

    coll = MagicMock()
    coll.find = MagicMock(return_value=_AsyncCursor(list(seeded)))
    coll.delete_many = AsyncMock()

    with patch("gecko_core.db.mongo_chunks.cache_collection", return_value=coll):
        out = await get_chunk_cache_mongo("h1", [0])  # no embed_model filter

    assert 0 in out
