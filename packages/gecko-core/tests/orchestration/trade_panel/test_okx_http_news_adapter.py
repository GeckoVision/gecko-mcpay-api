"""OKX V5 HMAC news adapter tests (reworked 2026-06-16).

vcr-style: a recorded OKX response is served through httpx.MockTransport; no
live network. Asserts:
  - articles normalize to the panel chunk shape
  - fail-OPEN on HTTP / transport / parse error
  - empty protocol short-circuits (no request)
  - OKX V5 HMAC auth headers are present + correctly signed; the secret is
    never the raw header value (only the base64 HMAC is sent)
  - epoch-millis publishTime is converted to ISO-8601
  - the request hits the real OKX V5 news path + carries the coin query
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from typing import Any

import httpx
from gecko_core.orchestration.trade_panel.okx_http_news_adapter import (
    OKXHttpNewsProvider,
    _extract_published,
    _normalize_articles,
)

_API_KEY = "test-key"
_SECRET = "test-secret"
_PASSPHRASE = "test-pass"


def _provider(handler: Any, *, passphrase: str = _PASSPHRASE) -> OKXHttpNewsProvider:
    transport = httpx.MockTransport(handler)
    return OKXHttpNewsProvider(
        api_key=_API_KEY,
        secret_key=_SECRET,
        passphrase=passphrase,
        client=httpx.AsyncClient(transport=transport),
    )


def test_fetch_returns_panel_shaped_chunks() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "title": "Kamino TVL hits ATH",
                        "summary": "Deposits surged 20% this week.",
                        "url": "https://news.example/a1",
                        "publishTime": "1781913600000",
                    }
                ],
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
    # epoch-millis -> ISO-8601 UTC
    assert c["published_ts"].startswith("20") and "T" in c["published_ts"]


def test_request_hits_okx_v5_news_path_with_coin_query() -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["ccyList"] = req.url.params.get("ccyList", "")
        seen["sortBy"] = req.url.params.get("sortBy", "")
        return httpx.Response(200, json={"code": "0", "data": []})

    provider = _provider(handler)
    asyncio.run(provider.fetch_news_chunks("kamino"))
    assert seen["path"] == "/api/v5/orbit/news-search"
    assert seen["ccyList"] == "KAMINO"  # ticker-normalized uppercase
    assert seen["sortBy"] == "latest"


def test_hmac_auth_headers_present_and_signed() -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        for h in (
            "ok-access-key",
            "ok-access-sign",
            "ok-access-timestamp",
            "ok-access-passphrase",
        ):
            seen[h] = req.headers.get(h, "")
        # Recompute the expected signature over the EXACT signed request path.
        request_path = req.url.raw_path.decode("ascii")
        prehash = f"{seen['ok-access-timestamp']}GET{request_path}"
        expected = base64.b64encode(
            hmac.new(_SECRET.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        seen["expected_sign"] = expected
        return httpx.Response(200, json={"code": "0", "data": []})

    provider = _provider(handler)
    asyncio.run(provider.fetch_news_chunks("kamino"))
    assert seen["ok-access-key"] == _API_KEY
    assert seen["ok-access-passphrase"] == _PASSPHRASE
    assert seen["ok-access-timestamp"]  # non-empty ISO-8601 millis
    # The signature on the wire is the base64 HMAC — NEVER the raw secret.
    assert seen["ok-access-sign"] != _SECRET
    assert seen["ok-access-sign"] == seen["expected_sign"]


def test_passphrase_header_omitted_when_absent() -> None:
    seen: dict[str, bool] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["has_pp"] = "ok-access-passphrase" in req.headers
        return httpx.Response(200, json={"code": "0", "data": []})

    provider = _provider(handler, passphrase="")
    asyncio.run(provider.fetch_news_chunks("kamino"))
    assert seen["has_pp"] is False


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


def test_fetch_fails_open_on_bad_json() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    provider = _provider(handler)
    chunks = asyncio.run(provider.fetch_news_chunks("kamino"))
    assert chunks == []


def test_empty_protocol_returns_empty() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={"data": []}))
    assert asyncio.run(provider.fetch_news_chunks("")) == []


def test_normalize_handles_list_and_wrapped_shapes() -> None:
    assert _normalize_articles([{"title": "x"}]) == [{"title": "x"}]
    assert _normalize_articles({"data": [{"title": "d"}]}) == [{"title": "d"}]
    assert _normalize_articles({"articles": [{"title": "y"}]}) == [{"title": "y"}]
    assert _normalize_articles({"nope": 1}) == []
    assert _normalize_articles("garbage") == []
    # Non-dict items inside a list are dropped.
    assert _normalize_articles([{"title": "ok"}, "skip", 3]) == [{"title": "ok"}]


def test_extract_published_handles_epoch_and_iso() -> None:
    # epoch-millis (OKX publishTime) -> ISO-8601
    iso = _extract_published({"publishTime": "1781913600000"})
    assert iso is not None and iso.startswith("20") and "T" in iso
    # already-ISO passes through
    assert _extract_published({"publishedAt": "2026-06-14T00:00:00Z"}) == ("2026-06-14T00:00:00Z")
    # missing -> None
    assert _extract_published({}) is None
