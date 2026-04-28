"""Source dispatcher.

Every external signal source (Colosseum, HN, Reddit, twit.sh, GitHub, the
flywheel, etc.) implements `Source`. `dispatch_sources` runs all enabled
sources concurrently for a given idea and returns a uniform dict of results.

Per-source failures are *swallowed* on purpose: a flaky third-party API must
never take down the whole research session. Failed sources surface as
`SourceResult(fired=False, error=...)` so the orchestrator can choose
whether to mention them in the final brief.
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


__all__ = ["Source", "SourceResult", "dispatch_sources"]
