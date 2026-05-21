"""Voice contract for the local-lab panel.

Locks the wire shape so ai-ml-engineer can ship voice modules
independently. The :class:`LocalVoice` protocol is a structural-only
contract — voices implement ``async def grade(...)`` and pass; no
inheritance required.

Why a contract here and not in ``local_panel``? Two reasons:

* ai-ml-engineer's voice modules import from this file. If the
  contract lived in ``local_panel.py`` it would create a circular
  dependency (panel imports voices imports panel).
* The JSON-extraction helper :func:`safe_parse_voice_json` is reused
  by every voice; it belongs with the voice contract, not with the
  panel coordinator.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Closed set per spec — voices that don't know what to say must return
# ``abstain`` with ``confidence=0.0`` rather than inventing a stance.
VoiceVerdict = Literal["bullish", "bearish", "neutral", "abstain"]


class VoiceOpinion(BaseModel):
    """One voice's response to one market snapshot.

    The contract is intentionally narrow:

    * ``verdict`` is the closed-set categorical signal the coordinator
      reads. Coordinator rules pin behaviour in code, not in any
      voice's prompt, per ``feedback-prompt-iteration-plateau``.
    * ``confidence`` is the only numeric the coordinator sees — kept
      bounded ``[0.0, 1.0]`` so a misbehaving voice can't dominate
      with an outlier value.
    * ``reasoning`` and ``observations`` are for the artifact log /
      post-hoc analysis only. Length-capped to keep memory rows
      compact (the JSONL has to fit in tail-readable shape).
    * ``raw_response`` is the model's full string — kept verbatim so
      JSON-parse failures can be re-analyzed offline.
    """

    voice_name: str
    verdict: VoiceVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=400)
    observations: list[str] = Field(default_factory=list, max_length=10)
    raw_response: str
    elapsed_ms: int
    cost_usd: float | None = None


@runtime_checkable
class LocalVoice(Protocol):
    """Structural protocol every voice implements.

    Async on purpose — voices fan out concurrently in
    :class:`local_panel.LocalPanel.run`. A voice that internally uses
    a sync HTTP client wraps it in ``asyncio.to_thread`` rather than
    making the protocol sync; the panel must be able to gather across
    voices.
    """

    voice_name: str

    async def grade(
        self,
        market_state: dict[str, Any],
        memory: MemoryReader,
    ) -> VoiceOpinion: ...


# We can't import LocalMemory here without creating an import cycle if
# the panel ever moves to this module. Re-export a structural Protocol
# the voices accept; the concrete LocalMemory satisfies it by accident.
class MemoryReader(Protocol):
    """Subset of LocalMemory voices are allowed to read.

    Voices can read prior decisions / outcomes for context but must
    NOT append — appends are reserved to the panel coordinator so the
    artifact log has one writer. Encoded as a Protocol because the
    concrete LocalMemory already exposes these methods; voices that
    accept ``MemoryReader`` work transparently.
    """

    def recent(
        self,
        event_filter: str | tuple[str, ...] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def outcomes_for(self, decision_id: str) -> list[dict[str, Any]]: ...


# Matches both ```json ... ``` and bare ``` ... ``` fences. Non-greedy
# so a response with multiple fenced blocks picks the first one.
_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def safe_parse_voice_json(raw: str, voice_name: str) -> dict[str, Any] | None:
    """Extract a JSON object from an LLM response.

    Handles three common shapes:

    1. Bare JSON object (the model honored ``response_format``).
    2. JSON wrapped in a markdown fence (``\\`\\`\\`json ... \\`\\`\\``` or
       ``\\`\\`\\` ... \\`\\`\\```).
    3. JSON embedded in prose — we extract the first balanced ``{...}``
       substring as a last resort.

    Returns ``None`` on parse failure (caller turns this into an
    ``abstain`` opinion so the panel never blocks on one voice's
    formatting glitch).
    """
    if not isinstance(raw, str) or not raw.strip():
        return None

    text = raw.strip()

    # 1) Try as-is.
    parsed = _try_parse_object(text)
    if parsed is not None:
        return parsed

    # 2) Try unwrapping a markdown fence.
    match = _FENCE_PATTERN.search(text)
    if match:
        inner = match.group(1).strip()
        parsed = _try_parse_object(inner)
        if parsed is not None:
            return parsed

    # 3) Last-resort: find the first balanced object.
    candidate = _extract_balanced_object(text)
    if candidate is not None:
        parsed = _try_parse_object(candidate)
        if parsed is not None:
            return parsed

    logger.warning("voice %s: could not parse JSON from response (%d chars)", voice_name, len(text))
    return None


def _try_parse_object(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _extract_balanced_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` substring, or None.

    Naive bracket counter — does not parse strings, so a brace inside
    a JSON string literal could throw it off. Acceptable for our
    voices: the LLM is asked for object-only responses, and we already
    tried bare-parse + fence-parse above.
    """
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : i + 1]
    return None


__all__ = [
    "LocalVoice",
    "MemoryReader",
    "VoiceOpinion",
    "VoiceVerdict",
    "safe_parse_voice_json",
]
