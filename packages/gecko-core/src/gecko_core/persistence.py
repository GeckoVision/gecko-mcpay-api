"""Persistence façade for content-addressed verdict lookup.

Verdicts are content-addressed by ``verdict_hash`` (sha256 over idea +
sources + structural verdict shape — see
``gecko_core.verdict_hash``). The full ``ResearchResult`` JSON lives on
the Supabase ``sessions.result_json`` column; the
``judge_transcripts`` Mongo collection carries the verdict-hash index
plus the canonical idea text.

This module joins the two:

  1. Look up the most-recent ``judge_transcripts`` doc for the hash.
  2. Take the ``session_id`` from that doc.
  3. Read the full ``result_json`` from Supabase.
  4. Validate into ``ResearchResult``.

When step 3 is unreachable (Supabase row absent / out of sync), a
``VerdictNotFoundError`` fires so the CLI surface can render a clean
"verdict not persisted" message rather than crashing.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from gecko_core.models import ResearchResult
from gecko_core.orchestration.transcripts import load_by_verdict_hash
from gecko_core.sessions.store import SessionStore

logger = logging.getLogger(__name__)


class VerdictNotFoundError(Exception):
    """The verdict_hash does not resolve to a stored ResearchResult."""


async def load_by_verdict_hash_async(
    short_or_full_hash: str,
    *,
    store: SessionStore | None = None,
) -> tuple[ResearchResult, str]:
    """Resolve ``short_or_full_hash`` to a ``(ResearchResult, idea)`` pair.

    The idea text is returned alongside the result because verdict-hash
    inputs require it (see ``gecko_core.verdict_hash.verdict_hash``)
    and the CLI footer surfaces ``verdict@<hash>`` so consumers expect
    to render with the original prompt in scope.
    """
    doc = load_by_verdict_hash(short_or_full_hash)
    if doc is None:
        raise VerdictNotFoundError(
            f"No verdict found for {short_or_full_hash!r}. "
            "Ensure the hash is from a recent run captured in judge_transcripts."
        )

    session_id_raw = doc.get("session_id")
    idea_text = str(doc.get("idea_text") or "")
    if not session_id_raw:
        raise VerdictNotFoundError(
            f"verdict_hash {short_or_full_hash!r} has no session_id; "
            "cannot reconstruct ResearchResult."
        )

    try:
        session_id = UUID(str(session_id_raw))
    except (TypeError, ValueError) as exc:
        raise VerdictNotFoundError(
            f"verdict_hash {short_or_full_hash!r} carries malformed session_id"
        ) from exc

    s = store or SessionStore.from_env()
    raw = await s.get_result(session_id)
    if raw is None:
        raise VerdictNotFoundError(
            f"Session {session_id} has no persisted result; the run may "
            "have been captured in transcripts but not yet written to "
            "Supabase, or the row was GC'd."
        )

    try:
        result = ResearchResult.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError
        raise VerdictNotFoundError(
            f"Persisted result for session {session_id} failed validation: {exc}"
        ) from exc

    return result, idea_text


async def update_result_payload(
    session_id: UUID,
    payload: dict[str, Any],
    *,
    store: SessionStore | None = None,
) -> None:
    """Write ``payload`` (a model_dumped ResearchResult) back to Supabase.

    Thin wrapper over ``SessionStore.set_result`` so refine /
    competitors_landscape can persist their additions through the same
    seam tests already mock.
    """
    s = store or SessionStore.from_env()
    await s.set_result(session_id, payload)


__all__ = [
    "VerdictNotFoundError",
    "load_by_verdict_hash_async",
    "update_result_payload",
]
