"""BazaarAdapter Protocol + registry of resource_type → adapter.

The default is ``GenericBazaarAdapter`` — it consumes any JSON or text
response shape via heuristics. Vendor shims register here only when a
response defeats the heuristic. **The catalog-led principle is that
shims are escape hatches, not the architectural default.**
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from gecko_core.payments.bazaar_discovery import BazaarResource
from gecko_core.payments.x402_consumer import X402Consumer
from gecko_core.sources.bazaar.types import BazaarChunk


@runtime_checkable
class BazaarAdapter(Protocol):
    """Pluggable response normalizer for a discovered Bazaar resource.

    ``applies_to`` returns True when the adapter handles a given
    resource (the registry queries adapters in priority order; first
    True wins). ``GenericBazaarAdapter.applies_to`` always returns True
    and registers last so it functions as the fallback.
    """

    name: str

    def applies_to(self, resource: BazaarResource) -> bool: ...

    async def fetch_and_normalize(
        self,
        resource: BazaarResource,
        x402_consumer: X402Consumer,
        *,
        max_usd: Decimal,
    ) -> list[BazaarChunk]: ...


__all__ = ["BazaarAdapter", "BazaarChunk"]
