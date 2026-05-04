"""S26-CITE-03 — twitsh metadata round-trips through RagChunk; citation assembly resolves URIs.

Tests:
1. RagChunk accepts a metadata dict and it survives model_validate.
2. The citation assembly logic (mirrored here) resolves twitsh:// to tweet URL.
3. Provenance.provider_kind is stamped from the chunk's provider_kind.
"""

from __future__ import annotations

from uuid import uuid4

from gecko_core.models import Citation, Provenance
from gecko_core.rag.query import RagChunk

# ---------------------------------------------------------------------------
# RagChunk metadata field
# ---------------------------------------------------------------------------


def test_rag_chunk_accepts_metadata() -> None:
    chunk = RagChunk(
        source_id=uuid4(),
        source_url="twitsh://session/abc",
        chunk_index=0,
        text="interesting tweet",
        similarity=0.7,
        provider_kind="twitsh",
        metadata={"tweet_url": "https://twitter.com/user/status/1234"},
    )
    assert chunk.metadata["tweet_url"] == "https://twitter.com/user/status/1234"


def test_rag_chunk_metadata_defaults_to_empty_dict() -> None:
    chunk = RagChunk(
        source_id=uuid4(),
        source_url="https://example.com/article",
        chunk_index=0,
        text="text",
        similarity=0.6,
    )
    assert chunk.metadata == {}


def test_rag_chunk_model_validate_with_metadata() -> None:
    data = {
        "source_id": str(uuid4()),
        "source_url": "twitsh://session/xyz",
        "chunk_index": 1,
        "text": "tweet content",
        "similarity": 0.5,
        "provider_kind": "twitsh",
        "metadata": {"tweet_url": "https://twitter.com/foo/status/99"},
    }
    chunk = RagChunk.model_validate(data)
    assert chunk.metadata.get("tweet_url") == "https://twitter.com/foo/status/99"


# ---------------------------------------------------------------------------
# Citation assembly logic (mirrors ask() / research() in workflows.py)
# ---------------------------------------------------------------------------


def _build_citations(chunks: list[RagChunk]) -> list[Citation]:
    """Mirror the citation assembly from ask() in workflows.py."""
    return [
        Citation(
            source_url=(
                c.metadata.get("tweet_url") or c.source_url
                if c.source_url.startswith("twitsh://")
                else c.source_url
            ),
            chunk_index=c.chunk_index,
            similarity=c.similarity,
            provenance=Provenance(provider_kind=c.provider_kind),
        )
        for c in chunks
    ]


def test_twitsh_url_resolved_to_tweet_url() -> None:
    tweet_url = "https://twitter.com/founder/status/42"
    chunks = [
        RagChunk(
            source_id=uuid4(),
            source_url="twitsh://session/s1",
            chunk_index=0,
            text="tweet text",
            similarity=0.65,
            provider_kind="twitsh",
            metadata={"tweet_url": tweet_url},
        )
    ]
    citations = _build_citations(chunks)
    assert citations[0].source_url == tweet_url


def test_web_url_passes_through_unchanged() -> None:
    url = "https://techcrunch.com/article"
    chunks = [
        RagChunk(
            source_id=uuid4(),
            source_url=url,
            chunk_index=0,
            text="article text",
            similarity=0.72,
            provider_kind="web",
        )
    ]
    citations = _build_citations(chunks)
    assert citations[0].source_url == url


def test_twitsh_without_tweet_url_falls_back_to_synthetic_uri() -> None:
    chunks = [
        RagChunk(
            source_id=uuid4(),
            source_url="twitsh://session/s1",
            chunk_index=0,
            text="tweet text",
            similarity=0.5,
            provider_kind="twitsh",
            metadata={},  # no tweet_url
        )
    ]
    citations = _build_citations(chunks)
    # Falls back to synthetic URI — still a valid citation
    assert citations[0].source_url == "twitsh://session/s1"


def test_provenance_kind_stamped_from_chunk() -> None:
    chunks = [
        RagChunk(
            source_id=uuid4(),
            source_url="twitsh://session/s1",
            chunk_index=0,
            text="tweet text",
            similarity=0.65,
            provider_kind="twitsh",
            metadata={"tweet_url": "https://twitter.com/u/status/1"},
        ),
        RagChunk(
            source_id=uuid4(),
            source_url="https://techcrunch.com/",
            chunk_index=1,
            text="article",
            similarity=0.70,
            provider_kind="web",
        ),
    ]
    citations = _build_citations(chunks)
    kinds = {c.provenance.provider_kind for c in citations if c.provenance}
    assert "twitsh" in kinds
    assert "web" in kinds
