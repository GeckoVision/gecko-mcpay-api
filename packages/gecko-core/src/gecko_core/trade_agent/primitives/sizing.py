"""Sizing primitives — convert (spec, bankroll, verdict) into USD size."""

from __future__ import annotations

from typing import Any

from gecko_core.trade_agent.spec import SizingBlock


def compute_size_usd(
    spec_sizing: SizingBlock,
    *,
    bankroll_usd: float,
    verdict: dict[str, Any] | None = None,
) -> float:
    """Return the USD size for the trade.

    Always non-negative; sizes capped at ``bankroll_usd`` so a misconfigured
    spec can't over-leverage on a single trade.
    """
    primitive = spec_sizing.primitive
    params = spec_sizing.params

    if primitive == "fixed_usd":
        size = float(params.get("amount_usd", 0))
    elif primitive == "percent_bankroll":
        pct = float(params.get("pct", 0))
        size = bankroll_usd * pct / 100
    elif primitive == "kelly_fraction":
        # v0.1: use confidence as the win prob proxy; AIML-2 owns the
        # full Kelly with edge estimation.
        confidence = float((verdict or {}).get("confidence", 0.5))
        fraction = float(params.get("fraction", 0.25))
        size = bankroll_usd * fraction * (2 * confidence - 1)
        size = max(0.0, size)
    elif primitive == "verdict_confidence_scaled":
        base = float(params.get("base_usd", 0))
        confidence = float((verdict or {}).get("confidence", 0.5))
        size = base * confidence
    else:
        size = 0.0

    return max(0.0, min(size, bankroll_usd))


__all__ = ["compute_size_usd"]
