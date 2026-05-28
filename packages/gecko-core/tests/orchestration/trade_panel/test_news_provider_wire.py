"""Sprint 18 #1 wire-tests — news_provider integration.

Per Sprint 18 design synthesis: wire okx-news MCP into the oracle envelope.
This test verifies:
  1. The NewsProvider protocol is structurally satisfiable by simple classes
  2. The default no-op (`NullNewsProvider`) returns empty list
  3. `merge_news_chunks` returns input unchanged when provider=None (no
     behavior delta for existing callers)
  4. Chunks are merged at the end of the corpus list when a fake provider
     fires; corpus indices stay stable
  5. The OKX adapter normalizes various OKX response shapes correctly
  6. Build a chunk via `build_news_chunk` — produces the panel-expected shape

Light fakes (per memory `feedback_lighter_tests`); no real MCP calls.
"""
from __future__ import annotations

from typing import Any

import pytest

from gecko_core.orchestration.trade_panel.news_provider import (
    NewsProvider,
    NullNewsProvider,
    build_news_chunk,
    merge_news_chunks,
)
from gecko_core.orchestration.trade_panel.okx_news_adapter import (
    OKXNewsProvider,
    _normalize_articles,
)


class _FakeProvider:
    """Light fake — returns a fixed list."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks
        self.calls: list[tuple[str, int, Any]] = []

    async def fetch_news_chunks(
        self, protocol: str, *, max_results: int = 5, as_of: Any = None
    ) -> list[dict[str, Any]]:
        self.calls.append((protocol, max_results, as_of))
        return list(self._chunks)


def test_fake_provider_satisfies_protocol():
    """Any class with `fetch_news_chunks` matching the signature is a NewsProvider."""
    fp = _FakeProvider([])
    assert isinstance(fp, NewsProvider)


def test_null_provider_returns_empty():
    """Default no-op provider — never returns anything."""
    import asyncio

    async def run() -> list[dict[str, Any]]:
        return await NullNewsProvider().fetch_news_chunks("kamino", max_results=5)

    assert asyncio.run(run()) == []


def test_merge_with_none_provider_is_noop():
    """provider=None must be byte-identical to the input chunks."""
    import asyncio

    corpus = [
        {"id": "a", "text": "corpus chunk A"},
        {"id": "b", "text": "corpus chunk B"},
    ]

    async def run() -> list[dict[str, Any]]:
        return await merge_news_chunks(corpus, provider=None, protocol="kamino")

    out = asyncio.run(run())
    assert out == corpus
    # And no copy — same reference is fine but a fresh list is also fine;
    # just no mutation
    assert [c["id"] for c in out] == ["a", "b"]


def test_merge_appends_news_after_corpus():
    """News chunks go AFTER corpus chunks — corpus indices stay stable."""
    import asyncio

    corpus = [
        {"id": "corpus-1", "text": "first corpus chunk"},
        {"id": "corpus-2", "text": "second corpus chunk"},
    ]
    news_chunk = build_news_chunk(
        headline="Kamino announces lending v2",
        body="Kamino has launched lending v2 with auto-compounding APY.",
        url="https://example.com/kamino-v2",
        protocol="kamino",
    )
    fake = _FakeProvider([news_chunk])

    async def run() -> list[dict[str, Any]]:
        return await merge_news_chunks(corpus, provider=fake, protocol="kamino")

    out = asyncio.run(run())
    assert len(out) == 3
    assert [c["id"] for c in out[:2]] == ["corpus-1", "corpus-2"]  # corpus first
    assert out[2]["source"] == "okx-news"
    assert out[2]["provider_kind"] == "okx_news_live"
    # Provider was called with the right args
    assert fake.calls == [("kamino", 5, None)]


def test_merge_dedupes_by_chunk_id():
    """If a news chunk's id matches a corpus chunk's id, the news one is dropped."""
    import asyncio

    dup_id = "okx-news-deadbeef0000"
    corpus = [{"id": dup_id, "text": "already in corpus"}]
    news_chunk = build_news_chunk(
        headline="duplicate", body="should be skipped", url="x", protocol="kamino"
    )
    # Force the id collision
    news_chunk["id"] = dup_id
    fake = _FakeProvider([news_chunk])

    async def run() -> list[dict[str, Any]]:
        return await merge_news_chunks(corpus, provider=fake, protocol="kamino")

    out = asyncio.run(run())
    assert len(out) == 1  # duplicate dropped


def test_merge_swallows_provider_exception():
    """A provider that raises must NOT crash the panel — return corpus unchanged."""
    import asyncio

    class _RaiseyProvider:
        async def fetch_news_chunks(self, protocol, *, max_results=5, as_of=None):
            raise RuntimeError("upstream news API timeout")

    corpus = [{"id": "a", "text": "x"}]

    async def run() -> list[dict[str, Any]]:
        return await merge_news_chunks(corpus, provider=_RaiseyProvider(), protocol="kamino")

    out = asyncio.run(run())
    assert out == corpus  # graceful degradation


def test_build_news_chunk_shape():
    """Verify the chunk shape matches the panel's expectations."""
    c = build_news_chunk(
        headline="JTO restaking integration",
        body="JTO announces partnership with Marinade for restaking yield.",
        url="https://example.com/jto-marinade",
        published_ts="2026-05-28T12:00:00+00:00",
        protocol="JTO",
    )
    # Required fields for trade-panel chunk processing
    assert c["id"].startswith("okx-news-")
    assert c["source"] == "okx-news"
    assert c["provider_kind"] == "okx_news_live"
    assert c["freshness_tier"] == "live_only"
    assert c["protocol"] == "jto"  # normalized lowercase
    assert "JTO restaking integration" in c["text"]
    assert "Marinade" in c["text"]
    assert c["url"] == "https://example.com/jto-marinade"


