"""Best-effort sink: cross-source oracle snapshots → Mongo `oracle_snapshots`.

Design ref: docs/build-plan-sprint-29-oracle-ingest.md

Why a SINK with the same shape as NewsSink + BehaviorSink:

Consistency. Every collection in our Mongo substrate uses the same
{from_env() → record(doc) → async best-effort upsert + idempotency key}
pattern. The oracle_voice (Sprint 29, contest_bot/voices/oracle_voice.py)
reads through snapshot_query.py which mirrors news_query.py exactly.

Shape:
    sink = OracleSnapshotSink.from_env()  # None if MONGODB_URI unset
    sink.record(snapshot_doc)             # dict: see build_snapshot_doc

Idempotent: keyed on `snapshot_id` (unique). Deterministic from
sha256(source|symbol|ts_iso) when caller doesn't supply it. Best-effort:
NEVER raises (mirrors behavior_sink._do_upsert). Async fire-and-forget.

Embedding field LEFT ABSENT in v1 per behavior_sink.py:147 precedent —
the design doc §4 specifies the embedding_summary text shape but the
Voyage call is gated to a separate cron'd script. The oracle_voice
itself doesn't need the embedding to function (it reads bias_score-
equivalent metadata: price + spread_pct from each source).

Env:
    MONGODB_URI         — Atlas connection string (required to enable)
    MONGODB_DB          — defaults to "gecko_cache" (matches the others)
    MONGODB_ORACLE_COLL — defaults to "oracle_snapshots"
    GECKO_ORACLE_SINK   — "0" disables even if URI is set (kill switch)
"""

from __future__ import annotations

import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("contest_bot.oracle.snapshot_sink")

DEFAULT_DB = "gecko_cache"
DEFAULT_COLLECTION = "oracle_snapshots"
SCHEMA_V = 1

_EXECUTOR: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(
            max_workers=int(os.environ.get("GECKO_ORACLE_SINK_WORKERS", "2")),
            thread_name_prefix="oracle-sink",
        )
    return _EXECUTOR


def _sink_enabled() -> bool:
    return os.environ.get("GECKO_ORACLE_SINK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _now_dt() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: Any) -> str | None:
    """Normalize to ISO-8601 UTC string. None on garbage."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def build_snapshot_doc(
    *,
    source: str,
    symbol: str,
    price: float,
    spread_pct: float | None = None,
    confidence: float | None = None,
    ts: Any = None,
    publishers_count: int | None = None,
    extras: dict[str, Any] | None = None,
) -> dict:
    """Project ingested fields into the `oracle_snapshots` BSON shape.

    Pure function — safe to call from tests. snapshot_id is deterministic
    on (source, symbol, ts) so re-emission of the same poll is a no-op
    upsert, not a duplicate row.
    """
    ts_iso = _to_iso(ts) or _now_dt().isoformat()
    sym = (symbol or "").upper().strip()
    src = (source or "").lower().strip()
    snapshot_id = hashlib.sha256(f"{src}|{sym}|{ts_iso}".encode()).hexdigest()
    # embedding_summary is the text the future Voyage embedder hooks into.
    # Per design doc §4: composite shape with symbol + price + spread + age.
    summary_parts = [f"{sym} @ ${price:.6f}", f"source={src}"]
    if spread_pct is not None:
        summary_parts.append(f"spread {spread_pct:.3f}%")
    if confidence is not None:
        summary_parts.append(f"conf {confidence:.6f}")
    if publishers_count is not None:
        summary_parts.append(f"{publishers_count} publishers")
    summary_parts.append(f"@ {ts_iso}")
    embedding_summary = "; ".join(summary_parts)

    doc: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "source": src,
        "symbol": sym,
        "price": float(price),
        "spread_pct": float(spread_pct) if spread_pct is not None else None,
        "confidence": float(confidence) if confidence is not None else None,
        "publishers_count": (
            int(publishers_count) if publishers_count is not None else None
        ),
        "ts": ts_iso,
        # embedding fields absent on insert — patched by a later batch job.
        "embedding_model": None,
        "embedding_summary": embedding_summary,
        "embedded_at": None,
        "schema_v": SCHEMA_V,
        "ingested_at": _now_dt(),
    }
    if extras:
        # Pass-through for source-specific extras (feed_id for Pyth,
        # mint for Jupiter). Won't conflict with named fields above.
        for k, v in extras.items():
            if k not in doc:
                doc[k] = v
    return doc


class OracleSnapshotSink:
    """Best-effort writer to Mongo `oracle_snapshots`. Mirrors the
    NewsSink / BehaviorSink API exactly.
    """

    def __init__(
        self,
        collection: Any,
        *,
        async_writes: bool = True,
    ) -> None:
        self._coll = collection
        self._async = async_writes

    @classmethod
    def from_env(cls, **kwargs: Any) -> OracleSnapshotSink | None:
        """Construct from MONGODB_URI. Returns None if Mongo is unreachable
        or the sink is disabled. Callers treat None as 'skip the persist'.
        """
        if not _sink_enabled():
            logger.info("oracle_sink: disabled via GECKO_ORACLE_SINK=0")
            return None
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            logger.info("oracle_sink: MONGODB_URI unset; sink not enabled")
            return None
        try:
            from pymongo import MongoClient

            db = MongoClient(uri, serverSelectionTimeoutMS=3000)[
                os.environ.get("MONGODB_DB", DEFAULT_DB)
            ]
            coll = db[os.environ.get("MONGODB_ORACLE_COLL", DEFAULT_COLLECTION)]
        except Exception as exc:
            logger.warning("oracle_sink: Mongo unavailable (%s); sink disabled", exc)
            return None
        return cls(coll, **kwargs)

    def record(self, snapshot: dict) -> None:
        """Upsert. Fire-and-forget. NEVER raises."""
        try:
            doc = dict(snapshot)
            if "snapshot_id" not in doc:
                # Build the id if caller passed an unprojected row.
                ts_iso = _to_iso(doc.get("ts")) or _now_dt().isoformat()
                sym = (doc.get("symbol") or "").upper().strip()
                src = (doc.get("source") or "").lower().strip()
                doc["snapshot_id"] = hashlib.sha256(
                    f"{src}|{sym}|{ts_iso}".encode()
                ).hexdigest()
        except Exception as exc:
            logger.warning("oracle_sink: build failed (%s); skipping", exc)
            return
        snapshot_id = doc.get("snapshot_id")
        if not snapshot_id:
            return

        if self._async:
            try:
                _get_executor().submit(self._do_upsert, snapshot_id, doc)
            except Exception as exc:
                logger.warning(
                    "oracle_sink: submit failed (%s); fallback sync", exc
                )
                self._do_upsert(snapshot_id, doc)
        else:
            self._do_upsert(snapshot_id, doc)

    def _do_upsert(self, snapshot_id: str, doc: dict) -> None:
        try:
            self._coll.update_one(
                {"snapshot_id": snapshot_id},
                {"$set": doc, "$setOnInsert": {"created_at": _now_dt()}},
                upsert=True,
            )
        except Exception as exc:
            logger.warning(
                "oracle_sink: upsert failed (%s); skipping silently", exc
            )


def shutdown(*, wait: bool = True) -> None:
    """Drain the sink executor. Idempotent."""
    global _EXECUTOR
    if _EXECUTOR is None:
        return
    try:
        _EXECUTOR.shutdown(wait=wait)
    except Exception as exc:
        logger.warning("oracle_sink: shutdown raised (%s)", exc)
    _EXECUTOR = None


__all__ = ["OracleSnapshotSink", "build_snapshot_doc", "shutdown"]
