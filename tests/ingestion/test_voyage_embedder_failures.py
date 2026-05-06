"""S19-VOYAGE-EMBEDDER-FAILURE-TESTS-01 — pin loud-crash behavior.

Mongo's chunks_vector index is locked at 1024-dim Voyage. A naive OpenAI
fallback (1536-dim) would silently corrupt inserts, so the embedder is
expected to crash loudly on every Voyage failure mode rather than degrade.
These tests pin that policy with VCR-style fixture exceptions so future
fallback experiments can't silently regress it.

Pattern C from CLAUDE.md (recorded-fixture contract tests applied to
wire-protocol integrations).
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest
from gecko_core.ingestion.embedder import _embed_voyage, embed


class _VoyageHTTPError(Exception):
    """Stand-in for the SDK's status-bearing exception class."""

    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"voyage error status={status_code}")
        self.status_code = status_code


class _RaisingClient:
    """Async client that raises a configured exception on every embed() call."""

    def __init__(self, exc_factory: Any, **_: Any) -> None:
        self.exc_factory = exc_factory
        self.call_count = 0

    async def embed(self, **_: Any) -> Any:
        self.call_count += 1
        raise self.exc_factory()


def _install_fake_voyageai(
    monkeypatch: pytest.MonkeyPatch, exc_factory: Any
) -> dict[str, _RaisingClient]:
    """Inject a fake voyageai module whose AsyncClient raises on embed()."""
    holder: dict[str, _RaisingClient] = {}

    class _FakeModule:
        def AsyncClient(self, *, api_key: str) -> _RaisingClient:
            client = _RaisingClient(exc_factory, api_key=api_key)
            holder["client"] = client
            return client

    monkeypatch.setitem(sys.modules, "voyageai", _FakeModule())
    return holder


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep with a no-op that records each backoff request."""
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return sleeps


@pytest.mark.asyncio
async def test_missing_voyage_api_key_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test A: VOYAGE_API_KEY unset + EMBED_PROVIDER=voyage → loud ValueError.

    The dispatcher in `embed()` (embedder.py:343-347) is the load-bearing
    guard; this test pins it. We override `get_ingestion_settings` directly
    rather than poking env vars because pydantic-settings reads `.env` and
    the dev shell typically has VOYAGE_API_KEY populated there.
    """
    from gecko_core.ingestion import settings as settings_module

    fake_settings = settings_module.IngestionSettings.model_construct(
        openai_api_key=None,
        tavily_api_key=None,
        embed_model="voyage-3",
        embed_provider="voyage",
        voyage_api_key=None,
        deepgram_api_key=None,
        deepgram_max_audio_minutes=30,
    )
    monkeypatch.setattr(settings_module, "get_ingestion_settings", lambda: fake_settings)
    # embedder imports the symbol directly — patch there too.
    from gecko_core.ingestion import embedder as embedder_module

    monkeypatch.setattr(embedder_module, "get_ingestion_settings", lambda: fake_settings)

    with pytest.raises(ValueError, match="VOYAGE_API_KEY"):
        await embed(["hello"])


@pytest.mark.asyncio
async def test_500_error_raises_immediately_no_retry(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    """Test B: 500 status raises after exactly 1 call.

    The retry guard at embedder.py:255 (`status in (429, None)`) excludes
    5xx — by design. Any silent retry would mask Voyage outages and burn
    quota on a broken endpoint.
    """
    holder = _install_fake_voyageai(
        monkeypatch, lambda: _VoyageHTTPError(500, "internal server error")
    )

    with pytest.raises(_VoyageHTTPError) as exc_info:
        await _embed_voyage(["hello"], api_key="pa-test", model="voyage-3")

    assert exc_info.value.status_code == 500
    assert holder["client"].call_count == 1
    # No backoff sleeps — non-retried path doesn't sleep.
    assert no_sleep == []


@pytest.mark.asyncio
async def test_429_exhausted_raises_after_three_attempts(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    """Test C: 3× 429 → raises after exactly 3 calls; 2 backoff sleeps issued.

    Loop in embedder.py:247-265 caps at attempt=3. After the 2nd 429 we
    sleep + retry; on the 3rd 429 the `attempt < 3` guard is false and
    we re-raise.
    """
    holder = _install_fake_voyageai(monkeypatch, lambda: _VoyageHTTPError(429, "rate limited"))

    with pytest.raises(_VoyageHTTPError) as exc_info:
        await _embed_voyage(["hello"], api_key="pa-test", model="voyage-3")

    assert exc_info.value.status_code == 429
    assert holder["client"].call_count == 3
    # 2 backoff sleeps (after attempts 1 and 2; attempt 3 raises without sleeping).
    assert len(no_sleep) == 2
    # Backoff comes from full-jitter draws; both must be non-negative finite.
    assert all(s >= 0 for s in no_sleep)


@pytest.mark.asyncio
async def test_401_auth_error_raises_immediately(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    """Test D: 401 status raises after exactly 1 call.

    Auth failures are not retryable — burning 3 attempts on a revoked key
    just delays the operator's signal. The retry guard correctly excludes
    everything except 429 / unknown.
    """
    holder = _install_fake_voyageai(monkeypatch, lambda: _VoyageHTTPError(401, "unauthorized"))

    with pytest.raises(_VoyageHTTPError) as exc_info:
        await _embed_voyage(["hello"], api_key="pa-test", model="voyage-3")

    assert exc_info.value.status_code == 401
    assert holder["client"].call_count == 1
    assert no_sleep == []
