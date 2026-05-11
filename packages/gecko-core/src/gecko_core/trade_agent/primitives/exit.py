"""Exit primitives — v0.1 stubs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gecko_core.trade_agent.spec import ExitBlock
from gecko_core.trade_agent.state.models import AgentPosition


@dataclass
class ExitDecision:
    position_id: str
    reason: str


def evaluate_exit(
    spec_exit: ExitBlock,
    position: AgentPosition,
    event: dict[str, Any],
) -> ExitDecision | None:
    """Return an :class:`ExitDecision` if the open ``position`` should be
    closed given the current ``event``; else ``None``.
    """
    primitive = spec_exit.primitive
    params = spec_exit.params

    if primitive == "take_profit":
        target_pct = float(params.get("target_pct", 10))
        price = event.get("price")
        if price is None or position.entry_price is None:
            return None
        pnl_pct = (float(price) - position.entry_price) / position.entry_price * 100
        if pnl_pct >= target_pct:
            return ExitDecision(position.position_id, "take_profit")
        return None

    if primitive == "trailing_stop":
        trail_pct = float(params.get("trail_pct", 5))
        high = float(event.get("session_high", position.entry_price or 0))
        price = float(event.get("price", 0))
        if high > 0 and price < high * (1 - trail_pct / 100):
            return ExitDecision(position.position_id, "trailing_stop")
        return None

    if primitive == "time_based":
        max_hold_s = float(params.get("max_hold_s", 3600))
        held_s = float(event.get("position_age_s", 0))
        if held_s >= max_hold_s:
            return ExitDecision(position.position_id, "time_based")
        return None

    if primitive == "verdict_flip":
        if event.get("verdict_flipped"):
            return ExitDecision(position.position_id, "verdict_flip")
        return None

    if primitive == "drawdown_stop":
        stop_pct = float(params.get("stop_pct", 10))
        price = event.get("price")
        if price is None or position.entry_price is None:
            return None
        pnl_pct = (float(price) - position.entry_price) / position.entry_price * 100
        if pnl_pct <= -stop_pct:
            return ExitDecision(position.position_id, "drawdown_stop")
        return None

    return None


__all__ = ["ExitDecision", "evaluate_exit"]
