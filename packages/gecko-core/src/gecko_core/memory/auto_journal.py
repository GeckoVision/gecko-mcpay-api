"""Auto-journal hooks for the five paid Gecko entry points (S5-MEM-04).

Each hook is best-effort: a journal write failure logs WARN but never
raises to the user. A `--no-journal` flag (or `journal=False` kwarg) on the
public entry points suppresses the write entirely.

Hook value schemas (verbatim from the dispatch brief):

- verdict_received: {idea, verdict, scores: {tam, wedge, v1_feasibility},
                     sources_count, tx_signature}
- scaffold_generated: {session_id, output_paths, total_tokens, cost_usd}
- plan_advised: {session_id, voices: [{role, closing_line, model_used}],
                 tier_preset, total_cost_usd}
- advisor_voiced: {session_id, role, closing_line, model_used, cost_usd}
- pulse_run: {session_id, prior_panel_id, current_closing_lines,
              deltas: [{voice, before, after}]}
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from gecko_core.memory import MemoryEntryType, MemoryScope, save
from gecko_core.memory.store import MemoryStore

logger = logging.getLogger(__name__)


def _scope_for_session(session_id: UUID, project_id: UUID | None) -> MemoryScope:
    """Prefer project scope when available so cross-session recall works."""
    if project_id is not None:
        return MemoryScope(type="project", id=str(project_id))
    return MemoryScope(type="session", id=str(session_id))


async def _is_enabled(
    *,
    journal: bool,
    project_id: UUID | None,
    store: MemoryStore | None,
) -> bool:
    if not journal:
        return False
    if project_id is None:
        return True
    s = store or MemoryStore.from_env()
    try:
        return await s.project_journal_enabled(project_id)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("journal: project flag lookup failed (%s); proceeding", exc)
        return True


async def journal_verdict(
    *,
    session_id: UUID,
    project_id: UUID | None,
    idea: str,
    verdict: str,
    scores: dict[str, Any] | None = None,
    sources_count: int = 0,
    tx_signature: str | None = None,
    journal: bool = True,
    store: MemoryStore | None = None,
) -> UUID | None:
    """Append a `verdict_received` entry. Best-effort."""
    if not await _is_enabled(journal=journal, project_id=project_id, store=store):
        return None
    value: dict[str, Any] = {
        "idea": idea,
        "verdict": verdict,
        "scores": scores or {},
        "sources_count": sources_count,
        "tx_signature": tx_signature,
    }
    try:
        return await save(
            _scope_for_session(session_id, project_id),
            MemoryEntryType.verdict_received,
            value,
            tx_signature=tx_signature,
        )
    except Exception as exc:  # pragma: no cover — best effort
        logger.warning("journal_verdict failed: %s", exc)
        return None


async def journal_scaffold(
    *,
    session_id: UUID,
    project_id: UUID | None,
    output_paths: list[str],
    total_tokens: int,
    cost_usd: float,
    journal: bool = True,
    store: MemoryStore | None = None,
) -> UUID | None:
    if not await _is_enabled(journal=journal, project_id=project_id, store=store):
        return None
    value: dict[str, Any] = {
        "session_id": str(session_id),
        "output_paths": list(output_paths),
        "total_tokens": int(total_tokens),
        "cost_usd": float(cost_usd),
    }
    try:
        return await save(
            _scope_for_session(session_id, project_id),
            MemoryEntryType.scaffold_generated,
            value,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("journal_scaffold failed: %s", exc)
        return None


async def journal_plan(
    *,
    session_id: UUID,
    project_id: UUID | None,
    voices: list[dict[str, Any]],
    tier_preset: str,
    total_cost_usd: float,
    journal: bool = True,
    store: MemoryStore | None = None,
) -> UUID | None:
    if not await _is_enabled(journal=journal, project_id=project_id, store=store):
        return None
    value: dict[str, Any] = {
        "session_id": str(session_id),
        "voices": voices,
        "tier_preset": tier_preset,
        "total_cost_usd": float(total_cost_usd),
    }
    try:
        return await save(
            _scope_for_session(session_id, project_id),
            MemoryEntryType.plan_advised,
            value,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("journal_plan failed: %s", exc)
        return None


async def journal_voice(
    *,
    session_id: UUID,
    project_id: UUID | None,
    role: str,
    closing_line: str,
    model_used: str,
    cost_usd: float,
    journal: bool = True,
    store: MemoryStore | None = None,
) -> UUID | None:
    if not await _is_enabled(journal=journal, project_id=project_id, store=store):
        return None
    value: dict[str, Any] = {
        "session_id": str(session_id),
        "role": role,
        "closing_line": closing_line,
        "model_used": model_used,
        "cost_usd": float(cost_usd),
    }
    try:
        return await save(
            _scope_for_session(session_id, project_id),
            MemoryEntryType.advisor_voiced,
            value,
            key=role,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("journal_voice failed: %s", exc)
        return None


async def journal_pulse(
    *,
    session_id: UUID,
    project_id: UUID | None,
    prior_panel_id: str | None,
    current_closing_lines: list[str],
    deltas: list[dict[str, Any]],
    journal: bool = True,
    store: MemoryStore | None = None,
) -> UUID | None:
    if not await _is_enabled(journal=journal, project_id=project_id, store=store):
        return None
    value: dict[str, Any] = {
        "session_id": str(session_id),
        "prior_panel_id": prior_panel_id,
        "current_closing_lines": list(current_closing_lines),
        "deltas": deltas,
    }
    try:
        return await save(
            _scope_for_session(session_id, project_id),
            MemoryEntryType.pulse_run,
            value,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("journal_pulse failed: %s", exc)
        return None


__all__ = [
    "journal_plan",
    "journal_pulse",
    "journal_scaffold",
    "journal_verdict",
    "journal_voice",
]
