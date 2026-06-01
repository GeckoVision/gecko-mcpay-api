#!/usr/bin/env python3
"""Sprint 29 — Idempotent collection + index creator for oracle_snapshots.

Run once per environment. Safe to re-run — every operation is upsert /
ensure-index style. Prints the Atlas Search vector-index DDL at the end
for the founder to paste into Atlas UI (vector index creation is
founder-gated per project_2026_05_26_session_endstate).

Usage:
    set -a; source .env; set +a
    python3 scripts/oracle/init_oracle_snapshots_collection.py

Exit codes:
    0 — success or no-op
    1 — Mongo unavailable
"""

from __future__ import annotations

import json
import logging
import os
import sys

logger = logging.getLogger("init_oracle_snapshots")

REGULAR_INDEXES = [
    # Most-common query: latest snapshot per (symbol, source)
    {"keys": [("symbol", 1), ("source", 1), ("ts", -1)], "name": "symbol_source_ts_desc"},
    # Per-symbol newest-first (used by snapshot_query.by_symbol)
    {"keys": [("symbol", 1), ("ts", -1)], "name": "symbol_ts_desc"},
    # Per-source health diagnostics
    {"keys": [("source", 1), ("ts", -1)], "name": "source_ts_desc"},
    # Idempotency key — uniqueness guarantee on (source, symbol, ts)
    {"keys": [("snapshot_id", 1)], "name": "snapshot_id_unique", "unique": True},
]

VECTOR_INDEX_DDL = {
    "name": "oracle_snapshots_vec",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 1024,
                "similarity": "cosine",
            },
            {"type": "filter", "path": "symbol"},
            {"type": "filter", "path": "source"},
            {"type": "filter", "path": "ts"},
        ]
    },
}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        logger.error("MONGODB_URI not set")
        return 1
    try:
        from pymongo import MongoClient
    except ImportError:
        logger.error("pymongo not installed")
        return 1

    db_name = os.environ.get("MONGODB_DB", "gecko_cache")
    coll_name = os.environ.get("MONGODB_ORACLE_COLL", "oracle_snapshots")

    try:
        db = MongoClient(uri, serverSelectionTimeoutMS=4000)[db_name]
        # Light ping — fails fast if Mongo is unreachable
        db.command("ping")
    except Exception as exc:
        logger.error("Mongo unavailable: %s", exc)
        return 1

    # create_collection is a no-op if the collection exists.
    existing = set(db.list_collection_names())
    if coll_name not in existing:
        db.create_collection(coll_name)
        print(f"Created collection: {db_name}.{coll_name}")
    else:
        print(f"Collection exists: {db_name}.{coll_name}")

    coll = db[coll_name]
    for spec in REGULAR_INDEXES:
        try:
            coll.create_index(
                spec["keys"],
                name=spec["name"],
                unique=spec.get("unique", False),
            )
            print(f"Ensured index: {spec['name']} on {spec['keys']}")
        except Exception as exc:
            logger.warning("Index create failed (%s): %s", spec["name"], exc)

    print()
    print("=" * 70)
    print("Atlas Search vector index — FOUNDER MUST PASTE INTO ATLAS UI")
    print("=" * 70)
    print(f"Database: {db_name}")
    print(f"Collection: {coll_name}")
    print(f"Search index type: Vector Search → JSON Editor")
    print("-" * 70)
    print(json.dumps(VECTOR_INDEX_DDL, indent=2))
    print("-" * 70)
    print("(Will be a no-op until rows actually carry `embedding`;")
    print(" founder also gates the Voyage spend on snapshots.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
