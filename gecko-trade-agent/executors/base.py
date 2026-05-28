"""Execution-adapter contract — venue-agnostic swap surface.

Defines the minimum surface every execution venue must expose for the
bot's decision loop to call it. Intentionally narrow: a swap request, a
swap result, a venue-name attribute. Venue-specific configuration
(API keys, RPC endpoints, slippage defaults) is the adapter's concern,
not the contract's.

The contract is asymmetric to ``OnchainOS.swap_execute()`` for one
reason: SendAI / Jupiter / Backpack all model swaps as a SwapAttempt
struct (the request) producing a SwapOutcome struct (the result),
which is cleaner than the positional-args style. OnchainOS adapters
translate at the boundary.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class SwapAttempt(BaseModel):
    """A swap request, venue-agnostic.

    Carries everything every adapter needs. Per-venue extras (priority
    fees, MEV protection, biz-type metadata) ride on ``venue_options``
    so the contract stays small.
    """

    model_config = ConfigDict(extra="forbid")

    from_token: str = Field(..., description="From-token mint or symbol.")
    to_token: str = Field(..., description="To-token mint or symbol.")
    readable_amount: str = Field(
        ...,
        description="Human-readable amount of from_token (e.g. '45' for 45 USDC).",
    )
    wallet: str = Field(..., description="Source wallet address.")
    slippage_bps: int | None = Field(
        default=None,
        ge=0,
        le=10_000,
        description="Max slippage in bps. None = adapter default.",
    )
    venue_options: dict[str, object] = Field(
        default_factory=dict,
        description="Venue-specific extras (mev_protection, priority_fee, etc).",
    )


class SwapOutcome(BaseModel):
    """The result of executing a SwapAttempt.

    Carries the on-chain settlement evidence (tx_hash + realized output
    amount) so the bot can compute PnL from real fills, not oracle
    prices. ``ok=False`` always carries a non-empty ``error``.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    venue: str = Field(..., description="Adapter name that produced this result.")
    tx_hash: str = ""
    error: str = ""
    from_token: str = ""
    to_token: str = ""
    readable_amount: str = ""
    # Realized output — populated when ok=True. Lets the bot compute
    # actual fill-based PnL instead of relying on oracle-derived estimates.
    to_amount_raw: str = "" """Minimal units (lamports/wei) of to_token received."""
    to_decimals: int = 0
    # Optional latency for adapter-level observability (each venue
    # measures differently — round-trip HTTP, on-chain confirmation, etc).
    elapsed_ms: int | None = None


@runtime_checkable
class ExecutionAdapter(Protocol):
    """Venue-agnostic swap surface every execution adapter implements.

    Structural-only Protocol — adapters don't inherit, they just expose
    ``venue_name`` (a str) and ``swap()`` (sync, takes SwapAttempt,
    returns SwapOutcome). Async variants can be added later as a parallel
    Protocol; v0.2 stays sync to match the bot's existing call shape.
    """

    venue_name: str

    def swap(self, attempt: SwapAttempt) -> SwapOutcome: ...


__all__ = [
    "ExecutionAdapter",
    "SwapAttempt",
    "SwapOutcome",
]
