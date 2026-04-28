"""Tests for the source dispatcher.

We use bespoke stub `Source` implementations rather than mocking — the
Protocol is small and stubs read clearer than `AsyncMock` chains.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from gecko_core.sources import Source, SourceResult, dispatch_sources


class _Stub:
    """Minimal Source impl. Intentionally not inheriting from Protocol —
    structural typing should pick it up."""

    def __init__(
        self,
        name: str,
        *,
        applies: bool = True,
        payload: dict[str, Any] | None = None,
        raises: BaseException | None = None,
        sleep: float = 0.0,
    ) -> None:
        self.name = name
        self._applies = applies
        self._payload = payload or {"name": name}
        self._raises = raises
        self._sleep = sleep
        self.fetch_called = False

    async def applies_to(self, *, categories: set[str]) -> bool:
        return self._applies

    async def fetch(self, *, idea: str, categories: set[str]) -> SourceResult:
        self.fetch_called = True
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._raises is not None:
            raise self._raises
        return SourceResult(source_name=self.name, payload=self._payload, cost_usd=0.01)


@pytest.mark.asyncio
async def test_dispatch_runs_all_sources_concurrently() -> None:
    a = _Stub("a", sleep=0.05)
    b = _Stub("b", sleep=0.05)
    c = _Stub("c", sleep=0.05)
    start = asyncio.get_event_loop().time()
    results = await dispatch_sources(
        idea="x", categories=set(), sources=[a, b, c], timeout_seconds=2.0
    )
    elapsed = asyncio.get_event_loop().time() - start
    assert set(results.keys()) == {"a", "b", "c"}
    assert all(r.fired for r in results.values())
    # If sequential, would be ~0.15s. Concurrent should be ~0.05s.
    assert elapsed < 0.12, f"sources ran sequentially (elapsed={elapsed:.3f}s)"


@pytest.mark.asyncio
async def test_per_source_failure_is_isolated() -> None:
    ok = _Stub("ok")
    boom = _Stub("boom", raises=RuntimeError("kaboom"))
    also_ok = _Stub("also_ok")
    results = await dispatch_sources(idea="x", categories=set(), sources=[ok, boom, also_ok])
    assert results["ok"].fired is True
    assert results["also_ok"].fired is True
    assert results["boom"].fired is False
    assert results["boom"].error is not None
    assert "RuntimeError" in results["boom"].error
    assert "kaboom" in results["boom"].error


@pytest.mark.asyncio
async def test_gated_source_returns_fired_false() -> None:
    gated = _Stub("gated", applies=False)
    fired = _Stub("fired")
    results = await dispatch_sources(idea="x", categories={"crypto"}, sources=[gated, fired])
    assert results["gated"].fired is False
    assert results["gated"].error is None
    assert gated.fetch_called is False
    assert results["fired"].fired is True


@pytest.mark.asyncio
async def test_timeout_fires_for_hung_source() -> None:
    fast = _Stub("fast")
    slow = _Stub("slow", sleep=2.0)
    results = await dispatch_sources(
        idea="x", categories=set(), sources=[fast, slow], timeout_seconds=0.1
    )
    assert results["fast"].fired is True
    assert results["slow"].fired is False
    assert results["slow"].error is not None
    assert "Timeout" in results["slow"].error


@pytest.mark.asyncio
async def test_results_keyed_on_source_name() -> None:
    a = _Stub("alpha", payload={"k": 1})
    b = _Stub("beta", payload={"k": 2})
    results = await dispatch_sources(idea="x", categories=set(), sources=[a, b])
    assert results["alpha"].payload == {"k": 1}
    assert results["beta"].payload == {"k": 2}


@pytest.mark.asyncio
async def test_empty_sources_returns_empty_dict() -> None:
    results = await dispatch_sources(idea="x", categories=set(), sources=[])
    assert results == {}


@pytest.mark.asyncio
async def test_applies_to_exception_is_isolated() -> None:
    """If a source's `applies_to` itself raises, it's still contained."""

    class _Bad:
        name = "bad"

        async def applies_to(self, *, categories: set[str]) -> bool:
            raise ValueError("can't decide")

        async def fetch(self, *, idea: str, categories: set[str]) -> SourceResult:
            raise AssertionError("fetch should not be called")

    ok = _Stub("ok")
    results = await dispatch_sources(idea="x", categories=set(), sources=[_Bad(), ok])
    assert results["bad"].fired is False
    assert "ValueError" in (results["bad"].error or "")
    assert results["ok"].fired is True


def test_source_protocol_is_runtime_checkable() -> None:
    s = _Stub("x")
    assert isinstance(s, Source)
