"""Sprint review meta-tool (S7-DOGFOOD-01).

Reads `git log --since=<date>`, memory entries scoped to a project, and any
`docs/build-plan-sprint-*.md` files, then synthesizes a structured
``SprintReview`` (shipped bullets, weakest_link, proposed_next).

Free in stub mode (no LLM call — render git log + memory as a plain
non-AI summary). Live mode does ONE LLM call via the same router stack
that ``gecko_advise`` uses (per-role catalog lookup at the requested
tier_preset).

This is a **pure-Python** module: no Supabase, no x402. The MCP tool /
API / CLI layers wrap it with their own transport concerns.
"""

from __future__ import annotations

from gecko_core.review.builder import build_review
from gecko_core.review.models import SprintReview

__all__ = ["SprintReview", "build_review"]
