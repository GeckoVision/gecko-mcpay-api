"""OKX news adapter — wraps okx-agent-trade-kit news MCP tools.

Sprint 18 #1 (2026-05-28). Adapts the OKX MCP `news_get_by_coin` +
`news_search` tools to the trade-panel's NewsProvider protocol.

The adapter is intentionally HTTP-transport-agnostic: callers pass an
`mcp_call` function that knows how to invoke MCP tools in their context
(Claude Code session, FastAPI worker, CLI, etc). This module never
imports MCP-specific machinery.

USAGE (in the agent runtime):

    from gecko_core.orchestration.trade_panel.okx_news_adapter import OKXNewsProvider

    async def my_mcp_call(tool: str, args: dict) -> dict:
        # ... your MCP transport here ...
        return await mcp_client.call(tool, args)

    provider = OKXNewsProvider(mcp_call=my_mcp_call)
    verdict = await run_trade_panel_with_retrieval(
        idea="...",
        protocol="kamino",
        news_provider=provider,
    )

If `okx-agent-trade-kit` is not available (CI / tests / offline dev), use
the NullNewsProvider from `news_provider.py` — same Protocol, no-op.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from gecko_core.orchestration.trade_panel.news_provider import (
    NewsProvider,
    build_news_chunk,
)

_log = logging.getLogger(__name__)


# Type alias — caller's MCP transport
MCPCallable = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class OKXNewsProvider:
    """News provider backed by `okx-agent-trade-kit` MCP tools.

    Tools used (per MCP catalog in session 2026-05-28):
      - `news_get_by_coin(coin, limit)` — recent news for a coin symbol
      - `news_search(query, limit)` — keyword search (fallback for protocols
        that aren't coin tickers, e.g. "kamino", "jito-restaking")

    Protocol → coin/query mapping is best-effort: the OKX MCP indexes by
    coin tickers but many protocols don't have one. We try
    `news_get_by_coin(protocol)` first; if it returns nothing, fall back to
    `news_search(protocol)`. Either way, results are normalized to the
    trade-panel chunk shape via `build_news_chunk`.
    """

    def __init__(
        self,
        mcp_call: MCPCallable,
        *,
        prefer_coin_endpoint: bool = True,
    ) -> None:
        self._mcp_call = mcp_call
        self._prefer_coin = prefer_coin_endpoint

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

        articles: list[dict[str, Any]] = []

        # Try coin-endpoint first (works for tokens with a ticker —
        # most protocols have one)
        if self._prefer_coin:
            try:
                resp = await self._mcp_call(
                    "mcp__okx-agent-trade-kit__news_get_by_coin",
                    {"coin": proto.upper(), "limit": max_results},
                )
                articles = _normalize_articles(resp)
            except Exception as exc:
                _log.debug(
                    "okx_news.coin_endpoint_failed protocol=%s err=%s",
                    proto, exc,
                )

        # Fallback: keyword search for protocols without a clean ticker
        if not articles:
            try:
                resp = await self._mcp_call(
                    "mcp__okx-agent-trade-kit__news_search",
                    {"query": proto, "limit": max_results},
                )
                articles = _normalize_articles(resp)
            except Exception as exc:
                _log.warning(
                    "okx_news.search_endpoint_failed protocol=%s err=%s",
                    proto, exc,
                )

        if not articles:
            return []

        # Convert to chunks
        chunks: list[dict[str, Any]] = []
        for a in articles[:max_results]:
            headline = (a.get("title") or a.get("headline") or "").strip()
            body = (a.get("summary") or a.get("body") or a.get("description") or "").strip()
            if not headline:
                continue
            url = a.get("url") or a.get("link")
            published = a.get("published_ts") or a.get("publishedAt") or a.get("created_at")
            chunks.append(
                build_news_chunk(
                    headline=headline,
                    body=body,
                    url=url,
                    published_ts=published,
                    protocol=proto,
                )
            )
        return chunks


def _normalize_articles(resp: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """Pull the article list out of various OKX response shapes."""
    if isinstance(resp, list):
        return resp
    if not isinstance(resp, dict):
        return []
    # OKX MCP responses typically wrap data under "data" or "articles"
    for key in ("data", "articles", "news", "results", "items"):
        v = resp.get(key)
        if isinstance(v, list):
            return v
    return []


# Verify the adapter satisfies the protocol at import time (catches drift)
assert isinstance(OKXNewsProvider(mcp_call=lambda t, a: None), NewsProvider)  # type: ignore[arg-type]


__all__ = ["OKXNewsProvider", "MCPCallable"]
