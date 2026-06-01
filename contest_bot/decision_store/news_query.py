"""Read-side helpers over the `market_news` Mongo collection.

Three queries, scoped tight to the planned market_researcher voice +
retroactive analysis:

  recent(N)
      Last N items by published_at (then fetched_at fallback).

  by_symbol(symbol, since=None, until=None)
      All news tagged with `symbol` (multikey hit on `tickers`), inside
      an optional time window.

  by_source(source)
      All news from a given provider — operational sanity check ("did
      cryptopanic actually land anything this hour?").

All three accept an injected `collection` so tests can pass a fake without
standing up Mongo. All return Python lists/dicts (BSON-friendly).

Vector similarity is intentionally NOT in v1 — the Atlas Search vector
index `market_news_vec` is founder-gated. When that lands, add
`find_similar` here mirroring `behavior_query.find_similar`.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("decision_store.news_query")

DEFAULT_DB = "gecko_cache"
DEFAULT_COLLECTION = "market_news"


def _collection_from_env() -> Any | None:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None
    try:
        from pymongo import MongoClient

        db = MongoClient(uri, serverSelectionTimeoutMS=3000)[
            os.environ.get("MONGODB_DB", DEFAULT_DB)
        ]
        return db[os.environ.get("MONGODB_NEWS_COLL", DEFAULT_COLLECTION)]
    except Exception as exc:
        logger.warning("news_query: mongo unavailable (%s)", exc)
        return None


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return str(value)


def _trim(doc: dict) -> dict:
    """Drop the embedding field — callers don't need 1024 floats per row."""
    return {k: v for k, v in doc.items() if k != "embedding"}


def recent(
    limit: int = 50,
    *,
    collection: Any | None = None,
) -> list[dict]:
    """Most-recent N news items by `published_at` (descending).

    `fetched_at` is used as a tiebreaker when `published_at` is null
    (some sources don't expose publish time). Embedding stripped from each
    result.
    """
    coll = collection if collection is not None else _collection_from_env()
    if coll is None:
        return []
    try:
        cursor = coll.find().sort([("published_at", -1), ("fetched_at", -1)]).limit(int(limit))
        return [_trim(d) for d in cursor]
    except Exception as exc:
        logger.warning("news_query.recent: find failed (%s)", exc)
        return []


def by_symbol(
    symbol: str,
    *,
    since: Any = None,
    until: Any = None,
    limit: int = 100,
    collection: Any | None = None,
) -> list[dict]:
    """News tagged with `symbol` (multikey hit on `tickers`), optionally
    bounded by `[since, until]` (inclusive, on `published_at`).

    Symbol is upper-cased before matching — provider adapters MUST store
    tickers upper-case (see `news_sink.build_news_doc`).
    """
    coll = collection if collection is not None else _collection_from_env()
    if coll is None:
        return []
    sym = symbol.upper().strip()
    flt: dict[str, Any] = {"tickers": sym}
    since_iso = _to_iso(since)
    until_iso = _to_iso(until)
    if since_iso or until_iso:
        window: dict[str, Any] = {}
        if since_iso:
            window["$gte"] = since_iso
        if until_iso:
            window["$lte"] = until_iso
        flt["published_at"] = window
    try:
        cursor = coll.find(flt).sort("published_at", -1).limit(int(limit))
        return [_trim(d) for d in cursor]
    except Exception as exc:
        logger.warning("news_query.by_symbol: find failed (%s)", exc)
        return []


def by_source(
    source: str,
    *,
    limit: int = 100,
    collection: Any | None = None,
) -> list[dict]:
    """Most recent N items from a given provider (e.g. `cryptopanic`,
    `okx-news`). Used as an operational sanity check — did this source
    actually land anything since the last cron?"""
    coll = collection if collection is not None else _collection_from_env()
    if coll is None:
        return []
    try:
        cursor = coll.find({"source": source}).sort([("fetched_at", -1)]).limit(int(limit))
        return [_trim(d) for d in cursor]
    except Exception as exc:
        logger.warning("news_query.by_source: find failed (%s)", exc)
        return []
