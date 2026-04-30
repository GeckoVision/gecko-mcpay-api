"""Pydantic models for the native Gecko decision-memory layer (S5-MEM-02).

Five typed entry types around the verdict → scaffold → plan → advise → pulse
loop, plus two free-form types (``feature_shipped`` / ``user_note``). The
embedding column is heavy (1536 floats) and is omitted from default reads.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class MemoryEntryType(StrEnum):
    """Typed entry types — the loop steps + two free-form escapes."""

    verdict_received = "verdict_received"
    scaffold_generated = "scaffold_generated"
    plan_advised = "plan_advised"
    advisor_voiced = "advisor_voiced"
    pulse_run = "pulse_run"
    feature_shipped = "feature_shipped"
    user_note = "user_note"
    sprint_reviewed = "sprint_reviewed"


class MemoryScope(BaseModel):
    """{type, id} addressing for a memory entry.

    `type` selects the namespace (project/session/user); `id` is the opaque
    string key inside that namespace (UUID for project/session, frames
    handle for user).
    """

    type: Literal["project", "session", "user"]
    id: str


class MemoryEntry(BaseModel):
    """One row from the `memory` table.

    `embedding` is intentionally optional — the 1536-float payload is heavy
    and most read paths don't need it. Helpers that fetch by scope omit it;
    `search()` returns the entry without the embedding (the similarity
    score is the projection callers actually want).
    """

    id: UUID
    scope: MemoryScope
    entry_type: MemoryEntryType
    key: str | None = None
    value: dict[str, Any]
    embedding: list[float] | None = None
    tx_signature: str | None = None
    created_at: datetime


__all__ = [
    "MemoryEntry",
    "MemoryEntryType",
    "MemoryScope",
]
