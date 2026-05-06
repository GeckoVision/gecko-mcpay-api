"""S20-A6 / S20-A-USAGE-COUNT-01 — tests for ``bump_usage_counts``.

Covers the contract:
- empty input → no DB call
- valid ObjectId list → single update_many with $in filter + $inc
- invalid ObjectId in list → skipped (logged WARN), valid ones still bumped
- Mongo raises → returns 0, WARN logged, NEVER re-raises (best-effort)
- all-invalid list → returns 0, no DB call
- structured log assertions on success + failure paths
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId
from gecko_core.db import mongo_chunks


def _make_coll(modified_count: int = 0, raise_exc: Exception | None = None) -> MagicMock:
    coll = MagicMock()
    if raise_exc is not None:
        coll.update_many = AsyncMock(side_effect=raise_exc)
    else:
        result = MagicMock()
        result.modified_count = modified_count
        coll.update_many = AsyncMock(return_value=result)
    return coll


@pytest.fixture
def patch_chunks_collection(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Yield a dict with a swappable ``coll``; tests mutate ``state['coll']``."""
    state: dict[str, Any] = {"coll": None}

    def _factory() -> Any:
        return state["coll"]

    monkeypatch.setattr(mongo_chunks, "chunks_collection", _factory)
    return state


async def test_empty_list_returns_zero_no_db_call(
    patch_chunks_collection: dict[str, Any],
) -> None:
    coll = _make_coll(modified_count=0)
    patch_chunks_collection["coll"] = coll

    n = await mongo_chunks.bump_usage_counts([])

    assert n == 0
    coll.update_many.assert_not_called()


async def test_three_valid_ids_calls_update_many_with_correct_filter(
    patch_chunks_collection: dict[str, Any],
) -> None:
    ids = [str(ObjectId()) for _ in range(3)]
    coll = _make_coll(modified_count=3)
    patch_chunks_collection["coll"] = coll

    n = await mongo_chunks.bump_usage_counts(ids)

    assert n == 3
    coll.update_many.assert_awaited_once()
    call = coll.update_many.await_args
    filt, update = call.args
    assert "_id" in filt
    assert "$in" in filt["_id"]
    assert len(filt["_id"]["$in"]) == 3
    assert all(isinstance(x, ObjectId) for x in filt["_id"]["$in"])
    assert update == {"$inc": {"metadata.usage_count": 1}}


async def test_invalid_object_id_skipped_valid_ones_still_bumped(
    patch_chunks_collection: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    valid = str(ObjectId())
    bad = "not-a-valid-objectid-xxxxxxxxxxxx"
    coll = _make_coll(modified_count=1)
    patch_chunks_collection["coll"] = coll

    with caplog.at_level(logging.WARNING, logger="gecko_core.db.mongo_chunks"):
        n = await mongo_chunks.bump_usage_counts([bad, valid])

    assert n == 1
    coll.update_many.assert_awaited_once()
    filt, _ = coll.update_many.await_args.args
    assert len(filt["_id"]["$in"]) == 1  # only the valid one made it through
    assert any("mongo.bump_usage.invalid_id" in rec.message for rec in caplog.records)


async def test_mongo_raises_returns_zero_and_does_not_propagate(
    patch_chunks_collection: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    coll = _make_coll(raise_exc=RuntimeError("connection reset"))
    patch_chunks_collection["coll"] = coll

    with caplog.at_level(logging.WARNING, logger="gecko_core.db.mongo_chunks"):
        n = await mongo_chunks.bump_usage_counts([str(ObjectId())])

    assert n == 0  # NEVER re-raises — best-effort side effect
    assert any("mongo.bump_usage.failed" in rec.message for rec in caplog.records)


async def test_all_invalid_ids_returns_zero_no_db_call(
    patch_chunks_collection: dict[str, Any],
) -> None:
    coll = _make_coll(modified_count=99)  # would be wrong if called
    patch_chunks_collection["coll"] = coll

    n = await mongo_chunks.bump_usage_counts(["bad-1", "still-bad-id", ""])

    assert n == 0
    coll.update_many.assert_not_called()


async def test_logging_done_event_on_success(
    patch_chunks_collection: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    ids = [str(ObjectId()), str(ObjectId())]
    coll = _make_coll(modified_count=2)
    patch_chunks_collection["coll"] = coll

    with caplog.at_level(logging.INFO, logger="gecko_core.db.mongo_chunks"):
        n = await mongo_chunks.bump_usage_counts(ids)

    assert n == 2
    done_records = [r for r in caplog.records if "mongo.bump_usage.done" in r.message]
    assert done_records, "expected mongo.bump_usage.done INFO log"
    rec = done_records[0]
    assert getattr(rec, "requested_count", None) == 2
    assert getattr(rec, "modified_count", None) == 2
    assert hasattr(rec, "ms_elapsed")
