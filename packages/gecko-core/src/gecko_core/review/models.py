"""Pydantic models for the sprint review meta-tool (S7-DOGFOOD-01)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SprintReview(BaseModel):
    """Structured output of ``build_review``.

    ``shipped`` is a list of one-line bullets describing what landed during
    the review window. ``weakest_link`` is a short string highlighting the
    one risk / gap most likely to bite next sprint. ``proposed_next`` is the
    three-bullet recommendation for the upcoming sprint.

    ``mode`` is ``"stub"`` (no LLM call) or ``"live"`` so callers can render
    the right disclaimer; the structured fields are populated either way.
    """

    project_id: str | None
    since_days: int
    shipped: list[str] = Field(default_factory=list)
    weakest_link: str = ""
    proposed_next: list[str] = Field(default_factory=list)
    mode: str = "stub"
    git_commits: list[str] = Field(default_factory=list)
    memory_entry_count: int = 0
    sprint_docs: list[str] = Field(default_factory=list)
    generated_at: datetime


__all__ = ["SprintReview"]
