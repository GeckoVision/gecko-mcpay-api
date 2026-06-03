"""Shared strategy rules — consumed by BOTH the backtest harness and the live
runner (Pattern-C kill). See base.py for the contract.

    from strategies import load_strategy
    strat = load_strategy("trend_breakout")        # default spec
    sig = strat.should_enter(features)              # Signal | None
    exits = strat.exit_policy()                     # ExitPolicy
"""

from __future__ import annotations

from typing import cast

from .base import ExitPolicy, Signal, Strategy
from .legacy import JtoBreakoutLegacy
from .meanrev import MeanReversion
from .spec import StrategySpec
from .trend import TrendBreakout

_REGISTRY = {
    "trend_breakout": TrendBreakout,
    "mean_reversion": MeanReversion,
    "jto_breakout": JtoBreakoutLegacy,
}


def load_strategy(strategy_id: str, spec: StrategySpec | None = None) -> Strategy:
    """Resolve a strategy_id to a Strategy instance. If `spec` is given it wins
    (lets the backtest sweep override default thresholds); else the strategy's
    default_spec() is used."""
    key = (strategy_id or "jto_breakout").strip()
    cls = _REGISTRY.get(key)
    if cls is None:
        raise ValueError(f"unknown strategy_id: {strategy_id!r} (have {list(_REGISTRY)})")
    return cast(Strategy, cls(spec) if spec is not None else cls())


__all__ = [
    "ExitPolicy",
    "JtoBreakoutLegacy",
    "MeanReversion",
    "Signal",
    "Strategy",
    "StrategySpec",
    "TrendBreakout",
    "load_strategy",
]
