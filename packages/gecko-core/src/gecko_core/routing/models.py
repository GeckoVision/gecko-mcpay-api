"""Public types for ``gecko_core.routing``."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RouteResult(BaseModel):
    """The outcome of a single ``route()`` call.

    Crosses MCP / CLI / API boundaries — the MCP tool JSON-serializes this
    directly, so renaming a field is a breaking change for skill consumers.
    """

    response: str
    model_used: str
    cost_usd: float = Field(ge=0.0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    savings_vs_premium: float = Field(ge=0.0)

    model_config = {"frozen": True}


__all__ = ["RouteResult"]
