"""Public models for the scaffold synthesizer."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel


class ScaffoldDocs(BaseModel):
    """JSON shape we ask gpt-4o to emit. Three full markdown documents.

    The synthesizer prompt enforces section structure, but we don't parse
    individual sections — we trust the prompt's contract and write each
    field as-is to disk. Pydantic just guarantees all three keys are
    present and non-empty strings.
    """

    prd_md: str
    business_plan_md: str
    building_md: str


class ScaffoldResult(BaseModel):
    """Return value of `generate_scaffold`.

    `paths` is the absolute paths of the three written files in canonical
    order (PRD, business plan, BUILDING). `tokens_used` and `cost_usd` are
    the synthesizer call's accounting — written so the CLI / MCP surface
    can show "free, debate already paid" but the API persistence layer
    can still attribute the cost to the session's LLM ledger if it wants.
    """

    paths: list[Path]
    session_id: UUID
    tokens_used: int
    cost_usd: float
    summary: str

    model_config = {"arbitrary_types_allowed": True}


class ScaffoldError(Exception):
    """Raised when scaffolding cannot proceed.

    Distinct subclasses model the user-actionable cases (kill verdict,
    missing session, malformed transcript) so the MCP / CLI surfaces can
    map them to clear error messages without parsing exception text.
    """


class KillVerdictError(ScaffoldError):
    """Refused: the debate's verdict was 'kill' — no value in scaffolding."""


class SessionNotFoundError(ScaffoldError):
    """The session_id doesn't exist or has been soft-deleted."""


class SessionNotReadyError(ScaffoldError):
    """The session exists but has no transcript / result yet (still running)."""


__all__ = [
    "KillVerdictError",
    "ScaffoldDocs",
    "ScaffoldError",
    "ScaffoldResult",
    "SessionNotFoundError",
    "SessionNotReadyError",
]
