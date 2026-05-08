"""Pydantic schemas for the trade-panel backtest (Phase 9 v1).

Stable contract surface — Phase 9.5's MCP / REST pass-through serializes
``BacktestReport`` directly. Fields here are additive: do not rename or
narrow types without a coordinated bump in the trade panel verdict shape.

Design notes
------------

``BacktestReport`` always returns — even when the simulator can't run.
The unbacktestable shape (``unbacktestable=True`` + ``reason``) is the
graceful-degradation contract: callers render "no historical context
available" rather than seeing an exception. This matches the founder's
"degrade gracefully" guardrail when Pyth Hermes turns out not to expose
historical data.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Granularity tokens for cached candles. Keep aligned with the Mongo
# ``protocol_price_history.granularity`` values; widening this Literal
# requires a paired write to ``storage.py`` AND the schema-drift comment
# in the Mongo collection contract.
BacktestGranularity = Literal["1h", "1d"]
BacktestSource = Literal["pyth", "coingecko", "fallback"]
TradeDirection = Literal["long", "short", "neutral"]


class Candle(BaseModel):
    """OHLCV row at a single ``ts`` for a protocol+granularity bucket."""

    model_config = ConfigDict(extra="forbid")

    protocol: str = Field(..., description="Protocol slug (lowercase, matches chunks.protocol).")
    ts: int = Field(..., description="Unix epoch seconds (UTC).")
    granularity: BacktestGranularity = Field(..., description="Candle granularity bucket.")
    source: BacktestSource = Field(..., description="Provenance of this candle.")
    open: float = Field(..., ge=0.0)
    high: float = Field(..., ge=0.0)
    low: float = Field(..., ge=0.0)
    close: float = Field(..., ge=0.0)
    vol_usd: float = Field(default=0.0, ge=0.0)


class BacktestIntent(BaseModel):
    """Normalized Strategist intent ready to replay against price history.

    Distinct from the free-form Strategist closing line: this is the
    structured view the simulator consumes. ``backtest_intent`` accepts a
    raw dict from the panel and coerces into this shape internally.
    """

    model_config = ConfigDict(extra="forbid")

    protocol: str = Field(..., description="Protocol slug (lowercase).")
    direction: TradeDirection = Field(..., description="Position direction.")
    horizon_days: int = Field(..., ge=1, le=365, description="Hold period in days.")
    size_pct: float = Field(
        default=1.0,
        ge=0.0,
        le=100.0,
        description="Position size as % of NAV (informational; v1 PnL is size-agnostic).",
    )
    stop_loss_pct: float | None = Field(
        default=None,
        description=(
            "Stop-loss as positive percent below entry for longs (above for shorts). "
            "None disables stop-loss simulation."
        ),
    )


class BacktestReport(BaseModel):
    """Realized-PnL replay of a Strategist intent against historical candles.

    Always-returnable: when the price corpus can't satisfy the intent, the
    report comes back with ``unbacktestable=True`` and a ``reason`` rather
    than the function raising. Callers branch on that flag to render a
    friendly "no historical context" panel instead of an error state.
    """

    model_config = ConfigDict(extra="forbid")

    pnl_pct: float = Field(
        default=0.0,
        description="Realized PnL as percent of entry (long convention; positive = profit).",
    )
    drawdown_pct: float = Field(
        default=0.0,
        ge=0.0,
        description="Worst peak-to-trough drawdown across the hold period (positive percent).",
    )
    n_similar_setups: int = Field(
        default=0,
        ge=0,
        description="Count of historical T0 windows replayed (informational; v1 = 1).",
    )
    hit_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of replayed setups with positive PnL (v1 = 0.0 or 1.0).",
    )
    source: BacktestSource = Field(
        default="pyth", description="Price-data provenance for this report."
    )
    unbacktestable: bool = Field(
        default=False,
        description="True when no replay was possible. Inspect ``reason`` for cause.",
    )
    reason: str | None = Field(
        default=None,
        description=(
            "Stable token explaining unbacktestable=True. Examples: "
            "'pyth_no_history', 'no_candles', 'unknown_protocol', 'invalid_intent'."
        ),
    )


__all__ = [
    "BacktestGranularity",
    "BacktestIntent",
    "BacktestReport",
    "BacktestSource",
    "Candle",
    "TradeDirection",
]
