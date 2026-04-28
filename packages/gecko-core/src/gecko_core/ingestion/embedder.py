"""OpenAI embeddings, batched.

`text-embedding-3-small` → 1536-dim vectors. Batches at 100 inputs per call,
which is well under the OpenAI 2048-input limit and keeps individual call
latency bounded.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from openai import AsyncOpenAI

from .settings import get_ingestion_settings

EMBED_BATCH_SIZE = 100

# OpenAI list price for text-embedding-3-small as of 2026-04. Cheap enough
# that we don't worry about a few cents of drift; surfaced on the per-session
# economics view so dashboards reflect real, not stub, spend.
_EMBED_RATES_USD_PER_1M: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}


def _chunked(seq: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def estimate_embed_cost_usd(model: str, total_tokens: int) -> float:
    rate = _EMBED_RATES_USD_PER_1M.get(model, 0.0)
    return total_tokens * rate / 1_000_000


async def embed(
    texts: list[str],
    *,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
    batch_size: int = EMBED_BATCH_SIZE,
) -> tuple[list[list[float]], int]:
    """Embed `texts`, batching at `batch_size`. Order-preserving.

    Returns (vectors, total_tokens). The token count is the sum across all
    batches and lets callers attribute cost to a session.
    """
    if not texts:
        return [], 0

    settings = get_ingestion_settings()
    api = client or AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
    model_name = model or settings.embed_model

    async def _one_batch(batch: list[str]) -> tuple[list[list[float]], int]:
        resp = await api.embeddings.create(model=model_name, input=batch)
        tokens = resp.usage.total_tokens if resp.usage is not None else 0
        return [d.embedding for d in resp.data], tokens

    batches = list(_chunked(texts, batch_size))
    # Sequential — protects rate limits and keeps cost predictable.
    results: list[list[float]] = []
    total_tokens = 0
    for batch in batches:
        vectors, tokens = await _one_batch(batch)
        results.extend(vectors)
        total_tokens += tokens
    await asyncio.sleep(0)
    return results, total_tokens


__all__ = ["EMBED_BATCH_SIZE", "embed", "estimate_embed_cost_usd"]