def test_build_news_chunk_truncates_long_body():
    """Bodies over 600 chars must be truncated with an ellipsis marker."""
    long_body = "x" * 800
    c = build_news_chunk(headline="test", body=long_body, protocol="kamino")
    assert "…" in c["text"]
    # Headline + ". " + truncated body + "…"
    assert len(c["text"]) <= 7 + 600 + 1 + 5  # cap with small margin


def test_build_news_chunk_stable_id():
    """Same headline + URL → same id (dedupe-friendly)."""
    a = build_news_chunk(headline="X", body="y", url="http://z", protocol="p")
    b = build_news_chunk(headline="X", body="different body!", url="http://z", protocol="p")
    assert a["id"] == b["id"]  # id is based on headline + URL, not body


def test_normalize_articles_various_shapes():
    """OKX MCP responses come in various shapes; the helper unpacks all of them."""
    # Already a list
    assert _normalize_articles([{"title": "x"}]) == [{"title": "x"}]
    # Wrapped in "data"
    assert _normalize_articles({"data": [{"title": "x"}]}) == [{"title": "x"}]
    # Wrapped in "articles"
    assert _normalize_articles({"articles": [{"title": "x"}]}) == [{"title": "x"}]
    # Empty / wrong shape
    assert _normalize_articles({}) == []
    assert _normalize_articles(None) == []  # type: ignore[arg-type]
    assert _normalize_articles("not a dict") == []  # type: ignore[arg-type]


def test_okx_adapter_calls_correct_mcp_tools():
    """The adapter must invoke the OKX news MCP tools with the right args."""
    import asyncio

    calls: list[tuple[str, dict]] = []

    async def fake_mcp(tool: str, args: dict) -> dict:
        calls.append((tool, args))
        if "by_coin" in tool:
            return {"data": [
                {"title": "Kamino lending v2", "summary": "lv2 ships", "url": "u1"},
                {"title": "Kamino restaking", "summary": "restake live", "url": "u2"},
            ]}
        return {"data": []}

    provider = OKXNewsProvider(mcp_call=fake_mcp)

    async def run() -> list[dict[str, Any]]:
        return await provider.fetch_news_chunks("kamino", max_results=5)

    chunks = asyncio.run(run())
    assert len(chunks) == 2
    # Should have called the coin endpoint first
    assert calls[0][0] == "mcp__okx-agent-trade-kit__news_get_by_coin"
    assert calls[0][1]["coin"] == "KAMINO"
    assert calls[0][1]["limit"] == 5
    # Chunks have the right shape
    assert all(c["source"] == "okx-news" for c in chunks)
    assert all(c["provider_kind"] == "okx_news_live" for c in chunks)


def test_okx_adapter_falls_back_to_search():
    """When coin endpoint returns empty, fall back to search."""
    import asyncio

    calls: list[tuple[str, dict]] = []

    async def fake_mcp(tool: str, args: dict) -> dict:
        calls.append((tool, args))
        if "by_coin" in tool:
            return {"data": []}
        if "search" in tool:
            return {"data": [{"title": "search-result", "summary": "x", "url": "u"}]}
        return {}

    provider = OKXNewsProvider(mcp_call=fake_mcp)

    async def run() -> list[dict[str, Any]]:
        return await provider.fetch_news_chunks("paysh", max_results=3)

    chunks = asyncio.run(run())
    assert len(chunks) == 1
    # Should have called BOTH endpoints (coin first, then search fallback)
    assert len(calls) == 2
    assert calls[0][0].endswith("news_get_by_coin")
    assert calls[1][0].endswith("news_search")
    assert calls[1][1]["query"] == "paysh"


def test_okx_adapter_empty_protocol_returns_empty():
    """Defensive: empty / whitespace protocol → empty result, no MCP calls."""
    import asyncio

    calls: list[tuple[str, dict]] = []

    async def fake_mcp(tool: str, args: dict) -> dict:
        calls.append((tool, args))
        return {"data": []}

    provider = OKXNewsProvider(mcp_call=fake_mcp)

    async def run() -> list[dict[str, Any]]:
        return await provider.fetch_news_chunks("   ", max_results=5)

    chunks = asyncio.run(run())
    assert chunks == []
    assert calls == []  # no MCP call made for empty protocol
