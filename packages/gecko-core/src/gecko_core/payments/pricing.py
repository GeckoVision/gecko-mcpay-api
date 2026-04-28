"""Per-tier pricing.

PRD lists basic at $10-20 and pro at $50-100 per session. We pick the floor
of each band as the canonical V1 price; can be raised once we have signal.
"""

from __future__ import annotations

from decimal import Decimal

from gecko_core.models import Tier

_PRICES: dict[Tier, Decimal] = {
    "basic": Decimal("10.00"),
    "pro": Decimal("50.00"),
}


def price_for(tier: Tier) -> Decimal:
    """Return the USD price for a tier. Raises ValueError on unknown tier."""
    try:
        return _PRICES[tier]
    except KeyError as e:
        raise ValueError(f"unknown tier: {tier!r}") from e


__all__ = ["price_for"]
