"""Source dispatcher.

Every external signal source (Colosseum, HN, Reddit, twit.sh, GitHub, the
flywheel, etc.) implements `Source`. `dispatch_sources` runs all enabled
sources concurrently for a given idea and returns a uniform dict of results.

Per-source failures are *swallowed* on purpose: a flaky third-party API must
never take down the whole research session. Failed sources surface as
`SourceResult(fired=False, error=...)` so the orchestrator can choose
whether to mention them in the final brief.

This module also exposes a lightweight catalog registry
(`register_source`, `available_sources`) so the MCP / CLI surfaces can
introspect which signal providers Gecko knows about without hard-coding the
list at every call site. The registry is populated as a side effect of
importing the concrete source modules.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SourceResult:
    """Uniform return type from every source.

    `payload` is source-specific and persisted on ResearchResult. `cost_usd`
    is rolled up into the per-session economics view. `fired=False` means
    the source either was gated out by `applies_to` or failed; either way
    it shouldn't count toward "sources used" in the brief.
    """

    source_name: str
    payload: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    fired: bool = True
    error: str | None = None


@runtime_checkable
class Source(Protocol):
    """Every source implements this minimal contract."""

    name: str

    async def applies_to(self, *, categories: set[str]) -> bool:
        """Whether this source should fire for an idea in `categories`."""
        ...

    async def fetch(self, *, idea: str, categories: set[str]) -> SourceResult:
        """Fetch the source's data for this idea.

        Implementations must catch their own exceptions and return a
        `SourceResult(fired=False, error=...)` rather than raising. The
        dispatcher will *also* catch anything that escapes, but the source
        knows its own context better and can produce a useful error string.
        """
        ...


@dataclass(frozen=True)
class SourceCatalogEntry:
    """Static metadata describing a source Gecko can query.

    Distinct from `SourceResult` (per-call output) and `Source` (a runtime
    instance). This is what the introspection surfaces (`gecko sources
    --catalog`, `gecko_available_sources` MCP tool) render.
    """

    name: str
    description: str
    gating: str
    cost_per_call: str


# Module-level catalog. Populated via `register_source` from each concrete
# source module's import side-effect. We deliberately keep this a plain list
# (rather than a dict) so the registration order is preserved for stable
# rendering — the catalog is small enough that linear lookup doesn't matter.
_SOURCE_CATALOG: list[SourceCatalogEntry] = []


def register_source(entry: SourceCatalogEntry) -> SourceCatalogEntry:
    """Register a source's static metadata. Idempotent on `name`.

    Concrete source modules call this at import time. Re-registration with
    the same name silently replaces the prior entry — supports dev reloads
    and tests that import source modules multiple times.
    """
    global _SOURCE_CATALOG
    _SOURCE_CATALOG = [e for e in _SOURCE_CATALOG if e.name != entry.name]
    _SOURCE_CATALOG.append(entry)
    return entry


def available_sources() -> list[SourceCatalogEntry]:
    """All registered source catalog entries.

    Triggers an import of the concrete source modules so the registry is
    populated even when callers haven't imported them themselves. Returns a
    copy so callers can't mutate the canonical list.
    """
    # Import for side-effects: each module calls `register_source`. Done
    # lazily here to avoid a circular import at package init time.
    from gecko_core.sources import _catalog as _catalog

    return list(_SOURCE_CATALOG)


async def dispatch_sources(
    *,
    idea: str,
    categories: set[str],
    sources: list[Source],
    timeout_seconds: float = 30.0,
) -> dict[str, SourceResult]:
    """Run all `sources` whose `.applies_to()` returns True, concurrently.

    Returns a dict keyed on `source.name`, including gated-out and failed
    sources (so callers can introspect *why* a source didn't contribute).
    """

    async def _run_one(s: Source) -> SourceResult:
        try:
            if not await s.applies_to(categories=categories):
                return SourceResult(source_name=s.name, payload={}, fired=False)
            return await asyncio.wait_for(
                s.fetch(idea=idea, categories=categories),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return SourceResult(
                source_name=s.name,
                payload={},
                fired=False,
                error=f"TimeoutError: exceeded {timeout_seconds}s",
            )
        except Exception as e:
            return SourceResult(
                source_name=s.name,
                payload={},
                fired=False,
                error=f"{type(e).__name__}: {e}",
            )

    results = await asyncio.gather(*(_run_one(s) for s in sources))
    return {r.source_name: r for r in results}


__all__ = [
    "Source",
    "SourceCatalogEntry",
    "SourceResult",
    "available_sources",
    "dispatch_sources",
    "register_source",
]
