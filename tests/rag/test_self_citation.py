"""Tests for the S20-SELF-CITATION-GUARD-01 self-citation guard.

Covers:
  - URL-side detection (`is_self_citation`)
  - Idea-side detection (`is_self_referential_idea`)
  - Rerank behavior with the guard active vs inactive
  - Stress-matrix #5 regression case
"""

from __future__ import annotations

from uuid import uuid4

from gecko_core.rag.query import RagChunk, _rerank_by_provider
from gecko_core.rag.self_citation import (
    is_self_citation,
    is_self_referential_idea,
)


def _chunk(
    *,
    url: str,
    sim: float,
    provider_kind: str = "web",
    idx: int = 0,
) -> RagChunk:
    return RagChunk(
        source_id=uuid4(),
        source_url=url,
        chunk_index=idx,
        text="x",
        similarity=sim,
        provider_kind=provider_kind,  # type: ignore[arg-type]
    )


def test_self_citation_url_detection() -> None:
    # Positive: production domain + repo paths
    assert is_self_citation("https://app.geckovision.tech/foo")
    assert is_self_citation("https://geckovision.tech/about")
    assert is_self_citation(
        "https://github.com/ernanibmurtinho/gecko-mcpay-api/blob/main/README.md"
    )
    assert is_self_citation("https://github.com/ernanibmurtinho/gecko-mcpay-app/issues/1")
    # Current GeckoVision org paths (post-2026-06-10 migration)
    assert is_self_citation(
        "https://github.com/GeckoVision/gecko-claude/blob/main/README.md"
    )
    assert is_self_citation("https://github.com/GeckoVision/gecko-programs/issues/1")
    # Case-insensitive
    assert is_self_citation("HTTPS://APP.GECKOVISION.TECH/FOO")

    # Negative: unrelated https
    assert not is_self_citation("https://example.com/post/123")
    assert not is_self_citation("https://github.com/someone-else/repo")
    # Negative: non-https schemes — structured providers can't be Gecko-owned
    assert not is_self_citation("bazaar://listing/abc123")
    assert not is_self_citation("twitsh://post/9001")
    assert not is_self_citation("")


def test_self_referential_idea_keywords() -> None:
    # Positive — distinctive Gecko-product phrases
    assert is_self_referential_idea(
        "tradeable-judgment-as-product — paid x402 paywall on verdict URLs"
    )
    assert is_self_referential_idea("a Gecko-style insight market")
    assert is_self_referential_idea("Tradeable Verdict as a service")
    assert is_self_referential_idea("paywall research outputs via x402")

    # Negative — adjacent/legitimate ideas should NOT trigger
    assert not is_self_referential_idea("x402 onramp aggregator for Solana")
    assert not is_self_referential_idea("DeFi yield routing for stablecoins")
    assert not is_self_referential_idea("a marketplace for AI agent tools")
    # Bare "verdict" alone — deliberately NOT a trigger
    assert not is_self_referential_idea("court verdict tracking dashboard")
    assert not is_self_referential_idea("")


def test_stress_matrix_5_regression() -> None:
    """Stress-matrix #5 concrete idea must trigger."""
    idea = "tradeable-judgment-as-product — paid x402 paywall on verdict URLs"
    assert is_self_referential_idea(idea) is True


def test_rerank_downweights_self_citations() -> None:
    """Active guard: a Gecko-domain chunk loses its top slot to a peer."""
    gecko_chunk = _chunk(
        url="https://app.geckovision.tech/blog/verdict-as-product",
        sim=0.80,
    )
    peer_chunk = _chunk(
        url="https://example.com/research/insight-markets",
        sim=0.78,
    )
    chunks = [gecko_chunk, peer_chunk]

    # Inactive baseline — Gecko chunk wins on raw similarity.
    baseline = _rerank_by_provider(chunks, top_k=2, self_citation_active=False)
    assert baseline[0].source_url == gecko_chunk.source_url

    # Active — Gecko chunk drops below peer because 0.80 * 0.5 = 0.40 < 0.78.
    guarded = _rerank_by_provider(chunks, top_k=2, self_citation_active=True)
    assert guarded[0].source_url == peer_chunk.source_url
    assert guarded[1].source_url == gecko_chunk.source_url
    # Not dropped — soft guard, not a filter.
    assert len(guarded) == 2


def test_rerank_unchanged_when_inactive() -> None:
    """With guard off, output is byte-identical to the pre-S20 baseline."""
    chunks = [
        _chunk(url="https://app.geckovision.tech/x", sim=0.9),
        _chunk(url="https://example.com/y", sim=0.8),
        _chunk(url="https://example.org/z", sim=0.7),
    ]
    out_a = _rerank_by_provider(chunks, top_k=3, self_citation_active=False)
    out_b = _rerank_by_provider(chunks, top_k=3)
    assert [c.source_url for c in out_a] == [c.source_url for c in out_b]
    assert [c.similarity for c in out_a] == [c.similarity for c in out_b]
    # And the Gecko chunk is still on top — guard is off.
    assert out_a[0].source_url == "https://app.geckovision.tech/x"
