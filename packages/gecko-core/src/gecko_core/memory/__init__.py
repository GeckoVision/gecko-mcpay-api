"""Native Gecko decision-memory layer (S5-MEM-02).

Public surface: ``save``, ``recall``, ``search``, ``delete``. The five paid
loop entry points (research / scaffold / plan / advise / pulse) hook into
``save`` via the auto-journal layer (S5-MEM-04). Cross-scope isolation is
enforced server-side via the ``gecko_memory_match`` RPC.

Design notes:

- Embedding is computed at *save* time from a textual representation of
  ``value`` (NOT ``key``) via ``ingestion.embedder.embed`` — same retry +
  concurrency cap as the rest of the pipeline.
- ``search`` embeds the query string fresh per call.
- ``recall`` is the cheap path: indexed lookup by (scope_type, scope_id,
  entry_type, created_at DESC). No embedding work.
- TTL is enforced at *read* time. Deletion is a Sprint 6 cron sweep.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from gecko_core.memory.embedder import embed_text, render_value_for_embedding
from gecko_core.memory.models import MemoryEntry, MemoryEntryType, MemoryScope
from gecko_core.memory.store import MemoryStore

logger = logging.getLogger(__name__)


async def save(
    scope: MemoryScope,
    entry_type: MemoryEntryType,
    value: dict[str, Any],
    *,
    key: str | None = None,
    tx_signature: str | None = None,
    ttl_at: datetime | None = None,
    store: MemoryStore | None = None,
    embed: bool = True,
) -> UUID:
    """Persist one memory entry. Returns the new UUID.

    Embedding is computed from ``render_value_for_embedding(entry_type,
    value, key=key)``. Pass ``embed=False`` for synthetic/test rows that
    should skip the OpenAI call (the row will be invisible to ``search``
    but still findable via ``recall``).
    """
    store = store or MemoryStore.from_env()
    embedding: list[float] | None = None
    if embed:
        text = render_value_for_embedding(entry_type.value, value, key=key)
        try:
            embedding = await embed_text(text)
        except Exception as exc:  # pragma: no cover — best effort
            logger.warning("memory.save: embed failed (%s); persisting without vector", exc)
            embedding = None

    return await store.insert(
        scope=scope,
        entry_type=entry_type,
        value=value,
        embedding=embedding,
        key=key,
        tx_signature=tx_signature,
        ttl_at=ttl_at,
    )


async def recall(
    scope: MemoryScope,
    *,
    entry_type: MemoryEntryType | None = None,
    key: str | None = None,
    limit: int = 20,
    since: datetime | None = None,
    store: MemoryStore | None = None,
) -> list[MemoryEntry]:
    """List entries for a scope, newest first. Cheap (no embedding work)."""
    store = store or MemoryStore.from_env()
    return await store.list_by_scope(
        scope=scope,
        entry_type=entry_type,
        key=key,
        limit=limit,
        since=since,
    )


async def search(
    scope: MemoryScope,
    query: str,
    *,
    top_k: int = 5,
    similarity_threshold: float = 0.6,
    store: MemoryStore | None = None,
) -> list[tuple[MemoryEntry, float]]:
    """Cosine-similarity top-k for `query` within `scope`."""
    store = store or MemoryStore.from_env()
    embedding = await embed_text(query)
    return await store.search(
        scope=scope,
        query_embedding=embedding,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )


async def delete(
    entry_id: UUID,
    *,
    requesting_user_id: str,
    store: MemoryStore | None = None,
) -> None:
    """Hard-delete one entry. Application-layer ownership check.

    v1 doesn't yet have Supabase auth integration, so ownership is enforced
    here by re-loading the entry and comparing ``scope`` to the requesting
    user. For project/session-scoped entries the API layer is responsible
    for asserting that the requesting user owns the project / session
    BEFORE calling this function.
    """
    store = store or MemoryStore.from_env()
    entry = await store.get(entry_id)
    if entry is None:
        return
    if entry.scope.type == "user" and entry.scope.id != requesting_user_id:
        raise PermissionError(
            f"user {requesting_user_id!r} cannot delete a memory entry "
            f"scoped to user {entry.scope.id!r}"
        )
    await store.delete(entry_id)


__all__ = [
    "MemoryEntry",
    "MemoryEntryType",
    "MemoryScope",
    "MemoryStore",
    "delete",
    "recall",
    "save",
    "search",
]
