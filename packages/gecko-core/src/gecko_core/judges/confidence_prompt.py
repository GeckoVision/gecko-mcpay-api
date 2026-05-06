"""S20-C-CONFIDENCE-PROMPT-01 — synth-step confidence self-rating.

The synth model emits a per-section ``confidence`` (float in ``[0, 1]``)
along with a one-line ``rationale``. The score is the minimum of three
dimensions (EVIDENCE_FLOOR, DISSENT_QUALITY, CITATION_DENSITY) so
a section is only as confident as its weakest dimension.

The orchestrator aggregates per-section confidences via :func:`aggregate_confidence`
(document-level ``min``) and stamps the result onto :class:`ResearchResult.confidence`.

REACHABILITY (per CLAUDE.md feedback_wedge_reachability_check):
    confidence_prompt.CONFIDENCE_PROMPT_INSTRUCTION → basic._SYSTEM_PROMPT
        → basic.generate parses _LLMOutput.confidence/rationale per section
        → aggregate_confidence(per_section) → ResearchResult.confidence
        → workflows.research pro-tier passthrough (model_copy preserves
          base_result fields not in update dict — confidence rides through).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)


# Maximum length of the rationale string (chars). The prompt caps the
# model at 20 words; we cap at 200 chars on the parser side as a safety
# net (over-cap rationales are truncated, not rejected).
_RATIONALE_MAX_CHARS = 200


CONFIDENCE_PROMPT_INSTRUCTION: str = """
In addition to the per-section JSON above, return a top-level ``confidence``
(float in [0.0, 1.0]) and ``rationale`` (≤ 20 words). Score THREE dimensions
and return the MINIMUM of the three:

1. EVIDENCE_FLOOR — did you cite ≥3 distinct chunks from rag_context?
   - <2 chunks → 0.3
   - 2 chunks  → 0.6
   - 3+ chunks → 0.9

2. DISSENT_QUALITY — was the critic's strongest objection addressed in
   prose with a counter-citation?
   - Unaddressed   → 0.4
   - Hand-waved    → 0.6
   - Cited counter → 0.9

3. CITATION_DENSITY — ratio of claim-sentences with ``[N]`` markers to
   total claim-sentences.
   - <0.3   → 0.3
   - 0.3-0.6 → 0.6
   - >0.6   → 0.9

Return ``{"confidence": min(d1, d2, d3), "rationale": "<=20 words"}``.

Calibration anchors: 0.9 = dense base, multi-citation, addressed dissent;
0.3 = sparse base, live-fetch dominant, unaddressed dissent. Optionally
include the per-dimension scores under ``evidence_floor``,
``dissent_quality``, ``citation_density`` for telemetry.
""".strip()


class ConfidenceRating(BaseModel):
    """Parsed confidence self-rating from the synth model.

    Per-dimension scores are optional; when the model emits them they
    feed downstream telemetry (which dimension drove the floor). The
    aggregate ``confidence`` is the source of truth — by spec it is
    ``min(evidence_floor, dissent_quality, citation_density)``, but the
    parser does not re-compute it (the model is asked to do the min in
    prose; we trust the emitted scalar).
    """

    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=_RATIONALE_MAX_CHARS)
    evidence_floor: float | None = Field(default=None, ge=0.0, le=1.0)
    dissent_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_density: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("rationale", mode="before")
    @classmethod
    def _truncate_rationale(cls, v: object) -> object:
        """Truncate over-cap rationales rather than reject them.

        Same permissive boundary posture as PRD list coercion: a verbose
        rationale should not invalidate the entire confidence rating —
        the calibration value is the structural signal, the rationale is
        prose.
        """
        if isinstance(v, str) and len(v) > _RATIONALE_MAX_CHARS:
            logger.warning(
                "synth.confidence.rationale_truncated len=%d cap=%d",
                len(v),
                _RATIONALE_MAX_CHARS,
            )
            return v[: _RATIONALE_MAX_CHARS - 3] + "..."
        return v


def parse_confidence(model_output_json: dict[str, Any]) -> ConfidenceRating:
    """Parse the model's confidence dict into a validated rating.

    Raises :class:`pydantic.ValidationError` when ``confidence`` is missing
    or out of range — those are structural failures the caller should
    surface (vs. silent degradation, which would mask a prompt regression).
    """
    return ConfidenceRating.model_validate(model_output_json)


def aggregate_confidence(per_section: list[float]) -> float:
    """Document-level aggregate over per-section confidences.

    Per spec: returns the **min** of the per-section values (the document
    is only as confident as its weakest section). Empty list returns 0.0
    with a WARN log — caller passed no sections, which is degenerate.
    """
    if not per_section:
        logger.warning(
            "synth.confidence.aggregate.empty — no per-section confidences supplied; returning 0.0"
        )
        return 0.0
    return min(per_section)


__all__ = [
    "CONFIDENCE_PROMPT_INSTRUCTION",
    "ConfidenceRating",
    "aggregate_confidence",
    "parse_confidence",
]


# Re-export for callers that probe a ValidationError shape (e.g. tests).
_ValidationError = ValidationError
