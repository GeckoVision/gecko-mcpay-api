from __future__ import annotations

import logging
import os

logger = logging.getLogger("decision_store.mongo")


def best_effort_upsert(coll, flt: dict, doc: dict) -> bool:
    """Upsert; NEVER raises (the trading loop must not crash on Mongo). Returns success."""
    try:
        coll.update_one(flt, {"$set": doc}, upsert=True)
        return True
    except Exception as exc:  # noqa: BLE001 — fail-safe by design
        logger.warning(
            "decision_store: mongo upsert failed (%s); JSONL remains source of truth", exc
        )
        return False


def get_collections():
    """Return (simulations, decisions) collections, or (None, None) if Mongo unreachable."""
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None, None
    try:
        from pymongo import MongoClient

        db = MongoClient(uri, serverSelectionTimeoutMS=3000)[
            os.environ.get("MONGODB_DB", "gecko")
        ]
        return db["simulations"], db["decisions"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("decision_store: mongo unavailable (%s); JSONL-only", exc)
        return None, None
