"""Pydantic models for the backtest harness wire shapes.

These are the *output* shapes of ``gecko_backtest()`` — what the CLI
renders, what tests assert against, and what would be persisted to a
``backtest_runs`` collection if we ever durable-store replay results.

Per CLAUDE.md Pattern A, the gating literal lives here as the single
source of truth so the harness, the CLI bridge, and tests all import
from one place.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GatingMode = Literal["on", "off", "both"]
RunGating = Literal["on", "off"]
Side = Literal["long", "short"]


class Trade(BaseModel):
    """One round-trip — entry to exit. Pure data."""

    model_config = ConfigDict(extra="forbid")

    entry_ts: float
    exit_ts: float
    entry_price: float
    exit_price: float
    size: float
    side: Side = "long"
    verdict_id: str | None = None
    pnl: float


class BacktestRun(BaseModel):
    """One replay arm — gated or ungated. All numbers reproducible."""

    model_config = ConfigDict(extra="forbid")

    gating_mode: RunGating
    sharpe: float
    max_dd_pct: float
    pnl_pct: float
    hit_rate: float
    n_trades: int
    equity_curve: list[float] = Field(default_factory=list)
    trades: list[Trade] = Field(default_factory=list)


class BacktestResult(BaseModel):
    """The full output of a ``gecko_backtest()`` call.

    ``delta_pnl_pct`` and ``delta_sharpe`` are defined as
    ``gated - ungated``; positive numbers mean gating won. These are the
    "verdict-gated trades that beat baseline by >=+200 bps median"
    numbers from the co-founder brief Section 1.7.
    """

    model_config = ConfigDict(extra="forbid")

    gated: BacktestRun | None = None
    ungated: BacktestRun | None = None
    delta_pnl_pct: float = 0.0
    delta_sharpe: float = 0.0
    verdict_call_count: int = 0
    cache_hit_rate: float = 0.0
    window_days: int = 0
    spec_id: str = ""


__all__ = [
    "BacktestResult",
    "BacktestRun",
    "GatingMode",
    "RunGating",
    "Side",
    "Trade",
]
