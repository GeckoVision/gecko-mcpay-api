"""Shared types for the bazaar source provider package.

Lives in its own leaf module so adapters and the provider can both import
``BazaarChunk`` without setting up a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class BazaarChunk:
    """A unit of evidence emitted by a Bazaar resource fetch.

    Distinct from ``gecko_core.ingestion.providers.SourceChunk``: this is
    the immediate output of an adapter's normalization pass and carries
    the per-chunk cost share + provenance back to ``BazaarSourceProvider``,
    which then maps it onto whatever the dispatcher expects.
    """

    text: str
    provider_kind: str  # "bazaar:<resource_type>"
    cost_usd: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)
    creator_handle: str | None = None


__all__ = ["BazaarChunk"]
