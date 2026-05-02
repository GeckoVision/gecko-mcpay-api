"""Mongo write paths for the chunk store (S18-MONGO-WRITE-01).

Mirrors the four chunk-write methods on ``SessionStore``:
- ``insert_chunks`` → :func:`insert_chunks_mongo`
- ``insert_chunks_write_audit`` → :func:`insert_chunks_write_audit_mongo`
- ``get_chunk_cache`` / ``_evict_chunk_cache`` → :func:`get_chunk_cache_mongo` /
  :func:`evict_chunk_cache_mongo`
- ``put_chunk_cache`` → :func:`put_chunk_cache_mongo`

Why the simpler shape vs Supabase:

- No payload halving. Mongo's 16 MB BSON document limit is far above any
  individual chunk; the supabase ``toast_limit`` shed-and-retry path was
  needed because Postgres TOASTing on 1536-dim vectors crossed httpx
  read timeouts. Mongo bulk inserts split client-side; we use
  ``ordered=False`` so duplicate-key errors on
  ``(source_id, chunk_index)`` are skipped instead of aborting the batch.
- No background eviction race. The supabase eviction is a delete on a
  pgvector index that can fight readers; in Mongo, deleteMany on the
  unique-PK is tiny and atomic.
- No model fingerprint default trick. The PK is
  ``(url_hash, chunk_index, embed_model)``. Caller must pass the model
  string explicitly; we don't carry the legacy ``None → DEFAULT`` ergonomic
  because a dim-mismatch is much louder than a silent default swap.

Read paths (``match_chunks``, ``match_chunks_windowed``,
``match_chunks_hybrid``) live in M4 — see ``gecko_core.rag.query`` once
that ticket lands.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from gecko_core.db.mongo import (
    audit_collection,
    cache_collection,
    chunks_collection,
)

if TYPE_CHECKING:
    from gecko_core.sources.types import ProviderKind

logger = logging.getLogger(__name__)

EMBED_DIM = 1536


class _MongoUnavailable(RuntimeError):
    """Raised when a Mongo write is attempted but the client isn't configured.

    Surfaced by ``insert_chunks_mongo`` / ``put_chunk_cache_mongo`` when
    ``GECKO_CHUNK_STORE=mongo`` is set but ``MONGODB_URI`` is missing.
    Caller (SessionStore) should treat this the same as any other write
    failure — the pipeline's audit row will record ``unknown`` and the
    request fails loudly. Better than a silent no-op that ships zero
    chunks under a green status code.
    """


# ---------------------------------------------------------------------------
# chunks (insert)
# ---------------------------------------------------------------------------


async def insert_chunks_mongo(
    session_id: UUID,
    source_id: UUID,
    chunks: list[tuple[int, str, list[float]]],
    *,
    provider_kind: ProviderKind = "web",
    project_id: UUID | None = None,
    source_url: str | None = None,
) -> int:
    """Bulk-insert chunks. Returns count of *new* documents written.

    Uses ``insert_many(ordered=False)`` so duplicate-key errors on the
    ``(source_id, chunk_index)`` unique index are tolerated — a re-run of
    the same source produces zero net new docs but doesn't raise.
    Pre-flight validation mirrors the Supabase path.
    """
    if not chunks:
        return 0

    from gecko_core.ingestion.exceptions import ChunkValidationError

    for idx, text, embedding in chunks:
        if not text or not text.strip():
            raise ChunkValidationError(
                f"chunk_index={idx} has empty/whitespace text",
                kind="empty_text",
            )
        if len(embedding) != EMBED_DIM:
            raise ChunkValidationError(
                f"chunk_index={idx} embedding dim {len(embedding)} != expected {EMBED_DIM}",
                kind="dim_mismatch",
            )

    coll = chunks_collection()
    if coll is None:
        raise _MongoUnavailable(
            "chunks_collection is None — MONGODB_URI unset or motor missing",
        )

    now = datetime.now(UTC)
    # source_url is denormalized onto the chunk doc so M4 read paths don't
    # need a Supabase round-trip per query — sources stay on Supabase, but
    # chunks own their own URL for citation rendering.
    docs: list[dict[str, Any]] = [
        {
            "session_id": str(session_id),
            "source_id": str(source_id),
            "source_url": source_url,
            "chunk_index": idx,
            "text": text,
            "embedding": embedding,
            "provider_kind": provider_kind,
            "project_id": str(project_id) if project_id is not None else None,
            "captured_at": now,
        }
        for idx, text, embedding in chunks
    ]

    try:
        result = await coll.insert_many(docs, ordered=False)
        inserted = len(result.inserted_ids)
    except Exception as exc:
        # pymongo raises BulkWriteError on duplicate keys with ordered=False;
        # the partial result lives on exc.details. Treat duplicates as
        # "already durable" and count them as inserted from the caller's POV.
        details = getattr(exc, "details", None)
        if isinstance(details, dict):
            n_inserted = int(details.get("nInserted", 0))
            write_errors = details.get("writeErrors", [])
            non_dup = [e for e in write_errors if e.get("code") != 11000]
            if non_dup:
                logger.warning(
                    "mongo.insert_chunks.partial_failure",
                    extra={
                        "session_id": str(session_id),
                        "source_id": str(source_id),
                        "n_inserted": n_inserted,
                        "n_dup_skipped": len(write_errors) - len(non_dup),
                        "n_real_errors": len(non_dup),
                        "first_error_code": non_dup[0].get("code"),
                    },
                )
                raise
            inserted = len(docs)
        else:
            raise

    logger.info(
        "mongo.insert_chunks.done",
        extra={
            "session_id": str(session_id),
            "source_id": str(source_id),
            "n_inbound": len(docs),
            "n_inserted": inserted,
            "provider_kind": provider_kind,
        },
    )
    return inserted


# ---------------------------------------------------------------------------
# chunks_write_audit
# ---------------------------------------------------------------------------


async def insert_chunks_write_audit_mongo(
    *,
    session_id: UUID,
    source_id: UUID | None,
    batch_size: int,
    succeeded: int,
    failed: int,
    error_kind: str,
    embed_model: str | None,
) -> None:
    """Best-effort audit insert. Errors are swallowed by design.

    Audit rows must NEVER fail an ingestion request. The classifier already
    surfaced the real outcome via the caller's logger; losing the audit
    document is observability debt, not data loss.
    """
    coll = audit_collection()
    if coll is None:
        return

    doc = {
        "session_id": str(session_id),
        "source_id": str(source_id) if source_id is not None else None,
        "batch_size": batch_size,
        "succeeded": succeeded,
        "failed": failed,
        "error_kind": error_kind,
        "embed_model": embed_model,
        "captured_at": datetime.now(UTC),
    }
    import contextlib

    with contextlib.suppress(Exception):
        await coll.insert_one(doc)


async def chunks_write_audit_rollup_recent_mongo(*, days: int = 7) -> list[dict[str, Any]]:
    """Return [{error_kind, count}] for the last ``days``. Empty on no data."""
    coll = audit_collection()
    if coll is None:
        return []

    from datetime import timedelta

    since = datetime.now(UTC) - timedelta(days=days)
    pipeline: list[dict[str, Any]] = [
        {"$match": {"captured_at": {"$gte": since}}},
        {"$group": {"_id": "$error_kind", "count": {"$sum": 1}}},
        {"$project": {"_id": 0, "error_kind": "$_id", "count": 1}},
    ]
    rows: list[dict[str, Any]] = []
    async for r in coll.aggregate(pipeline):
        rows.append(r)
    rows.sort(key=lambda r: (r["error_kind"] != "none", r["error_kind"]))
    return rows


# ---------------------------------------------------------------------------
# chunk_embedding_cache
# ---------------------------------------------------------------------------


async def get_chunk_cache_mongo(
    url_hash: str,
    indices: list[int],
    *,
    embed_model: str | None = None,
) -> dict[int, list[float]]:
    """Return ``{chunk_index: embedding}`` for cached rows. Empty on miss."""
    if not indices:
        return {}

    coll = cache_collection()
    if coll is None:
        return {}

    query: dict[str, Any] = {
        "url_hash": url_hash,
        "chunk_index": {"$in": indices},
    }
    if embed_model is not None:
        query["embed_model"] = embed_model

    out: dict[int, list[float]] = {}
    evict_indices: list[int] = []
    async for doc in coll.find(query, projection={"chunk_index": 1, "embedding": 1}):
        idx = doc.get("chunk_index")
        emb = doc.get("embedding")
        if idx is None or not isinstance(emb, list):
            continue
        vec = [float(v) for v in emb]
        if len(vec) != EMBED_DIM:
            logger.warning(
                "mongo.cache.dim_mismatch_evict",
                extra={
                    "url_hash": url_hash,
                    "chunk_index": int(idx),
                    "got_dim": len(vec),
                    "expected_dim": EMBED_DIM,
                    "error_kind": "dim_mismatch",
                },
            )
            evict_indices.append(int(idx))
            continue
        out[int(idx)] = vec

    if evict_indices:
        try:
            await evict_chunk_cache_mongo(url_hash, evict_indices)
        except Exception as exc:  # pragma: no cover — best-effort
            logger.info(
                "mongo.cache.evict_failed url_hash=%s err=%s",
                url_hash,
                exc.__class__.__name__,
            )
    return out


async def evict_chunk_cache_mongo(url_hash: str, indices: list[int]) -> None:
    """Delete poisoned cache rows. Mirrors ``_evict_chunk_cache`` semantics."""
    coll = cache_collection()
    if coll is None:
        return
    await coll.delete_many({"url_hash": url_hash, "chunk_index": {"$in": indices}})


async def put_chunk_cache_mongo(
    url_hash: str,
    rows: list[tuple[int, str, list[float]]],
    *,
    embed_model: str | None = None,
) -> None:
    """Upsert cache rows. First-writer-wins on the unique PK.

    Always pass an explicit ``embed_model``. The Mongo schema does NOT
    apply the legacy ``text-embedding-3-small`` default — a None passed
    through here writes ``None`` and the unique key
    ``(url_hash, chunk_index, embed_model=None)`` will collide weirdly
    with later explicit-model writes. Callers (the pipeline) already pass
    the active model from ``IngestionSettings().embed_model``.
    """
    if not rows:
        return
    coll = cache_collection()
    if coll is None:
        return

    model = embed_model or "text-embedding-3-small"
    now = datetime.now(UTC)
    operations: list[Any] = []
    from pymongo import UpdateOne

    for idx, text, embedding in rows:
        operations.append(
            UpdateOne(
                {
                    "url_hash": url_hash,
                    "chunk_index": idx,
                    "embed_model": model,
                },
                {
                    "$setOnInsert": {
                        "url_hash": url_hash,
                        "chunk_index": idx,
                        "text": text,
                        "embedding": embedding,
                        "embed_model": model,
                        "cached_at": now,
                    }
                },
                upsert=True,
            )
        )
    if operations:
        await coll.bulk_write(operations, ordered=False)


__all__ = [
    "EMBED_DIM",
    "chunks_write_audit_rollup_recent_mongo",
    "evict_chunk_cache_mongo",
    "get_chunk_cache_mongo",
    "insert_chunks_mongo",
    "insert_chunks_write_audit_mongo",
    "put_chunk_cache_mongo",
]
