"""Pydantic schemas for the 7-agent trade-research panel.

The contract surface — Phase 8b's MCP tool + REST endpoint serialize these.
Field semantics are stable; adding optional fields is non-breaking, renaming
existing fields is. Keep the Literal sets aligned with the closing-line
patterns in :mod:`gecko_core.orchestration.trade_panel.personas`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Final-verdict tokens. Mirrors the coordinator's closing-line regex.
TradeVerdictLiteral = Literal["act", "pass", "defer"]


class TradePanelTurn(BaseModel):
    """A single agent's turn in the panel.

    ``parsed_verdict`` is the structured extraction from the closing line
    (e.g. ``{"trend_verdict": "bullish"}``). ``None`` means the agent did
    not emit a parseable closing line — surface as a soft failure rather
    than coercing a default, so callers can flag the run as degraded.
    """

    model_config = ConfigDict(extra="forbid")

    agent: str = Field(..., description="Persona name (matches REQUIRED_AGENTS).")
    content: str = Field(..., description="Full turn text the agent produced.")
    parsed_verdict: dict[str, Any] | None = Field(
        default=None,
        description="Structured extraction from the closing line, or None if unparsed.",
    )


class TradePanelVerdict(BaseModel):
    """Final aggregated verdict from the coordinator + per-turn audit trail."""

    model_config = ConfigDict(extra="forbid")

    verdict: TradeVerdictLiteral = Field(..., description="Final coordinator decision.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Coordinator-reported confidence in [0,1]."
    )
    key_drivers: list[str] = Field(
        default_factory=list,
        description="Short bullet drivers behind the verdict.",
    )
    dissent_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Count of voices pointing the OTHER way from the coordinator's verdict. "
            "Computed from parsed_verdict on each non-coordinator turn."
        ),
    )
    blocker_questions: list[str] = Field(
        default_factory=list,
        description="Open questions that would change the verdict if answered.",
    )
    turns: list[TradePanelTurn] = Field(
        default_factory=list,
        description="Full transcript in canonical agent order.",
    )


__all__ = [
    "TradePanelTurn",
    "TradePanelVerdict",
    "TradeVerdictLiteral",
]
