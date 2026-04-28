"""Tests for `gecko_core.cache.mongo`.

We mock the `motor.motor_asyncio.AsyncIOMotorClient` import target inside the
module so no real Mongo URI is touched. These tests pin the no-op fallback
path and the TTL-index creation contract — the behavior other sources rely on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from gecko_core.cache import mongo as mongo_mod


class _FakeCollection:
    """Captures index creations and stores upserts in-memory."""

    def __init__(self) -> None:
        self.indexes: list[tuple[str, dict[str, Any]]] = []
        self.docs: dict[str, dict[str, Any]] = {}

    async def create_index(self, field: str, **kwargs: Any) -> str:
        self.indexes.append((field, dict(kwargs)))
        return f"{field}_1"

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return self.docs.get(query["key"])

    async def update_one(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> None:
        key = query["key"]
        self.docs[key] = dict(update["$set"])


class _FakeDB:
    def __init__(self, coll: _FakeCollection) -> None:
        self._coll = coll

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._coll


class _FakeClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._coll = _FakeCollection()
        self._db = _FakeDB(self._coll)

    def __getitem__(self, name: str) -> _FakeDB:
        return self._db


@pytest.fixture
def mongo_configured(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    """Patch the cache module to use a fake motor client."""
    monkeypatch.setenv("MONGODB_URI", "mongodb://fake-host:27017")
    monkeypatch.setenv("MONGODB_DB", "gecko_test")
    monkeypatch.setattr(mongo_mod, "AsyncIOMotorClient", _FakeClient)
    # Bust the lru_cache so each test gets a fresh client instance.
    mongo_mod._client.cache_clear()
    return mongo_mod._client()  # type: ignore[return-value]


@pytest.fixture
def mongo_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    mongo_mod._client.cache_clear()


# ---------------------------------------------------------------------------
# No-op when MONGODB_URI is missing
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("mongo_unconfigured")
async def test_get_cached_returns_none_when_unconfigured() -> None:
    assert await mongo_mod.get_cached("twitsh_cache", "any-key") is None


@pytest.mark.usefixtures("mongo_unconfigured")
async def test_set_cached_is_silent_no_op_when_unconfigured() -> None:
    # Must not raise.
    await mongo_mod.set_cached("twitsh_cache", "any-key", {"a": 1}, ttl_seconds=60)


@pytest.mark.usefixtures("mongo_unconfigured")
def test_is_mongo_configured_false_without_uri() -> None:
    assert mongo_mod.is_mongo_configured() is False


# ---------------------------------------------------------------------------
# TTL index is created on first write
# ---------------------------------------------------------------------------


async def test_set_cached_creates_ttl_index(mongo_configured: _FakeClient) -> None:
    await mongo_mod.set_cached("twitsh_cache", "k1", {"hello": "world"}, ttl_seconds=3600)
    coll = mongo_configured["gecko_test"]["twitsh_cache"]
    field_names = {f for f, _ in coll.indexes}
    assert "expires_at" in field_names, "TTL index on expires_at not created"
    # And the TTL spec uses expireAfterSeconds=0 (TTL governed by the field's value).
    expires_specs = [opts for f, opts in coll.indexes if f == "expires_at"]
    assert any(s.get("expireAfterSeconds") == 0 for s in expires_specs)
    # Unique key index is also created so cache lookups stay O(1).
    assert "key" in field_names


async def test_set_then_get_roundtrips(mongo_configured: _FakeClient) -> None:
    await mongo_mod.set_cached("twitsh_cache", "k1", {"hello": "world"}, ttl_seconds=3600)
    got = await mongo_mod.get_cached("twitsh_cache", "k1")
    assert got == {"hello": "world"}


async def test_get_returns_none_for_expired_doc(mongo_configured: _FakeClient) -> None:
    """Even if Mongo's TTL monitor hasn't reaped, we double-check on read."""
    coll = mongo_configured["gecko_test"]["twitsh_cache"]
    coll.docs["stale"] = {
        "key": "stale",
        "value": {"old": True},
        "expires_at": datetime.now(UTC) - timedelta(seconds=1),
    }
    assert await mongo_mod.get_cached("twitsh_cache", "stale") is None


async def test_get_returns_none_on_miss(mongo_configured: _FakeClient) -> None:
    assert await mongo_mod.get_cached("twitsh_cache", "never-set") is None


def test_cache_key_is_stable_and_deterministic() -> None:
    a = mongo_mod.cache_key("twit_sh:", "idea-1", "|", "crypto")
    b = mongo_mod.cache_key("twit_sh:", "idea-1", "|", "crypto")
    c = mongo_mod.cache_key("twit_sh:", "idea-2", "|", "crypto")
    assert a == b
    assert a != c
    # sha256 hex => 64 chars
    assert len(a) == 64
