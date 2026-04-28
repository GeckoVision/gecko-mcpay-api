"""Tests for V11-01 — bound concurrency + RateLimitError retry."""

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
    """Skip the real backoff sleeps so tests stay fast."""
    monkeypatch.setattr(embedder, "_RETRY_BACKOFFS_S", (0.0, 0.0, 0.0, 0.0))


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
async def test_four_rate_limits_raises() -> None:
    create = AsyncMock(side_effect=[_rate_limit_error() for _ in range(4)])
    with pytest.raises(openai.RateLimitError):
        await embedder.embed(["hi"], client=_fake_client(create), model="text-embedding-3-small")
    # Max 4 attempts; no fifth.
    assert create.await_count == 4


@pytest.mark.asyncio
async def test_non_rate_limit_error_does_not_retry() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(500, request=request)
    api_error = openai.APIStatusError("boom", response=response, body=None)
    create = AsyncMock(side_effect=api_error)
    with pytest.raises(openai.APIStatusError):
        await embedder.embed(["hi"], client=_fake_client(create), model="text-embedding-3-small")
    assert create.await_count == 1
