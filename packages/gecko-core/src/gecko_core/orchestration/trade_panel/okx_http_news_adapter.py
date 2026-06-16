"""OKX direct-HTTP news provider — Phase 2.1 (context-engineering, 2026-06-15).

The MCP-backed ``OKXNewsProvider`` (okx_news_adapter.py) needs an ``mcp_call``
transport that the deployed ECS task does NOT have. This adapter talks to the
OKX news REST endpoint directly over ``httpx`` so the deployed Pattern-E
reachability for live news can finally be satisfied (the gap flagged in
okx_news_adapter.py's DEPLOYMENT GAP note).

Provider-neutral by construction: it satisfies the same ``NewsProvider``
protocol as every other adapter; the panel never imports it directly (only the
ENV-gated factory does).

CONFIG (both required, else the factory never constructs this):
  - ``OKX_NEWS_API_URL`` — full REST endpoint base, provider-neutral. The
    coin/query is sent as a query param.
  - ``OKX_API_KEY`` — bearer credential. NEVER logged.

FAIL-OPEN: any network / parse / auth error returns an empty list. The panel
merges ``[]`` as a no-op, so news being down NEVER breaks the verdict.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from gecko_core.orchestration.trade_panel.news_provider import (
    NewsProvider,
    build_news_chunk,
)

_log = logging.getLogger(__name__)

# Network budget — the panel's round-1 must not stall on a slow news endpoint.
# Fail-OPEN on timeout: the sentiment voice runs corpus-only, exactly as today.
_HTTP_TIMEOUT_S = 4.0


class OKXHttpNewsProvider:
    """NewsProvider backed by the OKX news REST endpoint over httpx.

    Satisfies the ``NewsProvider`` protocol. Construct only via the ENV-gated
    factory (``news_factory.build_news_provider``) so prod never wires it
    without both ``OKX_NEWS_API_URL`` and ``OKX_API_KEY`` present.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        # Injectable client for tests (httpx.MockTransport, vcr-style).
        self._client = client

    async def fetch_news_chunks(
        self,
        protocol: str,
        *,
        max_results: int = 5,
        as_of: Any = None,
    ) -> list[dict[str, Any]]:
        proto = (protocol or "").strip()
        if not proto:
            return []

        try:
            articles = await self._fetch_articles(proto, max_results)
        except Exception as exc:
            # Fail-OPEN. Class name only — the URL/key must never reach logs.
            _log.warning(
                "okx_http_news.fetch_failed protocol=%s err=%s",
                proto,
                type(exc).__name__,
            )
            return []

        chunks: list[dict[str, Any]] = []
        for a in articles[:max_results]:
            headline = (a.get("title") or a.get("headline") or "").strip()
            if not headline:
                continue
            body = (a.get("summary") or a.get("body") or a.get("description") or "").strip()
            chunks.append(
                build_news_chunk(
                    headline=headline,
                    body=body,
                    url=a.get("url") or a.get("link"),
                    published_ts=(
                        a.get("published_ts") or a.get("publishedAt") or a.get("created_at")
                    ),
                    protocol=proto,
                )
            )
        return chunks

    async def _fetch_articles(self, proto: str, max_results: int) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"coin": proto.upper(), "q": proto, "limit": max_results}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._client is not None:
            resp = await self._client.get(self._base_url, params=params, headers=headers)
            resp.raise_for_status()
            return _normalize_articles(resp.json())
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
            resp = await client.get(self._base_url, params=params, headers=headers)
            resp.raise_for_status()
            return _normalize_articles(resp.json())


def _normalize_articles(payload: Any) -> list[dict[str, Any]]:
    """Pull the article list out of various OKX response shapes."""
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "articles", "news", "results", "items"):
        v = payload.get(key)
        if isinstance(v, list):
            return [a for a in v if isinstance(a, dict)]
    return []


# Import-time protocol-conformance guard (catches drift, like okx_news_adapter).
assert isinstance(OKXHttpNewsProvider(base_url="https://x", api_key="k"), NewsProvider)


__all__ = ["OKXHttpNewsProvider"]
