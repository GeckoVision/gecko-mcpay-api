"""Risk controls — checks the runtime runs *before* dispatching an entry.

The risk module is intentionally a small pure function — ``would_breach``
returns a typed reason string ("max_concurrent", "max_single_position",
"daily_loss", "dissent_strength") or ``None`` if the candidate passes.
Callers journal the reason so users see *why* an entry was vetoed.
"""

from __future__ import annotations

from dataclasses import dataclass

from gecko_core.trade_agent.primitives.entry import EntryCandidate
from gecko_core.trade_agent.spec import RiskBlock


@dataclass
class RiskState:
    """Runtime-side risk snapshot. The runtime maintains this; we just
    consult it."""

    open_positions: int = 0
    bankroll_usd: float = 0.0
    daily_loss_pct: float = 0.0
    surviving_dissent_strength: float | None = None


def would_breach(
    spec_risk: RiskBlock,
    state: RiskState,
    candidate: EntryCandidate,
) -> str | None:
    """Return a breach reason or ``None`` if the candidate is safe."""
    if state.open_positions >= spec_risk.max_concurrent_positions:
        return "max_concurrent"

    if state.bankroll_usd > 0:
        pct = (candidate.nominal_size_usd / state.bankroll_usd) * 100
        if pct > spec_risk.max_single_position_pct:
            return "max_single_position"

    if state.daily_loss_pct >= spec_risk.max_daily_loss_pct:
        return "daily_loss"

    if (
        spec_risk.circuit_breaker_on_dissent_strength is not None
        and state.surviving_dissent_strength is not None
        and state.surviving_dissent_strength >= spec_risk.circuit_breaker_on_dissent_strength
    ):
        return "dissent_strength"

    return None


__all__ = ["RiskState", "would_breach"]
