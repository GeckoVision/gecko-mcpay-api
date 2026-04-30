"""`gecko_resume <project_id>` — structured summary of a project's recent loop.

Walks memory entries scoped to the project for the last `days` (default
30), groups by entry_type, and renders a compact summary. Sub-second:
single indexed query, group + format in-memory, no LLM call.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from gecko_core.memory import MemoryEntryType, MemoryScope, recall
from gecko_core.memory.models import MemoryEntry
from gecko_core.memory.store import MemoryStore


class ProjectResume(BaseModel):
    """Structured payload returned by `gecko_resume`."""

    project_id: str
    last_activity_at: datetime | None
    by_type: dict[str, list[dict[str, Any]]]
    last_panel_voices: list[dict[str, Any]]
    last_pulse_deltas: list[dict[str, Any]]


async def build_resume(
    project_id: UUID | str,
    *,
    days: int = 30,
    store: MemoryStore | None = None,
    limit: int = 200,
) -> ProjectResume:
    """Return a ProjectResume for the project.

    `days` bounds the recall window; the indexed scope-query is cheap, so
    we pull up to `limit` entries and group in memory.
    """
    pid = str(project_id) if not isinstance(project_id, str) else project_id
    scope = MemoryScope(type="project", id=pid)
    since = datetime.now(UTC) - timedelta(days=days)

    entries = await recall(scope, limit=limit, since=since, store=store)

    by_type: dict[str, list[MemoryEntry]] = defaultdict(list)
    for e in entries:
        by_type[e.entry_type.value].append(e)

    last_activity = entries[0].created_at if entries else None

    # Last panel: most recent plan_advised entry.
    last_panel_voices: list[dict[str, Any]] = []
    plans = by_type.get(MemoryEntryType.plan_advised.value, [])
    if plans:
        v = plans[0].value.get("voices") or []
        if isinstance(v, list):
            last_panel_voices = [item for item in v if isinstance(item, dict)]

    # Last pulse: most recent pulse_run entry.
    last_pulse_deltas: list[dict[str, Any]] = []
    pulses = by_type.get(MemoryEntryType.pulse_run.value, [])
    if pulses:
        d = pulses[0].value.get("deltas") or []
        if isinstance(d, list):
            last_pulse_deltas = [item for item in d if isinstance(item, dict)]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for type_name, items in by_type.items():
        grouped[type_name] = [
            {
                "id": str(item.id),
                "key": item.key,
                "value": item.value,
                "tx_signature": item.tx_signature,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]

    return ProjectResume(
        project_id=pid,
        last_activity_at=last_activity,
        by_type=grouped,
        last_panel_voices=last_panel_voices,
        last_pulse_deltas=last_pulse_deltas,
    )


__all__ = ["ProjectResume", "build_resume"]
