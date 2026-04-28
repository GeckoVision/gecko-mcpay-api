"""RAG query layer — pgvector cosine similarity over a session's chunks.

Calls the `match_chunks` SQL function via Supabase RPC. Embeds the question
with the same model used at ingest time so the vectors live in the same
space. Returns chunks ordered by similarity desc.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from gecko_core.ingestion.embedder import embed
from gecko_core.sessions.store import SessionStore


class RagChunk(BaseModel):
    """A chunk surfaced by similarity search.

    `similarity` is in [0, 1]; 1.0 is identical. The `source_url` round-trips
    through to citations so the orchestration layer can validate every claim.
    """

    source_id: UUID
    source_url: HttpUrl
    chunk_index: int
    text: str
    similarity: float = Field(ge=0.0, le=1.0)


async def rag_query(
    session_id: UUID,
    question: str,
    top_k: int = 8,
    store: SessionStore | None = None,
) -> list[RagChunk]:
    """Embed `question` and return the top-k most similar chunks for the session."""
    if not question.strip():
        return []
    if top_k <= 0:
        return []

    store = store or SessionStore.from_env()

    vectors, tokens = await embed([question])
    if not vectors:
        return []
    query_embedding = vectors[0]
    # Account for the question-embedding cost too — small but real, and avoids
    # apparent margin drift between research and follow-up queries.
    if tokens > 0:
        from gecko_core.ingestion.embedder import estimate_embed_cost_usd
        from gecko_core.ingestion.settings import get_ingestion_settings

        cost = estimate_embed_cost_usd(get_ingestion_settings().embed_model, tokens)
        await store.add_cost(session_id, "embed", cost)

    def _rpc() -> list[dict[str, Any]]:
        # Underscore name to reach the inner Client; we keep the seam thin to
        # avoid leaking supabase types into gecko-core's public surface.
        client = store._client
        res = client.rpc(
            "match_chunks",
            {
                "p_session_id": str(session_id),
                "query_embedding": query_embedding,
                "match_count": top_k,
            },
        ).execute()
        return cast(list[dict[str, Any]], res.data or [])

    rows = await asyncio.to_thread(_rpc)
    return [RagChunk.model_validate(row) for row in rows]


__all__ = ["RagChunk", "rag_query"]
