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
    # The model the router chose pre-flight. Differs from `model_used` when an
    # OpenRouter cross-provider fallback fires (S4-ROUTE-03) — `model_used` is
    # whichever model actually answered.
    model_requested: str | None = None
    cost_usd: float = Field(ge=0.0)
    # OpenRouter-billed truth (S4-ROUTE-01). None when the upstream did not
    # return `usage.cost` (e.g. direct OpenAI API). The pre-flight gate uses
    # `cost_usd` (estimate); this field is the ground truth surfaced post-call.
    usage_cost_usd: float | None = None
    # OpenRouter `usage.cost_details.upstream_inference_cost` when present —
    # the underlying provider's billed rate, before OpenRouter's margin.
    upstream_cost_usd: float | None = None
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    savings_vs_premium: float = Field(ge=0.0)

    model_config = {"frozen": True}


__all__ = ["RouteResult"]
