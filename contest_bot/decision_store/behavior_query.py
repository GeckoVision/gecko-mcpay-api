"""Read-side helpers over the `bot_behaviors` Mongo collection.

Two queries, scoped tight to the founder's narrative:

  find_similar(text, limit=10)
      Voyage-embed the summary text, run an in-process cosine scan over
      candidate `bot_behaviors` rows that have an `embedding`. When an
      Atlas Search `bot_behaviors_vec` index lands (v2 — see roadmap),
      this flips to `$vectorSearch` with a one-method change.

  discipline_score(symbol=None, days=7)
      The discipline-thesis aggregate (design doc §7 Q3):
      "of N declines in the last K days, how many were PREVENTED_LOSS?"
      Returns per-symbol breakdown.

Both functions accept an injected `collection` so tests can pass a fake
without standing up Mongo. Both return Python lists/dicts (BSON-friendly,
no Mongo-specific objects bleed out).

Design notes:
    * Cosine search is identical-shape to `decision_store/query.py` —
      reuse-by-pattern, not import (different collection, different schema).
    * `find_similar` will NOT auto-embed unembedded rows. If the row is
      missing `embedding`, it's skipped. Backfill is a separate script.
    * `discipline_score` runs a single Mongo aggregation; no Python loop.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("decision_store.behavior_query")

DEFAULT_DB = "gecko"
DEFAULT_COLLECTION = "bot_behaviors"


def _collection_from_env() -> Any | None:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None
    try:
        from pymongo import MongoClient

        db = MongoClient(uri, serverSelectionTimeoutMS=3000)[
            os.environ.get("MONGODB_DB", DEFAULT_DB)
        ]
        return db[os.environ.get("MONGODB_BEHAVIOR_COLL", DEFAULT_COLLECTION)]
    except Exception as exc:
        logger.warning("behavior_query: mongo unavailable (%s)", exc)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def find_similar(
    decision_summary_text: str,
    *,
    limit: int = 10,
    collection: Any | None = None,
    filters: dict | None = None,
    embed_fn: Any | None = None,
) -> list[dict]:
    """Top-`limit` behaviors by cosine similarity to the embedded text.

    Each result is `{score: float, doc: dict}` with `doc` shaped like the
    full BSON row (minus the `embedding` field — trimmed to keep the result
    payload small).

    Args:
        decision_summary_text: human-readable summary (same format as
            `decision_store.embedder.decision_summary_text` output).
        limit: top-k to return (default 10).
        collection: injected collection (for tests). Defaults to
            `MONGODB_URI`-bound `bot_behaviors`.
        filters: optional pre-filter dict applied to `collection.find()`,
            e.g. `{"symbol": "WIF", "action": "decline"}`. Reduces candidate
            count BEFORE the in-process cosine pass.
        embed_fn: defaults to `decision_store.embedder.embed_blocking`. Tests
            inject a fake to skip the Voyage call.

    Returns empty list on any failure (no exceptions surface to caller).
    """
    coll = collection if collection is not None else _collection_from_env()
    if coll is None:
        logger.info("behavior_query.find_similar: no collection; returning []")
        return []

    if embed_fn is None:
        try:
            from .embedder import embed_blocking as embed_fn  # type: ignore[no-redef]
        except Exception as exc:
            logger.warning("behavior_query: embedder import failed (%s)", exc)
            return []

    try:
        qvec, _model = embed_fn(decision_summary_text)
    except Exception as exc:
        logger.warning("behavior_query: embed failed (%s)", exc)
        return []
    if qvec is None:
        return []

    flt: dict[str, Any] = dict(filters or {})
    flt["embedding"] = {"$exists": True, "$ne": None}

    try:
        cursor = coll.find(flt)
    except Exception as exc:
        logger.warning("behavior_query: find failed (%s)", exc)
        return []

    scored: list[dict] = []
    for doc in cursor:
        emb = doc.get("embedding")
        if not emb:
            continue
        score = _cosine(qvec, emb)
        # Drop the embedding from the returned doc — caller doesn't need 1024
        # floats per result and shipping them across an MCP boundary is waste.
        trimmed = {k: v for k, v in doc.items() if k != "embedding"}
        scored.append({"score": score, "doc": trimmed})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def discipline_score(
    *,
    symbol: str | None = None,
    days: int = 7,
    collection: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The discipline-thesis aggregate, per design doc §7 Q3.

    For each symbol (or just `symbol` if scoped), in the last `days`:

        total_declines       — all rows where action=decline AND labeled
        prevented_losses     — counterfactual.label == "PREVENTED_LOSS"
        missed_wins          — counterfactual.label == "MISSED_WIN"
        neutral              — counterfactual.label == "NEUTRAL"
        discipline           — prevented_losses / total_declines (0.0 if 0)

    Returns:
        {
            "window_days": 7,
            "now": "ISO-8601",
            "per_symbol": [{symbol, total, prevented, missed, neutral, discipline}, ...],
            "global": {total, prevented, missed, neutral, discipline}
        }

    Empty per_symbol + zeroed global on any failure.
    """
    coll = collection if collection is not None else _collection_from_env()
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    empty: dict[str, Any] = {
        "window_days": days,
        "now": (now or datetime.now(UTC)).isoformat(),
        "per_symbol": [],
        "global": {"total": 0, "prevented": 0, "missed": 0, "neutral": 0, "discipline": 0.0},
    }
    if coll is None:
        return empty

    match_stage: dict[str, Any] = {
        "action": "decline",
        "counterfactual.status": "labeled",
        "ts": {"$gte": cutoff.isoformat()},
    }
    if symbol is not None:
        match_stage["symbol"] = symbol

    pipeline: list[dict[str, Any]] = [
        {"$match": match_stage},
        {
            "$group": {
                "_id": "$symbol",
                "total": {"$sum": 1},
                "prevented": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$counterfactual.label", "PREVENTED_LOSS"]},
                            1,
                            0,
                        ]
                    }
                },
                "missed": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$counterfactual.label", "MISSED_WIN"]},
                            1,
                            0,
                        ]
                    }
                },
                "neutral": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$counterfactual.label", "NEUTRAL"]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {"$sort": {"total": -1}},
    ]

    try:
        rows = list(coll.aggregate(pipeline))
    except Exception as exc:
        logger.warning("behavior_query.discipline_score: aggregate failed (%s)", exc)
        return empty

    per_symbol: list[dict[str, Any]] = []
    global_total = 0
    global_prev = 0
    global_miss = 0
    global_neut = 0
    for r in rows:
        total = int(r.get("total", 0))
        prev = int(r.get("prevented", 0))
        miss = int(r.get("missed", 0))
        neut = int(r.get("neutral", 0))
        per_symbol.append(
            {
                "symbol": r.get("_id"),
                "total": total,
                "prevented": prev,
                "missed": miss,
                "neutral": neut,
                "discipline": (prev / total) if total else 0.0,
            }
        )
        global_total += total
        global_prev += prev
        global_miss += miss
        global_neut += neut

    return {
        "window_days": days,
        "now": (now or datetime.now(UTC)).isoformat(),
        "per_symbol": per_symbol,
        "global": {
            "total": global_total,
            "prevented": global_prev,
            "missed": global_miss,
            "neutral": global_neut,
            "discipline": (global_prev / global_total) if global_total else 0.0,
        },
    }
