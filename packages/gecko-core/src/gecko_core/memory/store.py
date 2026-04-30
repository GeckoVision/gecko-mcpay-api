"""Supabase wrapper for the `memory` table (S5-MEM-02).

Async surface; the underlying supabase-py client is sync, so calls dispatch
via asyncio.to_thread to avoid blocking the event loop. Mirrors the pattern
in `gecko_core.sessions.store`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from supabase import Client

from gecko_core.db import create_supabase_client
from gecko_core.memory.models import MemoryEntry, MemoryEntryType, MemoryScope

logger = logging.getLogger(__name__)


class MemoryStore:
    """Async wrapper over the Supabase service-role client for `memory` CRUD."""

    MEMORY_TABLE = "memory"
    MEMORY_MATCH_RPC = "gecko_memory_match"

    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> MemoryStore:
        """Build a store using SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY from env."""
        return cls(create_supabase_client())

    async def insert(
        self,
        *,
        scope: MemoryScope,
        entry_type: MemoryEntryType,
        value: dict[str, Any],
        embedding: list[float] | None,
        key: str | None = None,
        tx_signature: str | None = None,
        ttl_at: datetime | None = None,
    ) -> UUID:
        """Insert one memory row. Returns the new UUID."""
        payload: dict[str, Any] = {
            "scope_type": scope.type,
            "scope_id": scope.id,
            "entry_type": entry_type.value,
            "key": key,
            "value": value,
            "embedding": embedding,
            "tx_signature": tx_signature,
            "ttl_at": ttl_at.isoformat() if ttl_at is not None else None,
        }

        def _insert() -> dict[str, Any]:
            res = self._client.table(self.MEMORY_TABLE).insert(payload).execute()
            data = res.data or []
            if not data:
                raise RuntimeError("memory insert returned no rows")
            return cast(dict[str, Any], data[0])

        row = await asyncio.to_thread(_insert)
        return UUID(str(row["id"]))

    async def list_by_scope(
        self,
        *,
        scope: MemoryScope,
        entry_type: MemoryEntryType | None = None,
        key: str | None = None,
        limit: int = 20,
        since: datetime | None = None,
    ) -> list[MemoryEntry]:
        """Return memory entries for a scope, newest first.

        Filters expired (`ttl_at <= NOW()`) rows at read time. The embedding
        column is intentionally omitted — heavy and unused on this path.
        """

        def _select() -> list[dict[str, Any]]:
            q = (
                self._client.table(self.MEMORY_TABLE)
                .select(
                    "id,scope_type,scope_id,entry_type,key,value,tx_signature,created_at,ttl_at"
                )
                .eq("scope_type", scope.type)
                .eq("scope_id", scope.id)
            )
            if entry_type is not None:
                q = q.eq("entry_type", entry_type.value)
            if key is not None:
                q = q.eq("key", key)
            if since is not None:
                q = q.gte("created_at", since.isoformat())
            q = q.order("created_at", desc=True).limit(limit)
            res = q.execute()
            return cast(list[dict[str, Any]], res.data or [])

        rows = await asyncio.to_thread(_select)
        out: list[MemoryEntry] = []
        now = datetime.now(UTC)
        for r in rows:
            ttl_raw = r.get("ttl_at")
            if ttl_raw:
                try:
                    ttl_at = datetime.fromisoformat(str(ttl_raw).replace("Z", "+00:00"))
                except ValueError:
                    ttl_at = None
                if ttl_at is not None and ttl_at <= now:
                    continue
            out.append(_row_to_entry(r))
        return out

    async def search(
        self,
        *,
        scope: MemoryScope,
        query_embedding: list[float],
        top_k: int = 5,
        similarity_threshold: float = 0.6,
    ) -> list[tuple[MemoryEntry, float]]:
        """Cosine top-k. Server-side scope filter (RPC) prevents cross-scope leakage."""

        def _rpc() -> list[dict[str, Any]]:
            res = self._client.rpc(
                self.MEMORY_MATCH_RPC,
                {
                    "p_scope_type": scope.type,
                    "p_scope_id": scope.id,
                    "p_query_embedding": query_embedding,
                    "p_match_limit": top_k,
                    "p_similarity_threshold": similarity_threshold,
                },
            ).execute()
            return cast(list[dict[str, Any]], res.data or [])

        rows = await asyncio.to_thread(_rpc)
        out: list[tuple[MemoryEntry, float]] = []
        for r in rows:
            sim = float(r.get("similarity") or 0.0)
            out.append((_row_to_entry(r), sim))
        return out

    async def delete(self, entry_id: UUID) -> bool:
        """Hard-delete one row. Returns True if a row was deleted.

        Application-layer ownership check happens in the public `delete()`
        helper (memory.__init__) — service-role client bypasses RLS.
        """

        def _delete() -> list[dict[str, Any]]:
            res = self._client.table(self.MEMORY_TABLE).delete().eq("id", str(entry_id)).execute()
            return cast(list[dict[str, Any]], res.data or [])

        rows = await asyncio.to_thread(_delete)
        return bool(rows)

    async def get(self, entry_id: UUID) -> MemoryEntry | None:
        """Fetch one entry by id (no embedding)."""

        def _select() -> list[dict[str, Any]]:
            res = (
                self._client.table(self.MEMORY_TABLE)
                .select("id,scope_type,scope_id,entry_type,key,value,tx_signature,created_at")
                .eq("id", str(entry_id))
                .limit(1)
                .execute()
            )
            return cast(list[dict[str, Any]], res.data or [])

        rows = await asyncio.to_thread(_select)
        if not rows:
            return None
        return _row_to_entry(rows[0])

    async def recent_project_ids(
        self,
        *,
        since: datetime | None = None,
        limit: int = 5,
    ) -> list[str]:
        """Return up to ``limit`` distinct project scope_ids with recent entries.

        S8-REVIEW-01: drives ``bb sprint-review`` auto-discovery so callers
        without ``--project-id`` see the most-recently-journaled projects
        instead of an empty review. Sorted by most-recent ``created_at``.
        Filters to ``scope_type='project'``; user/session scopes are ignored
        because they aren't valid review targets.
        """

        def _select() -> list[dict[str, Any]]:
            q = (
                self._client.table(self.MEMORY_TABLE)
                .select("scope_id,created_at")
                .eq("scope_type", "project")
            )
            if since is not None:
                q = q.gte("created_at", since.isoformat())
            # Pull more than `limit` rows so we can dedupe by scope_id while
            # still surfacing the freshest unique ids. 200 is a safe ceiling
            # for a 14-day window even on heavily-journaled projects.
            q = q.order("created_at", desc=True).limit(200)
            res = q.execute()
            return cast(list[dict[str, Any]], res.data or [])

        try:
            rows = await asyncio.to_thread(_select)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("recent_project_ids lookup failed: %s", exc)
            return []
        seen: list[str] = []
        for row in rows:
            sid = str(row.get("scope_id") or "")
            if sid and sid not in seen:
                seen.append(sid)
            if len(seen) >= limit:
                break
        return seen

    async def project_journal_enabled(self, project_id: UUID) -> bool:
        """Return projects.journal_enabled. Defaults to True if column missing/row absent."""

        def _select() -> list[dict[str, Any]]:
            res = (
                self._client.table("projects")
                .select("journal_enabled")
                .eq("id", str(project_id))
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )
            return cast(list[dict[str, Any]], res.data or [])

        try:
            rows = await asyncio.to_thread(_select)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("project_journal_enabled lookup failed: %s", exc)
            return True
        if not rows:
            return True
        flag = rows[0].get("journal_enabled")
        return bool(flag) if flag is not None else True


def _row_to_entry(row: dict[str, Any]) -> MemoryEntry:
    created_raw = row.get("created_at")
    if isinstance(created_raw, datetime):
        created_at = created_raw
    else:
        created_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
    value_raw = row.get("value") or {}
    return MemoryEntry(
        id=UUID(str(row["id"])),
        scope=MemoryScope(
            type=cast(Any, row["scope_type"]),
            id=str(row["scope_id"]),
        ),
        entry_type=MemoryEntryType(row["entry_type"]),
        key=row.get("key"),
        value=cast("dict[str, Any]", value_raw if isinstance(value_raw, dict) else {}),
        tx_signature=row.get("tx_signature"),
        created_at=created_at,
    )


__all__ = ["MemoryStore"]
