"""Judge-output dedup helper (FIX-02).

The judge LLM occasionally emits two complete scoring blocks (TAM / WEDGE /
V1_FEASIBILITY ... Final verdict: ...) inside a single turn reply, separated
by ``\\n\\n---\\n\\n`` or by a repeated ``Final verdict:`` marker. Observed in
production dogfood session ``3d26b165-90ba-4e17-8e50-db483abf6932`` (v0.2.12).

The duplication is *inside* one judge turn — the GroupChat driver only invokes
the judge agent once (see ``pro/__init__.py``), so the fix lives at the
summary-assembly layer rather than the orchestrator.

Policy: keep the LAST block (the model's most recent thought is canonical
under self-correction patterns). Log a structured WARN
``pro.judge.dedup_count`` with the count when more than one block is seen so
the AI/ML lane can track frequency for prompt-tuning later.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Either a horizontal-rule separator (the production-observed marker) or a
# repeated ``Final verdict:`` line — both indicate the model double-emitted
# its scoring block. We split on rules and on repeated final-verdict markers
# defensively.
_RULE_SPLIT = re.compile(r"\n\s*---+\s*\n")
_FINAL_VERDICT_RE = re.compile(r"^\s*Final verdict\s*:", re.IGNORECASE | re.MULTILINE)


def dedup_judge_summary(summary: str | None) -> str | None:
    """Return the canonical (last) judge block from ``summary``.

    Args:
        summary: raw judge-turn content (may contain duplicate blocks).

    Returns:
        ``None`` if ``summary`` is falsy; otherwise the LAST block when
        duplicates are detected, or the input unchanged.

    Side effect: emits ``logger.warning("pro.judge.dedup_count", extra={...})``
    when count > 1 so operators can track recurrence.
    """
    if not summary:
        return summary

    # First pass: split on horizontal rules.
    parts = [p for p in _RULE_SPLIT.split(summary) if p.strip()]

    # Second pass: if no rule split fired but we still see >1 ``Final verdict:``
    # marker, split on that boundary instead (keep it attached to the right
    # half so the last block stays well-formed).
    if len(parts) <= 1:
        verdict_markers = list(_FINAL_VERDICT_RE.finditer(summary))
        if len(verdict_markers) > 1:
            # Slice on every Final-verdict boundary except the first one,
            # so each block contains its own scoring + verdict line.
            cut_points = [m.start() for m in verdict_markers[1:]]
            sections: list[str] = []
            prev = 0
            for cp in cut_points:
                sections.append(summary[prev:cp])
                prev = cp
            sections.append(summary[prev:])
            parts = [s for s in sections if s.strip()]

    if len(parts) <= 1:
        return summary

    logger.warning(
        "pro.judge.dedup_count",
        extra={"event": "pro.judge.dedup_count", "count": len(parts)},
    )
    return parts[-1].strip()


__all__ = ["dedup_judge_summary"]
