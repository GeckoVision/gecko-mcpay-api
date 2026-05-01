"""Tiny MongoDB Atlas cache helper.

Used by external `Source` implementations (HN, Reddit, ...) to avoid
hammering public APIs on every research run. Lazy-connects on first use
and reuses one `AsyncIOMotorClient` for the process lifetime.

Design notes:
- If `MONGODB_URI` is unset we return a no-op (`get_cached` -> None,
  `set_cached` -> noop). Callers therefore don't need to branch.
- TTL is enforced server-side via a TTL index on `expires_at`. We also
  double-check `expires_at` on read so freshly-written documents that
  the TTL monitor hasn't reaped yet still expire correctly.
- Cache values are JSON-serializable dicts; we store under `value`.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

try:
    from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
except ImportError:  # pragma: no cover - motor is in deps; guard for stripped envs
    AsyncIOMotorClient = None  # type: ignore[assignment,misc]
    AsyncIOMotorCollection = Any  # type: ignore[assignment,misc]


def _mongo_uri() -> str | None:
    # Read env directly so we don't force a settings import on cold paths.
    uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI")
    if not uri or uri == "__unset__":
        # `__unset__` is the SSM sentinel used by infra/push-ssm-params.sh
        # so ECS task defs can resolve `secrets:` ValueFrom before Mongo is
        # wired up. Treat it as truly unset.
        return None
    return uri


def is_mongo_configured() -> bool:
    return _mongo_uri() is not None and AsyncIOMotorClient is not None


@lru_cache(maxsize=1)
def _client() -> AsyncIOMotorClient | None:  # type: ignore[type-arg]
    uri = _mongo_uri()
    if not uri or AsyncIOMotorClient is None:
        return None
    return AsyncIOMotorClient(uri)


def _db_name() -> str:
    return os.environ.get("MONGODB_DB", "gecko_cache")


async def _collection(name: str) -> AsyncIOMotorCollection | None:  # type: ignore[type-arg]
    client = _client()
    if client is None:
        return None
    coll = client[_db_name()][name]
    # Idempotent: Mongo no-ops if the index already exists with same spec.
    try:
        await coll.create_index("expires_at", expireAfterSeconds=0)
        await coll.create_index("key", unique=True)
    except Exception:
        # Index creation is best-effort; cache reads/writes still work.
        pass
    return coll


def cache_key(*parts: str) -> str:
    """Stable sha256 over arbitrary parts. Caller defines part ordering."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


async def get_cached(collection: str, key: str) -> dict[str, Any] | None:
    """Return cached value or None on miss / unconfigured / expired."""
    coll = await _collection(collection)
    if coll is None:
        return None
    doc = await coll.find_one({"key": key})
    if doc is None:
        return None
    expires_at = doc.get("expires_at")
    if isinstance(expires_at, datetime):
        # Mongo strips tzinfo on read; treat naive as UTC.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            return None
    value = doc.get("value")
    return value if isinstance(value, dict) else None


async def set_cached(collection: str, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    """Upsert `value` under `key` with TTL. No-op if Mongo unconfigured."""
    coll = await _collection(collection)
    if coll is None:
        return
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    await coll.update_one(
        {"key": key},
        {"$set": {"key": key, "value": value, "expires_at": expires_at}},
        upsert=True,
    )


__all__ = ["cache_key", "get_cached", "is_mongo_configured", "set_cached"]
