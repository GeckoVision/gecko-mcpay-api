"""Mongo storage for the ``protocol_price_history`` collection (Phase 9 v1).

Distinct from ``gecko_core.db.mongo`` (chunks) and
``gecko_core.cache.mongo`` (TTL caches). This module owns one collection
on the ``gecko_rag`` DB:

    protocol_price_history — one doc per (protocol, granularity, ts).

Schema (mirrors ``Candle`` exactly):

    { protocol: str, ts: int, granularity: "1h"|"1d", source: "pyth"|...,
      open: float, high: float, low: float, close: float, vol_usd: float }

Compound index: ``{protocol: 1, granularity: 1, ts: -1}``. The Mongo
shell command lives in the spec doc; live deploy uses
``ensure_indexes()`` below.

Idempotent upsert key: ``(protocol, granularity, ts)``. Re-ingestion of
overlapping windows is safe — the daily cron can replay the last 30d
without duplicating rows.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from gecko_core.db.mongo import _db
from gecko_core.orchestration.trade_panel.backtest.models import (
    BacktestGranularity,
    Candle,
)

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

_log = logging.getLogger(__name__)

PRICE_HISTORY_COLLECTION = "protocol_price_history"


def price_history_collection() -> AsyncIOMotorCollection[Any] | None:
    """Return the price-history collection or None when Mongo isn't wired."""
    db = _db()
    return None if db is None else db[PRICE_HISTORY_COLLECTION]


async def ensure_indexes() -> bool:
    """Create the compound index if missing. Idempotent.

    Returns ``True`` when the index call dispatched (Mongo configured),
    ``False`` when the collection isn't reachable. Production callers run
    this once at startup; tests don't need it.
    """
    coll = price_history_collection()
    if coll is None:
        return False
    try:
        await coll.create_index(
            [("protocol", 1), ("granularity", 1), ("ts", -1)],
            name="protocol_granularity_ts",
            background=True,
        )
        return True
    except Exception as exc:  # pragma: no cover - defensive against test envs
        _log.warning("backtest.storage.ensure_indexes_failed err=%s", exc)
        return False


async def upsert_candles(candles: list[Candle]) -> int:
    """Idempotent upsert keyed on ``(protocol, granularity, ts)``.

    Returns the number of candles dispatched (not the modified count —
    Mongo's bulk-write modified-count semantics aren't useful here since
    re-ingestion of identical rows reports zero modifications).
    """
    if not candles:
        return 0
    coll = price_history_collection()
    if coll is None:
        return 0

    from pymongo import UpdateOne

    ops: list[UpdateOne] = []
    for c in candles:
        ops.append(
            UpdateOne(
                {"protocol": c.protocol, "granularity": c.granularity, "ts": c.ts},
                {"$set": c.model_dump()},
                upsert=True,
            )
        )
    try:
        await coll.bulk_write(ops, ordered=False)
        return len(ops)
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("backtest.storage.upsert_failed err=%s", exc)
        return 0


async def read_candles(
    protocol: str,
    *,
    granularity: BacktestGranularity,
    ts_start: int,
    ts_end: int,
) -> list[Candle]:
    """Read candles for one protocol+granularity in ``[ts_start, ts_end]``.

    Returns ascending by ``ts``. Empty list when Mongo isn't configured
    or no rows match — callers should not distinguish those cases (the
    backtest path treats both as "no history available").
    """
    coll = price_history_collection()
    if coll is None:
        return []
    proto = protocol.strip().lower()
    if not proto:
        return []
    cursor = coll.find(
        {
            "protocol": proto,
            "granularity": granularity,
            "ts": {"$gte": ts_start, "$lte": ts_end},
        }
    ).sort("ts", 1)
    out: list[Candle] = []
    try:
        async for doc in cursor:
            try:
                out.append(
                    Candle(
                        protocol=doc["protocol"],
                        ts=int(doc["ts"]),
                        granularity=doc["granularity"],
                        source=doc.get("source", "fallback"),
                        open=float(doc.get("open", 0.0)),
                        high=float(doc.get("high", 0.0)),
                        low=float(doc.get("low", 0.0)),
                        close=float(doc.get("close", 0.0)),
                        vol_usd=float(doc.get("vol_usd", 0.0)),
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                # Skip malformed rows rather than fail the whole read.
                _log.warning("backtest.storage.read_skip_malformed err=%s", exc)
                continue
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("backtest.storage.read_failed err=%s", exc)
        return []
    return out


__all__ = [
    "PRICE_HISTORY_COLLECTION",
    "ensure_indexes",
    "price_history_collection",
    "read_candles",
    "upsert_candles",
]
