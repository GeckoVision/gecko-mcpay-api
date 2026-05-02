"""Tests for V11-01 — bound concurrency + RateLimitError retry.

S16-INGEST-04: the legacy `_RETRY_BACKOFFS_S` constant was removed in
S16-INGEST-03 when fixed backoffs were replaced with full-jitter
exponential. These tests still cover meaningful behavior that
`tests/ingestion/test_embedder_retry_jitter.py` does NOT (the happy
path with no retry, the single-transient retry case, and non-rate-limit
exceptions short-circuiting). They are kept and rewired against the
new symbols (`asyncio.sleep` + `_full_jitter_backoff`) so jitter
sleeps are skipped without depending on a removed module attribute.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest
from gecko_core.ingestion import embedder


def _fake_response(vectors: list[list[float]], tokens: int) -> Any:
    resp = MagicMock()
    resp.data = [MagicMock(embedding=v) for v in vectors]
    resp.usage = MagicMock(total_tokens=tokens)
    return resp


def _fake_client(create_mock: AsyncMock) -> Any:
    client = MagicMock()
    client.embeddings = MagicMock()
    client.embeddings.create = create_mock
    return client


def _rate_limit_error(code: str = "tokens") -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError(
        message="rate limited",
        response=response,
        body={"error": {"code": code, "message": "tpm"}},
    )


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the real jittered sleeps so tests stay fast.

    S16-INGEST-04 — replaces the old `_RETRY_BACKOFFS_S` patch. The
    embedder now sleeps via `asyncio.sleep(_full_jitter_backoff(n))`;
    we stub both so the unit under test executes the retry control
    flow without spending wall-clock time on jitter draws.
    """

    async def _instant_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(embedder.asyncio, "sleep", _instant_sleep)
    monkeypatch.setattr(embedder, "_full_jitter_backoff", lambda _attempt: 0.0)


@pytest.mark.asyncio
async def test_happy_path_no_retry() -> None:
    create = AsyncMock(return_value=_fake_response([[0.1, 0.2]], 5))
    vectors, tokens = await embedder.embed(
        ["hello"], client=_fake_client(create), model="text-embedding-3-small"
    )
    assert vectors == [[0.1, 0.2]]
    assert tokens == 5
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_one_transient_then_success() -> None:
    create = AsyncMock(side_effect=[_rate_limit_error("tokens"), _fake_response([[0.3]], 3)])
    vectors, tokens = await embedder.embed(
        ["hi"], client=_fake_client(create), model="text-embedding-3-small"
    )
    assert vectors == [[0.3]]
    assert tokens == 3
    # 1 failure + 1 success = exactly one retry.
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_max_attempts_rate_limits_raises() -> None:
    """S16-INGEST-04 — was `test_four_rate_limits_raises` against the
    legacy 4-attempt cap. Cap is now 5 (`_MAX_ATTEMPTS`); after 5
    consecutive rate-limit responses the last one propagates."""
    side_effects: list[Any] = [_rate_limit_error() for _ in range(embedder._MAX_ATTEMPTS)]
    create = AsyncMock(side_effect=side_effects)
    with pytest.raises(openai.RateLimitError):
        await embedder.embed(["hi"], client=_fake_client(create), model="text-embedding-3-small")
    # Exactly _MAX_ATTEMPTS calls; no extra attempt past the cap.
    assert create.await_count == embedder._MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_non_rate_limit_error_does_not_retry() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(500, request=request)
    api_error = openai.APIStatusError("boom", response=response, body=None)
    create = AsyncMock(side_effect=api_error)
    with pytest.raises(openai.APIStatusError):
        await embedder.embed(["hi"], client=_fake_client(create), model="text-embedding-3-small")
    assert create.await_count == 1
