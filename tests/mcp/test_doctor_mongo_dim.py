"""S19-MONGO-INDEX-DIM-CHECK-01 — verify the doctor's Atlas vector-index dim check.

Stubs `pymongo.MongoClient` so we can hand back canned `list_search_indexes()`
shapes without standing up a real Atlas cluster. Pattern mirrors the existing
sys.modules injection in `tests/ingestion/test_voyage_embedder_contract.py`.
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
    """Inject a fake `pymongo` module so doctor's `from pymongo import MongoClient` works."""
    fake_mod: Any = type(sys)("pymongo")
    fake_mod.MongoClient = _FakeMongoClient
    monkeypatch.setitem(sys.modules, "pymongo", fake_mod)
    yield _FakeMongoClient


def _idx_def(name: str, *, dim: int | None, similarity: str = "cosine") -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    if dim is not None:
        fields.append(
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": dim,
                "similarity": similarity,
            }
        )
    return {"name": name, "latestDefinition": {"fields": fields}}


@pytest.mark.parametrize("dim", [1024])
def test_dim_check_passes_when_index_matches_expected(
    fake_pymongo: type[_FakeMongoClient], dim: int
) -> None:
    fake_pymongo.last_search_indexes = [
        _idx_def("chunks_vector", dim=dim),
        {"name": "chunks_text", "latestDefinition": {"fields": []}},
    ]
    from gecko_mcp.doctor import check_chunk_store

    env = {"GECKO_CHUNK_STORE": "mongo", "MONGODB_URI": "mongodb://stub"}
    rows = {r.name: r for r in check_chunk_store(environ=env)}

    dim_row = rows["chunk_store:mongo:index:chunks_vector:dim"]
    assert dim_row.ok is True
    assert "dim=1024 ok" in dim_row.detail
    assert "similarity=cosine" in dim_row.detail


def test_dim_check_fails_when_index_is_1536(fake_pymongo: type[_FakeMongoClient]) -> None:
    """The exact footgun S18 might have left: index built at OpenAI's 1536."""
    fake_pymongo.last_search_indexes = [
        _idx_def("chunks_vector", dim=1536),
        {"name": "chunks_text", "latestDefinition": {"fields": []}},
    ]
    from gecko_mcp.doctor import check_chunk_store

    env = {"GECKO_CHUNK_STORE": "mongo", "MONGODB_URI": "mongodb://stub"}
    rows = {r.name: r for r in check_chunk_store(environ=env)}

    dim_row = rows["chunk_store:mongo:index:chunks_vector:dim"]
    assert dim_row.ok is False
    assert "dim=1536" in dim_row.detail
    assert "expected=1024" in dim_row.detail
    assert "Voyage" in dim_row.detail


def test_dim_check_handles_definition_legacy_key(
    fake_pymongo: type[_FakeMongoClient],
) -> None:
    """Older Atlas versions return ``definition`` instead of ``latestDefinition``."""
    fake_pymongo.last_search_indexes = [
        {
            "name": "chunks_vector",
            "definition": {
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": 1024,
                        "similarity": "cosine",
                    }
                ]
            },
        },
        {"name": "chunks_text", "latestDefinition": {"fields": []}},
    ]
    from gecko_mcp.doctor import check_chunk_store

    env = {"GECKO_CHUNK_STORE": "mongo", "MONGODB_URI": "mongodb://stub"}
    rows = {r.name: r for r in check_chunk_store(environ=env)}
    assert rows["chunk_store:mongo:index:chunks_vector:dim"].ok is True


def test_dim_check_reports_parse_failure_when_no_vector_field(
    fake_pymongo: type[_FakeMongoClient],
) -> None:
    fake_pymongo.last_search_indexes = [
        {"name": "chunks_vector", "latestDefinition": {"fields": []}},
        {"name": "chunks_text", "latestDefinition": {"fields": []}},
    ]
    from gecko_mcp.doctor import check_chunk_store

    env = {"GECKO_CHUNK_STORE": "mongo", "MONGODB_URI": "mongodb://stub"}
    rows = {r.name: r for r in check_chunk_store(environ=env)}

    dim_row = rows["chunk_store:mongo:index:chunks_vector:dim"]
    assert dim_row.ok is False
    assert "could not parse" in dim_row.detail


def test_dim_check_skipped_when_chunks_vector_index_missing(
    fake_pymongo: type[_FakeMongoClient],
) -> None:
    """If the vector index doesn't exist at all, the missing-index row fires
    instead of the dim-mismatch row — no double-failure on the same root cause."""
    fake_pymongo.last_search_indexes = [
        {"name": "chunks_text", "latestDefinition": {"fields": []}},
    ]
    from gecko_mcp.doctor import check_chunk_store

    env = {"GECKO_CHUNK_STORE": "mongo", "MONGODB_URI": "mongodb://stub"}
    rows = {r.name: r for r in check_chunk_store(environ=env)}

    assert rows["chunk_store:mongo:index:chunks_vector"].ok is False
    assert "chunk_store:mongo:index:chunks_vector:dim" not in rows


def test_extract_vector_index_dim_helper() -> None:
    from gecko_mcp.doctor import _extract_vector_index_dim

    dim, sim = _extract_vector_index_dim(_idx_def("chunks_vector", dim=1024))
    assert dim == 1024
    assert sim == "cosine"

    dim, sim = _extract_vector_index_dim({"name": "x", "latestDefinition": {"fields": []}})
    assert dim is None
    assert sim is None


def test_constant_is_exported_from_mongo_chunks() -> None:
    """Doctor's source of truth must be the chunk validator's source of truth."""
    from gecko_core.db.mongo_chunks import EMBED_DIM, MONGO_VECTOR_DIM_EXPECTED

    assert MONGO_VECTOR_DIM_EXPECTED == 1024
    assert EMBED_DIM == MONGO_VECTOR_DIM_EXPECTED
