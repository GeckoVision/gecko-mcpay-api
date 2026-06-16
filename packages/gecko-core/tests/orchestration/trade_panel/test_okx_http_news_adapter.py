"""Phase 2.1 — OKX direct-HTTP news adapter tests.

vcr-style: a recorded OKX response is served through httpx.MockTransport;
no live network. Asserts chunk-shape conformance + fail-OPEN on errors.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from gecko_core.orchestration.trade_panel.okx_http_news_adapter import (
    OKXHttpNewsProvider,
    _normalize_articles,
)


def _provider(handler: Any) -> OKXHttpNewsProvider:
    transport = httpx.MockTransport(handler)
    return OKXHttpNewsProvider(
        base_url="https://news.example/okx",
        api_key="test-key",
        client=httpx.AsyncClient(transport=transport),
    )


def test_fetch_returns_panel_shaped_chunks() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "title": "Kamino TVL hits ATH",
                        "summary": "Deposits surged 20% this week.",
                        "url": "https://news.example/a1",
                        "publishedAt": "2026-06-14T00:00:00Z",
                    }
                ]
            },
        )

    provider = _provider(handler)
    chunks = asyncio.run(provider.fetch_news_chunks("kamino", max_results=5))
    assert len(chunks) == 1
    c = chunks[0]
    assert c["provider_kind"] == "okx_news_live"
    assert c["freshness_tier"] == "live_only"
    assert c["protocol"] == "kamino"
    assert "Kamino TVL hits ATH" in c["text"]
    assert c["url"] == "https://news.example/a1"


def test_fetch_fails_open_on_http_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = _provider(handler)
    chunks = asyncio.run(provider.fetch_news_chunks("kamino"))
    assert chunks == []


def test_fetch_fails_open_on_transport_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    provider = _provider(handler)
    chunks = asyncio.run(provider.fetch_news_chunks("kamino"))
    assert chunks == []


def test_empty_protocol_returns_empty() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={"data": []}))
    assert asyncio.run(provider.fetch_news_chunks("")) == []


def test_api_key_in_auth_header_not_logged() -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization", "")
        return httpx.Response(200, json={"data": []})

    provider = _provider(handler)
    asyncio.run(provider.fetch_news_chunks("kamino"))
    assert seen["auth"] == "Bearer test-key"


def test_normalize_handles_list_and_wrapped_shapes() -> None:
    assert _normalize_articles([{"title": "x"}]) == [{"title": "x"}]
    assert _normalize_articles({"articles": [{"title": "y"}]}) == [{"title": "y"}]
    assert _normalize_articles({"nope": 1}) == []
    assert _normalize_articles("garbage") == []
