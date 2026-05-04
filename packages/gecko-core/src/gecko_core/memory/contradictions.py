"""Contradiction detection over the memory layer (S5-MEM-06).

Flags when an incoming entry semantically conflicts with a prior entry in
the same scope. Two-stage check:

1. Cosine similarity: ≥ ``threshold`` (default 0.78) signals "talking
   about the same thing".
2. Type-aware conflict rule:
   - ``verdict_received`` ↔ ``verdict_received``: differing verdict labels
     (ship vs kill) → contradiction.
   - ``plan_advised`` / ``advisor_voiced``: closing-line text → second LLM
     pass (gpt-4o-mini, json_object) decides whether priorities conflict.

Surfaces a ``Contradiction`` payload (informational, never blocking — kill
verdicts must always journal).
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast
from uuid import UUID

from openai import AsyncOpenAI
from pydantic import BaseModel

from gecko_core.llm_helpers import supports_strict_outputs
from gecko_core.memory.embedder import embed_text, render_value_for_embedding
from gecko_core.memory.models import MemoryEntry, MemoryEntryType, MemoryScope
from gecko_core.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class Contradiction(BaseModel):
    """One contradiction surfacing on an auto-journal hook."""

    incoming_entry_id: UUID
    contradicting_entry_id: UUID
    similarity: float
    reason: str
    can_proceed: bool


# Type families that can sensibly contradict each other. Search restricts
# the prior-entry pool to these compatible types so a `pulse_run` doesn't
# spuriously contradict a `verdict_received` from last week.
_COMPATIBLE_TYPES: dict[MemoryEntryType, set[MemoryEntryType]] = {
    MemoryEntryType.verdict_received: {MemoryEntryType.verdict_received},
    MemoryEntryType.plan_advised: {
        MemoryEntryType.plan_advised,
        MemoryEntryType.advisor_voiced,
    },
    MemoryEntryType.advisor_voiced: {
        MemoryEntryType.plan_advised,
        MemoryEntryType.advisor_voiced,
    },
    MemoryEntryType.pulse_run: {MemoryEntryType.pulse_run, MemoryEntryType.plan_advised},
}


_LLM_SYSTEM = (
    "You compare two advisor priorities. Respond with a JSON object: "
    '{"contradicts": bool, "reason": "<one-sentence explanation>"}. '
    "Set contradicts=true when the priorities push in opposite directions "
    "(e.g. one says 'lock the LOI' and the other says 'pivot to a "
    "different segment'); false when they're complementary or just "
    "different facets of the same plan."
)


async def _llm_judges_conflict(
    *,
    client: AsyncOpenAI,
    incoming_text: str,
    prior_text: str,
    model: str = "gpt-4o-mini",
    router: str = "openai",
) -> tuple[bool, str]:
    """Second-pass semantic conflict check. Returns (contradicts, reason).

    LLM-hygiene Commit D: when the (model, router) supports OpenAI
    Structured Outputs strict mode, render the inline contradicts/reason
    schema directly (no Pydantic class for a 2-field shape — flat
    json_schema is shorter than declaring a model). Otherwise fall back
    to ``json_object`` and rely on the existing ``json.loads`` + key
    coercion below.
    """
    user = (
        f"Prior priority:\n{prior_text}\n\nIncoming priority:\n{incoming_text}\n\nOutput JSON only."
    )
    if supports_strict_outputs(model, router):
        response_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": "ContradictionVerdict",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "contradicts": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["contradicts", "reason"],
                },
                "strict": True,
            },
        }
    else:
        response_format = {"type": "json_object"}
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user", "content": user},
        ],
        response_format=cast(Any, response_format),
        temperature=0.0,
        seed=42,
    )
    content = resp.choices[0].message.content or "{}"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False, "llm_invalid_json"
    contradicts = bool(payload.get("contradicts", False))
    reason = str(payload.get("reason", "")).strip() or "no reason given"
    return contradicts, reason


def _verdict_label(value: dict[str, Any]) -> str | None:
    v = value.get("verdict")
    if isinstance(v, str):
        return v.strip().lower()
    return None


def _closing_summary(value: dict[str, Any]) -> str:
    """Pick a textual surface for LLM comparison."""
    if "closing_line" in value:
        return str(value.get("closing_line") or "")
    voices = value.get("voices")
    if isinstance(voices, list):
        parts: list[str] = []
        for v in voices:
            if isinstance(v, dict):
                role = str(v.get("role") or "?")
                line = str(v.get("closing_line") or "")
                if line:
                    parts.append(f"{role}: {line}")
        return "\n".join(parts)
    if "current_closing_lines" in value:
        lines = value.get("current_closing_lines") or []
        if isinstance(lines, list):
            return "\n".join(str(x) for x in lines)
    return json.dumps(value, sort_keys=True, default=str)[:800]


async def check(
    scope: MemoryScope,
    incoming_entry: MemoryEntry,
    *,
    threshold: float = 0.78,
    store: MemoryStore | None = None,
    openai_client: AsyncOpenAI | None = None,
) -> Contradiction | None:
    """Look for a prior entry in the same scope that contradicts the incoming one.

    Returns the strongest contradiction (highest similarity with semantic
    conflict), or ``None`` if no conflict is found.
    """
    store = store or MemoryStore.from_env()

    compatible = _COMPATIBLE_TYPES.get(incoming_entry.entry_type)
    if compatible is None:
        return None

    # 1. Embed the incoming entry's value if not already done.
    text = render_value_for_embedding(
        incoming_entry.entry_type.value, incoming_entry.value, key=incoming_entry.key
    )
    embedding = incoming_entry.embedding or await embed_text(text)

    # 2. Cosine top-k within scope. Threshold pre-filtered server-side.
    matches = await store.search(
        scope=scope,
        query_embedding=embedding,
        top_k=10,
        similarity_threshold=threshold,
    )

    candidates: list[tuple[MemoryEntry, float]] = [
        (m, sim) for m, sim in matches if m.id != incoming_entry.id and m.entry_type in compatible
    ]
    if not candidates:
        return None

    # 3. Type-aware conflict resolution.
    incoming_text = _closing_summary(incoming_entry.value)

    best: Contradiction | None = None
    for prior, sim in candidates:
        if incoming_entry.entry_type == MemoryEntryType.verdict_received:
            v_in = _verdict_label(incoming_entry.value)
            v_pr = _verdict_label(prior.value)
            if v_in and v_pr and v_in != v_pr:
                cand = Contradiction(
                    incoming_entry_id=incoming_entry.id,
                    contradicting_entry_id=prior.id,
                    similarity=sim,
                    reason=f"prior verdict {v_pr.upper()} differs from incoming {v_in.upper()}",
                    can_proceed=True,
                )
                if best is None or cand.similarity > best.similarity:
                    best = cand
            continue

        # plan_advised / advisor_voiced / pulse_run — LLM second pass.
        if openai_client is None:
            from gecko_core.orchestration.settings import get_orchestration_settings

            orch = get_orchestration_settings()
            openai_client = AsyncOpenAI(api_key=orch.llm_api_key, base_url=orch.llm_endpoint)

        prior_text = _closing_summary(prior.value)
        try:
            contradicts, reason = await _llm_judges_conflict(
                client=openai_client,
                incoming_text=incoming_text,
                prior_text=prior_text,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("contradiction LLM check failed: %s", exc)
            continue
        if contradicts:
            cand = Contradiction(
                incoming_entry_id=incoming_entry.id,
                contradicting_entry_id=prior.id,
                similarity=sim,
                reason=reason,
                can_proceed=True,
            )
            if best is None or cand.similarity > best.similarity:
                best = cand

    return best


def render_banner(contradiction: Contradiction, prior: MemoryEntry) -> str:
    """Render the user-facing banner shown by MCP / CLI surfaces."""
    when = prior.created_at.strftime("%Y-%m-%d")
    label = ""
    if prior.entry_type == MemoryEntryType.verdict_received:
        v = _verdict_label(prior.value) or "?"
        idea = str(prior.value.get("idea") or "")[:80]
        label = f"{v.upper()} — {idea!r}"
    else:
        label = _closing_summary(prior.value)[:120]
    return (
        "Contradicts a prior decision.\n"
        f"{when}: {label}\n"
        f"Similarity: {contradiction.similarity:.2f}. {contradiction.reason}"
    )


__all__ = ["Contradiction", "check", "render_banner"]
