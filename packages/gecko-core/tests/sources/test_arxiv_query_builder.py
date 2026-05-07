"""S21-FIX-09 — Arxiv query-construction + retry coverage.

Production session ``d7d26f26-c652-4de6-be6b-c16c18096469`` logged
``arxiv.parse.empty`` on a URL that ANDed five hyphenated terms together.
The mirror returned a 200 with zero bytes (not a valid empty ``<feed/>``)
because no abstract matches all five over-narrow tokens.

These tests cover:
  - the term cap (≤3),
  - hyphen explosion,
  - OR-joining,
  - the empty-body retry path that loosens to a single term,
  - the give-up path when both attempts return empty bodies.

Pattern C: recorded-fixture style only — no live Arxiv calls.
"""

from __future__ import annotations

import httpx
import pytest
from gecko_core.sources.arxiv.provider import (
    DEFAULT_MAX_KEYWORDS,
    FALLBACK_MAX_KEYWORDS,
    _build_query,
    _extract_keywords,
    _split_hyphens,
    make_arxiv_source,
)

# Reused tiny fixture so the retry test can assert "second attempt
# parsed two entries" without copying the full Atom payload.
_FIXTURE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2403.12345v1</id>
    <title>Agentic Marketplaces and Verifiable Judgment</title>
    <summary>We propose a protocol where autonomous agents trade verdicts.</summary>
    <author><name>Alice Researcher</name></author>
    <link href="http://arxiv.org/pdf/2403.12345v1" type="application/pdf" title="pdf"/>
    <arxiv:primary_category term="cs.MA" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <title>Retrieval-Augmented Reasoning with x402 Micropayments</title>
    <summary>An empirical study of paid-evidence orchestration.</summary>
    <author><name>Carol Solo</name></author>
    <arxiv:primary_category term="cs.IR" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""

_EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:totalResults>
</feed>
"""


# ---------------------------------------------------------------------------
# pure builder coverage
# ---------------------------------------------------------------------------


def test_default_keyword_cap_is_four() -> None:
    # FIX-09 re-fire: cap loosened from 3 → 4 so multi-noun ideas like
    # "neobank Solana USDC categorized context" keep enough keyword
    # density for Arxiv relevance ranking to surface a paper.
    assert DEFAULT_MAX_KEYWORDS == 4
    assert FALLBACK_MAX_KEYWORDS == 1


def test_extract_keywords_caps_at_limit_even_with_many_inputs() -> None:
    # The production failure: 5 hyphenated phrases. After hyphen-explosion
    # we get many tokens; cap must hold at the requested limit.
    idea = (
        "strategy-architecture domain-specific research-market "
        "infrastructure build-context for agentic discovery"
    )
    kept = _extract_keywords(idea, limit=4)
    assert len(kept) == 4


def test_extract_keywords_explodes_hyphens() -> None:
    kept = _extract_keywords("strategy-architecture", limit=10)
    # hyphens split, both parts present, neither contains a hyphen.
    assert "strategy" in kept
    assert "architecture" in kept
    assert all("-" not in t for t in kept)


def test_split_hyphens_drops_short_fragments() -> None:
    # Fragments under 3 chars are noise (e.g. "a-tool" → ["tool"]).
    assert _split_hyphens("a-tool") == ["tool"]
    # No hyphen → unchanged.
    assert _split_hyphens("agentic") == ["agentic"]


def test_build_query_uses_or_joiner_by_default() -> None:
    query = _build_query("agentic protocol research")
    assert "+OR+" in query
    assert "+AND+" not in query


def test_build_query_caps_terms_for_production_idea() -> None:
    # The exact production query that triggered S21-FIX-09.
    idea = (
        "strategy-architecture AND domain-specific AND research-market "
        "AND infrastructure AND build-context"
    )
    query = _build_query(idea)
    # ≤4 `all:` clauses regardless of how many tokens we threw at it.
    assert query.count("all:") <= 4
    # No literal hyphenated tokens leak through.
    assert "strategy-architecture" not in query
    assert "build-context" not in query


def test_build_query_fallback_limit_yields_single_term() -> None:
    query = _build_query(
        "agentic protocol research with multiple terms",
        max_keywords=FALLBACK_MAX_KEYWORDS,
    )
    assert query.count("all:") == 1


def test_build_query_explicit_and_operator_still_supported() -> None:
    # We keep AND wired up so a future caller can request it; default
    # path stays OR.
    query = _build_query("agentic protocol research", operator="AND")
    assert "+AND+" in query


def test_build_query_unknown_operator_defaults_to_or() -> None:
    query = _build_query("agentic protocol research", operator="XOR")
    assert "+OR+" in query


# ---------------------------------------------------------------------------
# FIX-09 re-fire: dogfood-failing idea + raw-idea fallback path
# ---------------------------------------------------------------------------


def test_extract_keywords_for_dogfood_idea_yields_four_terms() -> None:
    """Pure-function unit test for the FIX-09 keyword extractor.

    The dogfood idea ``"neobank Solana USDC categorized context"`` was
    returning zero Arxiv hits because the legacy code AND-joined every
    token. The extractor must surface 4 distinct, hyphen-free, non-stop
    keywords from this input so the OR-join below is well-formed.
    """
    kept = _extract_keywords("neobank Solana USDC categorized context", limit=4)
    assert len(kept) == 4
    assert all("-" not in t for t in kept)
    # The four input nouns should all survive the stopword filter.
    for token in ("neobank", "solana", "categorized", "context"):
        assert token in kept


def test_build_query_dogfood_idea_is_or_joined_and_capped() -> None:
    """Smoke for the query string assembled from the failing dogfood idea.

    Asserts the two FIX-09 invariants the production failure violated:
    OR-joining (not AND) and ≤4 ``all:`` clauses.
    """
    query = _build_query("neobank Solana USDC categorized context")
    assert "+OR+" in query
    assert "+AND+" not in query
    assert 0 < query.count("all:") <= 4


def test_build_query_falls_back_to_truncated_raw_idea_when_few_keywords() -> None:
    """When extraction yields fewer than 2 terms, degrade to raw idea (≤80 ch).

    All-stopwords input strips to an empty keyword list; the builder
    returns the URL-encoded raw idea bounded at 80 characters rather
    than an empty / 1-term query that the mirror would 200-with-nothing.
    """
    long_idea = "the and of the and " * 20  # all stopwords; extractor returns []
    query = _build_query(long_idea)
    assert "all:" not in query  # raw-idea fallback, not Lucene
    # quote_plus encodes spaces as '+'; decoded length must respect cap.
    decoded = query.replace("+", " ")
    assert len(decoded) <= 80


# ---------------------------------------------------------------------------
# fetch-level retry / give-up coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_retries_on_empty_body_then_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """First call returns empty body; retry with looser query returns Atom.

    The retry MUST hit a different URL (the fallback uses
    ``FALLBACK_MAX_KEYWORDS``) and the resulting SourceResult must
    contain the parsed chunks plus the ``empty_body`` WARN from the first
    attempt.
    """
    seen_urls: list[str] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if len(seen_urls) == 1:
            return httpx.Response(200, text="")
        return httpx.Response(200, text=_FIXTURE_ATOM)

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    src = make_arxiv_source(http_client=client)

    caplog.set_level("WARNING", logger="gecko_core.sources.arxiv.provider")
    result = await src.fetch(
        idea=(
            "strategy-architecture domain-specific research-market "
            "infrastructure build-context agentic"
        ),
        categories=set(),
    )
    await client.aclose()

    assert len(seen_urls) == 2, "expected one retry after empty body"
    assert seen_urls[0] != seen_urls[1], "retry must use loosened query URL"
    assert result.fired is True
    assert len(result.payload["chunks"]) == 2
    # The first attempt logged the empty_body WARN with its URL.
    assert any(
        "arxiv.query.empty_body" in r.getMessage() and seen_urls[0] in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_fetch_gives_up_after_two_empty_bodies(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both attempts return empty body → empty source list + give_up WARN."""
    seen_urls: list[str] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text="")

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    src = make_arxiv_source(http_client=client)

    caplog.set_level("WARNING", logger="gecko_core.sources.arxiv.provider")
    result = await src.fetch(
        idea=(
            "strategy-architecture domain-specific research-market "
            "infrastructure build-context agentic"
        ),
        categories=set(),
    )
    await client.aclose()

    assert len(seen_urls) == 2
    assert result.fired is False
    assert result.payload["chunks"] == []
    assert result.error is not None
    assert "empty body" in result.error
    # Give-up log carries both URLs so the operator can replay them.
    give_up_msgs = [
        r.getMessage() for r in caplog.records if "arxiv.query.give_up" in r.getMessage()
    ]
    assert give_up_msgs, "expected arxiv.query.give_up WARN"
    assert seen_urls[0] in give_up_msgs[0]
    assert seen_urls[1] in give_up_msgs[0]


@pytest.mark.asyncio
async def test_fetch_does_not_retry_on_valid_empty_feed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A valid <feed/> with totalResults=0 is a normal miss, not the bug.

    We log INFO ``arxiv.query.zero_results`` and return cleanly without
    a retry — the bug is specifically the zero-byte body, not zero hits.
    """
    seen_urls: list[str] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text=_EMPTY_FEED)

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    src = make_arxiv_source(http_client=client)

    caplog.set_level("INFO", logger="gecko_core.sources.arxiv.provider")
    result = await src.fetch(idea="agentic protocol research", categories=set())
    await client.aclose()

    assert len(seen_urls) == 1, "valid empty feed must NOT trigger retry"
    assert result.fired is False
    assert result.payload["chunks"] == []
    assert any("arxiv.query.zero_results" in r.getMessage() for r in caplog.records)
