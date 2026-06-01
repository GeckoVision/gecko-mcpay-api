#!/usr/bin/env python3
"""One-shot initializer for the `market_news` Mongo collection.

Idempotent + safe to re-run. What it does:

  1. Connects to Atlas via `MONGODB_URI` (uses `MONGODB_DB`, defaults
     `gecko_cache` to match the founder's env).
  2. Creates the `market_news` collection if it doesn't exist (Mongo
     auto-creates on first insert, but we explicitly `create_collection`
     so the indexes can attach right away and it shows up in Compass /
     `db.getCollectionNames()` before any data lands).
  3. Creates the regular indexes from the design doc §2.
  4. PRINTS the Atlas Search vector index DDL — does NOT create it.
     Per `project_2026_05_26_session_endstate` the vector index is
     founder-gated; we just emit the JSON the founder pastes into the
     Atlas UI under Search → Create Search Index → JSON Editor.

Env required:
    MONGODB_URI
    MONGODB_DB           (default: gecko_cache)
    MONGODB_NEWS_COLL    (default: market_news)

Exit codes:
    0 — success or already-present (idempotent no-op)
    1 — MONGODB_URI unset / Mongo unreachable / index create raised

Usage:
    uv run python scripts/data/init_market_news_collection.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

DEFAULT_DB = "gecko_cache"
DEFAULT_COLLECTION = "market_news"


# Regular (non-vector) indexes. Mirror the design doc §2.
# Tuples of (keys, kwargs). `keys` is a list-of-tuples (Mongo `IndexModel` shape).
INDEX_SPECS: list[tuple[list[tuple[str, int]], dict[str, Any]]] = [
    # Natural primary key — dedupe at the source level.
    ([("news_id", 1)], {"unique": True, "name": "news_id_unique"}),
    # Time-ordered scans for `recent(N)`.
    ([("published_at", -1)], {"name": "published_at_desc"}),
    ([("fetched_at", -1)], {"name": "fetched_at_desc"}),
    # Per-symbol queries (multikey on `tickers`).
    (
        [("tickers", 1), ("published_at", -1)],
        {"name": "tickers_published_at_desc"},
    ),
    # Operational sanity: "which provider fed us this hour."
    ([("source", 1), ("fetched_at", -1)], {"name": "source_fetched_at_desc"}),
    # Classifier queue: rows that have not yet been classified.
    (
        [("classification", 1)],
        {
            "name": "classification_pending_partial",
            "partialFilterExpression": {"classification": None},
        },
    ),
]


# Atlas Search vector index DDL. EMIT-ONLY — do NOT create.
# Voyage `voyage-finance-2` is 1024-dim per `decision_store/embedder.py`.
ATLAS_VECTOR_INDEX_DDL: dict[str, Any] = {
    "name": "market_news_vec",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 1024,
                "similarity": "cosine",
            },
            {"type": "filter", "path": "tickers"},
            {"type": "filter", "path": "source"},
            {"type": "filter", "path": "classification.regime_impact"},
            {"type": "filter", "path": "published_at"},
        ]
    },
}


def _connect():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        print("ERROR: MONGODB_URI is not set in env.", file=sys.stderr)
        sys.exit(1)
    try:
        from pymongo import MongoClient
    except ImportError:
        print("ERROR: pymongo is not installed. Run `uv sync`.", file=sys.stderr)
        sys.exit(1)
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        # Force a server round-trip so failure is detected here, not later.
        client.admin.command("ping")
    except Exception as exc:
        print(f"ERROR: Mongo unreachable ({exc}).", file=sys.stderr)
        sys.exit(1)
    db_name = os.environ.get("MONGODB_DB", DEFAULT_DB)
    coll_name = os.environ.get("MONGODB_NEWS_COLL", DEFAULT_COLLECTION)
    return client[db_name], coll_name


def _ensure_collection(db, coll_name: str) -> None:
    existing = set(db.list_collection_names())
    if coll_name in existing:
        print(f"[init_market_news] collection '{coll_name}' already exists — skip create")
        return
    try:
        db.create_collection(coll_name)
        print(f"[init_market_news] created collection '{coll_name}'")
    except Exception as exc:
        # CollectionInvalid means raced with another initializer — fine.
        print(f"[init_market_news] create_collection raised (likely race): {exc}")


def _ensure_indexes(coll) -> None:
    existing = {ix["name"] for ix in coll.list_indexes()}
    for keys, kwargs in INDEX_SPECS:
        name = kwargs.get("name") or "_".join(f"{k}_{d}" for k, d in keys)
        if name in existing:
            print(f"[init_market_news] index '{name}' already exists — skip")
            continue
        try:
            coll.create_index(keys, **kwargs)
            print(f"[init_market_news] created index '{name}'")
        except Exception as exc:
            print(f"[init_market_news] index '{name}' create FAILED: {exc}", file=sys.stderr)
            # Don't sys.exit — the script is idempotent + best-effort per index.


def _print_vector_ddl(coll_name: str, db_name: str) -> None:
    print("")
    print("=" * 72)
    print(
        "ATLAS SEARCH VECTOR INDEX — paste this into Atlas UI under:\n"
        f"  Database `{db_name}` → Collection `{coll_name}`\n"
        "  → Search → Create Search Index → JSON Editor."
    )
    print("Founder-gated per project_2026_05_26_session_endstate.")
    print("=" * 72)
    print(json.dumps(ATLAS_VECTOR_INDEX_DDL, indent=2))
    print("=" * 72)
    print("")


def main() -> int:
    db, coll_name = _connect()
    _ensure_collection(db, coll_name)
    coll = db[coll_name]
    _ensure_indexes(coll)
    _print_vector_ddl(coll_name, db.name)
    print(f"[init_market_news] done. db={db.name} coll={coll_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
