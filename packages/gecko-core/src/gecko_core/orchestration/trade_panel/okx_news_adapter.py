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

DEPLOYMENT GAP (2026-05-28): the deployed /trade_research handler in
packages/gecko-api/main.py runs in ECS WITHOUT an MCP transport — it
cannot invoke `mcp__okx-agent-trade-kit__*` tools. Wiring this provider
into the deployed handler requires EITHER:
  - A direct-HTTP OKX news adapter (needs public OKX REST endpoint URL
    + API key in SSM at /gecko-api/OKX_API_KEY + ECS task env wire), OR
  - An MCP-host sidecar in ECS (deferred infra lift).
Until that lands, the deployed Pattern E reachability for live news is
NOT satisfied. The local CLI / agent-runtime path (which DOES have MCP
transport) can pass `OKXNewsProvider(mcp_call=...)` today.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

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
                    proto,
                    exc,
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
                    proto,
                    exc,
                )

        if not articles:
            return []

        # Convert to chunks + fan-out to NewsSink (Sprint 28 S28-WIRE)
        chunks: list[dict[str, Any]] = []
        _sink = self._news_sink_lazy()
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
            # Sprint 28 (2026-06-01): persist to Mongo `market_news` for
            # the market_researcher voice (S28-AI-1) to read. Fire-and-
            # forget — sink swallows internally; outer try is belt-and-
            # suspenders so an ingest hiccup never breaks chunk
            # generation for the panel.
            #
            # ARCHITECTURE CAVEAT: this imports from contest_bot (a
            # downstream sibling). It's a CODE SMELL flagged for
            # staff-engineer per docs/methodology/market-news-collection.md
            # §7 — the clean fix is to promote NewsSink into gecko-core.
            # Shipping the pragmatic wire today; refactor when a second
            # provider adapter (CryptoPanic / Fed RSS) lands.
            if _sink is not None:
                try:
                    source_id = a.get("id") or a.get("article_id") or url or headline
                    tickers = (
                        [str(t).upper() for t in a.get("tickers")]
                        if isinstance(a.get("tickers"), list)
                        else ([proto.upper()] if proto else [])
                    )
                    _sink.record(
                        {
                            "source": "okx-news",
                            "source_id": str(source_id),
                            "url": url,
                            "headline": headline,
                            "body": body,
                            "published_at": published,
                            "tickers": tickers,
                        }
                    )
                except Exception as _wx:  # pragma: no cover
                    _log.warning("okx_news.sink_record_failed err=%s", _wx)
        return chunks

    def _news_sink_lazy(self) -> Any:
        """Lazy-construct NewsSink on first call. Cached per adapter
        instance. Returns None when MONGODB_URI is unset OR the sibling
        import fails (e.g. gecko-core consumed outside the monorepo)."""
        if hasattr(self, "_sink_cached"):
            return self._sink_cached
        try:
            # Sibling-package import. See ARCHITECTURE CAVEAT above.
            from contest_bot.decision_store.news_sink import NewsSink  # type: ignore[import-not-found]

            self._sink_cached = NewsSink.from_env()
        except Exception as exc:
            _log.info("okx_news.sink_unavailable err=%s", exc)
            self._sink_cached = None
        return self._sink_cached


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


__all__ = ["MCPCallable", "OKXNewsProvider"]
