"""Bazaar source provider — catalog-led x402 buyer (Sprint 16 Track B).

The whole point of this package: **one generic adapter consumes whatever
the Bazaar catalog returns**. Vendor shims under ``adapters/`` are escape
hatches for response shapes that defeat the heuristic — never the
default path. See ``docs/build-plan-sprint-16-bazaar-consumer.md``
Track B reframe banner.
"""

from __future__ import annotations

from gecko_core.sources.bazaar.provider import (
    BazaarChunk,
    BazaarSourceProvider,
    make_bazaar_provider,
)

__all__ = [
    "BazaarChunk",
    "BazaarSourceProvider",
    "make_bazaar_provider",
]
