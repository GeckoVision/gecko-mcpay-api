"""Routing decision matrix (S3-05, v1).

The matrix is data, not branches — pricing or model swaps are a single
dict edit, no code change.

Each task_hint maps to a (default_model, premium_model) pair. ``pick_model``
returns the requested column; ``candidate_models`` returns both as an
ordered preference list (preferred-first) so the budget cap can downshift.
"""

from __future__ import annotations

from typing import Final, Literal

from typing_extensions import TypedDict  # py<3.12 + pydantic needs this variant

TaskHint = Literal["reasoning", "code", "extraction", "summary", "default"]
DEFAULT_TASK_HINT: Final[TaskHint] = "default"


class _MatrixEntry(TypedDict):
    """One row of the routing matrix."""

    default: str
    premium: str


# v1 matrix — conservative, opinionated. Update when prices move or when a
# new model rotates into either column.
ROUTING_MATRIX: Final[dict[TaskHint, _MatrixEntry]] = {
    "reasoning": {"default": "gpt-4o", "premium": "claude-sonnet-4-6"},
    "code": {"default": "claude-sonnet-4-6", "premium": "claude-opus-4-7"},
    "extraction": {"default": "gpt-4o-mini", "premium": "gpt-4o"},
    "summary": {"default": "gpt-4o-mini", "premium": "gpt-4o"},
    "default": {"default": "gpt-4o-mini", "premium": "gpt-4o"},
}


def pick_model(*, task_hint: TaskHint, prefer_premium: bool) -> str:
    """Return the matrix-preferred model for ``(task_hint, prefer_premium)``."""
    entry = ROUTING_MATRIX[task_hint]
    return entry["premium"] if prefer_premium else entry["default"]


def candidate_models(*, task_hint: TaskHint, prefer_premium: bool) -> list[str]:
    """Ordered candidates: preferred first, then the alternative column.

    The budget enforcer in `route()` walks this list cheapest-first when the
    preferred choice exceeds the cap, so both columns must appear here.
    Deduped (some task_hints could legitimately share the same model in
    both columns in a future revision).
    """
    entry = ROUTING_MATRIX[task_hint]
    preferred = entry["premium"] if prefer_premium else entry["default"]
    alternative = entry["default"] if prefer_premium else entry["premium"]
    out = [preferred]
    if alternative != preferred:
        out.append(alternative)
    return out


__all__ = [
    "DEFAULT_TASK_HINT",
    "ROUTING_MATRIX",
    "TaskHint",
    "candidate_models",
    "pick_model",
]
