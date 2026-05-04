"""S26-SOURCE-DIVERSITY-01 — provenance.provider_kind is stamped on basic citations.

basic.generate() must stamp provenance.provider_kind on each citation from
the rag_query chunk lookup so audit_provider_mix can detect provider diversity
even when only source_url + default provenance ("free") come from the LLM.
"""

from __future__ import annotations

from uuid import uuid4

from gecko_core.models import Citation, Provenance
from gecko_core.orchestration.provider_mix_audit import audit_provider_mix
from gecko_core.rag.query import RagChunk


def _citation(url: str, provider_kind: str = "free") -> Citation:
    return Citation(
        source_url=url,
        chunk_index=0,
        similarity=0.6,
        provenance=Provenance(provider_kind=provider_kind),
    )


def _chunk(url: str, provider_kind: str) -> RagChunk:
    return RagChunk(
        source_id=uuid4(),
        source_url=url,
        chunk_index=0,
        text="text",
        similarity=0.6,
        provider_kind=provider_kind,
    )


# ---------------------------------------------------------------------------
# audit_provider_mix behaviour with correctly-stamped provenance
# ---------------------------------------------------------------------------


def test_audit_returns_balanced_when_multiple_kinds_stamped() -> None:
    citations = [
        _citation("https://techcrunch.com/1", "web"),
        _citation("https://techcrunch.com/2", "web"),
        _citation("twitsh://session/s1", "twitsh"),
        _citation("bazaar://service/tool", "bazaar"),
        _citation("https://arxiv.org/abs/1234", "arxiv"),
    ]
    assert audit_provider_mix(citations) == "balanced"


def test_audit_returns_single_provider_dominates_all_web() -> None:
    citations = [_citation(f"https://example.com/{i}", "web") for i in range(5)]
    assert audit_provider_mix(citations) == "single_provider_dominates"


def test_audit_uses_provenance_kind_for_resolved_twitsh_url() -> None:
    """After CITE-03 resolution, twitsh citations have https:// source_url but
    provenance.provider_kind = 'twitsh'.  audit_provider_mix must see 'twitsh'."""
    citations = [
        _citation("https://techcrunch.com/1", "web"),
        _citation("https://techcrunch.com/2", "web"),
        _citation("https://twitter.com/user/status/1", "twitsh"),  # resolved
        _citation("https://twitter.com/user/status/2", "twitsh"),  # resolved
        _citation("bazaar://svc/tool", "bazaar"),
    ]
    flag = audit_provider_mix(citations)
    # Two twitsh + two web + one bazaar: web is 2/5 = 40% — not dominant.
    assert flag != "single_provider_dominates"


# ---------------------------------------------------------------------------
# _stamp helper logic (mirrors the implementation in basic.py)
# ---------------------------------------------------------------------------


def _stamp(citations_list: list[Citation], chunks: list[RagChunk]) -> list[Citation]:
    """Reproduce the _stamp helper from basic.generate() for unit testing."""
    chunk_kind_by_url: dict[str, str] = {c.source_url: c.provider_kind for c in chunks}

    out: list[Citation] = []
    for cit in citations_list:
        kind = chunk_kind_by_url.get(str(cit.source_url))
        if kind and kind != (cit.provenance.provider_kind if cit.provenance else "free"):
            cit = cit.model_copy(update={"provenance": Provenance(provider_kind=kind)})
        out.append(cit)
    return out


def test_stamp_overwrites_free_with_twitsh() -> None:
    chunks = [_chunk("twitsh://session/s1", "twitsh")]
    citations = [_citation("twitsh://session/s1", "free")]

    stamped = _stamp(citations, chunks)
    assert stamped[0].provenance is not None
    assert stamped[0].provenance.provider_kind == "twitsh"


def test_stamp_preserves_existing_correct_kind() -> None:
    chunks = [_chunk("https://example.com/", "web")]
    citations = [_citation("https://example.com/", "web")]

    stamped = _stamp(citations, chunks)
    assert stamped[0].provenance is not None
    assert stamped[0].provenance.provider_kind == "web"


def test_stamp_leaves_unmatched_citation_unchanged() -> None:
    chunks = [_chunk("https://example.com/a", "web")]
    citations = [_citation("https://other.com/b", "free")]

    stamped = _stamp(citations, chunks)
    # No matching chunk; provenance must stay as-is.
    assert stamped[0].provenance is not None
    assert stamped[0].provenance.provider_kind == "free"
