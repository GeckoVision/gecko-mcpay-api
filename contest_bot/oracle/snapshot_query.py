"""Read helpers for the `oracle_snapshots` collection.

Mirrors contest_bot.decision_store.news_query exactly — recent /
by_symbol / by_source. The oracle_voice (Sprint 29) reads through
latest_per_source() to assemble its three-way agreement check.

Best-effort: returns [] on Mongo unavailable / connection error /
collection empty. Never raises.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("contest_bot.oracle.snapshot_query")

DEFAULT_DB = "gecko_cache"
DEFAULT_COLLECTION = "oracle_snapshots"


def _collection_from_env() -> Any | None:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None
    try:
        from pymongo import MongoClient

        db = MongoClient(uri, serverSelectionTimeoutMS=3000)[
            os.environ.get("MONGODB_DB", DEFAULT_DB)
        ]
        return db[os.environ.get("MONGODB_ORACLE_COLL", DEFAULT_COLLECTION)]
    except Exception as exc:
        logger.warning("oracle_query.connect_failed err=%s", exc)
        return None


def _trim(d: dict) -> dict:
    """Strip the embedding (large) for hot-path reads; keep summary."""
    if not isinstance(d, dict):
        return d
    out = dict(d)
    out.pop("embedding", None)
    out.pop("_id", None)
    return out


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return None


def recent(
    limit: int = 20,
    *,
    collection: Any | None = None,
) -> list[dict]:
    """Most recent snapshots across ALL symbols + sources."""
    coll = collection if collection is not None else _collection_from_env()
    if coll is None:
        return []
    try:
        cursor = coll.find({}).sort("ts", -1).limit(int(limit))
        return [_trim(d) for d in cursor]
    except Exception as exc:
        logger.warning("oracle_query.recent_failed err=%s", exc)
        return []


def by_symbol(
    symbol: str,
    *,
    source: str | None = None,
    since: Any = None,
    until: Any = None,
    limit: int = 100,
    collection: Any | None = None,
) -> list[dict]:
    """Snapshots for `symbol` (and optionally `source`), bounded by
    [since, until] on `ts`. Newest first."""
    coll = collection if collection is not None else _collection_from_env()
    if coll is None:
        return []
    sym = symbol.upper().strip()
    flt: dict[str, Any] = {"symbol": sym}
    if source:
        flt["source"] = source.lower().strip()
    since_iso = _to_iso(since)
    until_iso = _to_iso(until)
    if since_iso or until_iso:
        window: dict[str, Any] = {}
        if since_iso:
            window["$gte"] = since_iso
        if until_iso:
            window["$lte"] = until_iso
        flt["ts"] = window
    try:
        cursor = coll.find(flt).sort("ts", -1).limit(int(limit))
        return [_trim(d) for d in cursor]
    except Exception as exc:
        logger.warning("oracle_query.by_symbol_failed sym=%s err=%s", sym, exc)
        return []


def latest_per_source(
    symbol: str,
    *,
    collection: Any | None = None,
) -> dict[str, dict]:
    """Return {source: latest_snapshot_doc} for the given symbol.

    The oracle_voice's load-bearing query: "what does each source say
    right now?" Returns at most one row per source. Empty dict if no
    snapshots exist for this symbol.
    """
    coll = collection if collection is not None else _collection_from_env()
    if coll is None:
        return {}
    sym = symbol.upper().strip()
    out: dict[str, dict] = {}
    try:
        # Mongo aggregation: group by source, take the newest ts per group.
        # Simpler approach for v1: query recent rows + dedupe in Python
        # (cheaper than aggregation pipeline for typical small N).
        cursor = coll.find({"symbol": sym}).sort("ts", -1).limit(50)
        for d in cursor:
            src = d.get("source")
            if src and src not in out:
                out[src] = _trim(d)
        return out
    except Exception as exc:
        logger.warning("oracle_query.latest_per_source_failed sym=%s err=%s", sym, exc)
        return {}


def by_source(
    source: str,
    *,
    limit: int = 100,
    collection: Any | None = None,
) -> list[dict]:
    """Most recent snapshots from one source. Useful for source-health
    diagnostics ("is Pyth still publishing?")."""
    coll = collection if collection is not None else _collection_from_env()
    if coll is None:
        return []
    src = source.lower().strip()
    try:
        cursor = coll.find({"source": src}).sort("ts", -1).limit(int(limit))
        return [_trim(d) for d in cursor]
    except Exception as exc:
        logger.warning("oracle_query.by_source_failed src=%s err=%s", src, exc)
        return []


__all__ = ["recent", "by_symbol", "by_source", "latest_per_source"]
