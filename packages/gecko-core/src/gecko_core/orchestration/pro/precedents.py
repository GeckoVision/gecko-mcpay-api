"""Render Gecko Flywheel precedents into a debate-context block.

S2X-06 surfaces precedents to the 5 agents in the opening prompt. The block
is intentionally compact (one line per precedent) because the analyst is
already on a tight context budget and we just need the agents to *see* the
prior verdicts — they'll re-raise specifics if they matter.

The empty-state branch ("No prior precedents found.") is deliberate: an
empty corpus is itself signal — the agents should know they're evaluating a
category Gecko has not seen before. Rendering nothing would let the agents
silently treat the absence as "no constraint."
"""

from __future__ import annotations

from gecko_core.sessions.store import GeckoPrecedent

_BLOCK_HEADER = "Prior similar ideas Gecko evaluated:"
_EMPTY_LINE = "No prior precedents found."
_SUMMARY_CHAR_CAP = 240  # one line per precedent — truncate aggressively


def _one_line_summary(text: str) -> str:
    """Collapse multi-line summaries to a single line, capped to keep the block small."""
    flat = " ".join(text.split())
    if len(flat) > _SUMMARY_CHAR_CAP:
        return flat[: _SUMMARY_CHAR_CAP - 1].rstrip() + "…"
    return flat


def render_precedent_block(precedents: list[GeckoPrecedent]) -> str:
    """Return a compact bulleted block describing prior precedents.

    Output shape::

        Prior similar ideas Gecko evaluated:
        - [SHIP] short summary (sim=0.84)
        - [KILL] short summary (sim=0.81)

    Or, when ``precedents`` is empty::

        Prior similar ideas Gecko evaluated:
        - No prior precedents found.
    """
    lines: list[str] = [_BLOCK_HEADER]
    if not precedents:
        lines.append(f"- {_EMPTY_LINE}")
        return "\n".join(lines)

    for p in precedents:
        verdict_tag = p.verdict.upper()
        summary = _one_line_summary(p.idea_summary)
        sim = f" (sim={p.similarity:.2f})" if p.similarity is not None else ""
        lines.append(f"- [{verdict_tag}] {summary}{sim}")
    return "\n".join(lines)


__all__ = ["render_precedent_block"]
