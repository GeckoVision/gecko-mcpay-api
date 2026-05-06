"""S20-RAG-02 — verify the doctor probe for filterable index fields.

Uses the same fake-pymongo pattern as ``test_doctor_mongo_dim.py``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest


class _FakeCollection:
    def __init__(self, search_indexes: list[dict[str, Any]]) -> None:
        self._idx = search_indexes

    def list_search_indexes(self) -> list[dict[str, Any]]:
        return list(self._idx)


class _FakeAdmin:
    def command(self, _name: str) -> dict[str, int]:
        return {"ok": 1}


class _FakeDB:
    def __init__(self, search_indexes: list[dict[str, Any]]) -> None:
        self._coll = _FakeCollection(search_indexes)

    def __getitem__(self, _name: str) -> _FakeCollection:
        return self._coll


class _FakeMongoClient:
    last_search_indexes: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.admin = _FakeAdmin()
        self._db = _FakeDB(_FakeMongoClient.last_search_indexes)

    def __getitem__(self, _name: str) -> _FakeDB:
        return self._db


@pytest.fixture
def fake_pymongo(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_FakeMongoClient]]:
    fake_mod: Any = type(sys)("pymongo")
    fake_mod.MongoClient = _FakeMongoClient
    monkeypatch.setitem(sys.modules, "pymongo", fake_mod)
    yield _FakeMongoClient


def _idx(name: str, *, dim: int = 1024, filter_paths: list[str] | None = None) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {
            "type": "vector",
            "path": "embedding",
            "numDimensions": dim,
            "similarity": "cosine",
        }
    ]
    for p in filter_paths or []:
        fields.append({"type": "filter", "path": p})
    return {"name": name, "latestDefinition": {"fields": fields}}


def test_filters_check_passes_when_all_present(
    fake_pymongo: type[_FakeMongoClient],
) -> None:
    from gecko_core.db.mongo import CHUNKS_VECTOR_FILTER_FIELDS

    fake_pymongo.last_search_indexes = [
        _idx("chunks_vector", filter_paths=list(CHUNKS_VECTOR_FILTER_FIELDS)),
        {"name": "chunks_text", "latestDefinition": {"fields": []}},
    ]
    from gecko_mcp.doctor import check_chunk_store

    env = {"GECKO_CHUNK_STORE": "mongo", "MONGODB_URI": "mongodb://stub"}
    rows = {r.name: r for r in check_chunk_store(environ=env)}
    row = rows["chunk_store:mongo:index:chunks_vector:filters"]
    assert row.ok is True
    assert "all filterable" in row.detail
    for f in CHUNKS_VECTOR_FILTER_FIELDS:
        assert f in row.detail


def test_filters_check_fails_when_one_missing(
    fake_pymongo: type[_FakeMongoClient],
) -> None:
    from gecko_core.db.mongo import CHUNKS_VECTOR_FILTER_FIELDS

    paths = [p for p in CHUNKS_VECTOR_FILTER_FIELDS if p != "source"]
    fake_pymongo.last_search_indexes = [
        _idx("chunks_vector", filter_paths=paths),
        {"name": "chunks_text", "latestDefinition": {"fields": []}},
    ]
    from gecko_mcp.doctor import check_chunk_store

    env = {"GECKO_CHUNK_STORE": "mongo", "MONGODB_URI": "mongodb://stub"}
    rows = {r.name: r for r in check_chunk_store(environ=env)}
    row = rows["chunk_store:mongo:index:chunks_vector:filters"]
    assert row.ok is False
    assert "missing filter" in row.detail
    assert "source" in row.detail


def test_filters_check_fails_when_no_filter_fields_at_all(
    fake_pymongo: type[_FakeMongoClient],
) -> None:
    fake_pymongo.last_search_indexes = [
        _idx("chunks_vector", filter_paths=[]),
        {"name": "chunks_text", "latestDefinition": {"fields": []}},
    ]
    from gecko_mcp.doctor import check_chunk_store

    env = {"GECKO_CHUNK_STORE": "mongo", "MONGODB_URI": "mongodb://stub"}
    rows = {r.name: r for r in check_chunk_store(environ=env)}
    row = rows["chunk_store:mongo:index:chunks_vector:filters"]
    assert row.ok is False
    assert "no filter fields declared" in row.detail
    assert "s20_rag02_filterable_index.py" in row.detail


def test_extract_vector_index_filters_helper() -> None:
    from gecko_mcp.doctor import _extract_vector_index_filters

    paths = _extract_vector_index_filters(
        _idx("chunks_vector", filter_paths=["vertical", "category"])
    )
    assert paths == {"vertical", "category"}

    empty = _extract_vector_index_filters({"name": "x", "latestDefinition": {"fields": []}})
    assert empty == set()
