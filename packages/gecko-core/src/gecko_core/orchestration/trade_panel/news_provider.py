"""News-provider abstraction for the trade panel — Sprint 18 (2026-05-28).

Per the 2026-05-28 3-specialist Sprint 18 design review (ai-ml-engineer +
trading-strategist + product-manager):

  > "Wire okx-news MCP into the oracle envelope. Free win — we already
  >  have it; nothing reads it. Unblocks catalyst voice + research voice
  >  Tests can't proceed until it's wired."

The sentiment_analyst persona in `_default_prompts.json` already says it
reads "news headlines, X/Twitter chatter, Discord/governance forum posts."
But until this module, those chunks had to come from the static corpus
only — no LIVE news feed.

This module adds a thin `NewsProvider` protocol + a default no-op
implementation. Callers (agent runtime, CLI, MCP server) can pass an
adapter; the trade_panel doesn't hard-depend on OKX or any other source.

PATTERN (per CLAUDE.md "Pattern E reachability"):
  The provider is injected via the same path as `history_source` for
  backtesting (existing parameter on `run_trade_panel_with_retrieval`).
  Chunks are merged in-memory at the exact same line as
  `reconstruct_pool_chunks` — both feed into the panel via the SAME
  retrieved_chunks list, so `_format_chunks` renders them identically,
  the citation breadth directive applies uniformly, and the partition
  helper places them into evidence_citations (not framework_context).

NEWS CHUNK SHAPE (must match the corpus chunk shape):
    {
        "id": "okx-news-<headline-hash>",
        "text": "<headline>. <body up to ~600 chars>",
        "source": "okx-news",
        "provider_kind": "okx_news_live",     # for partition_emitted_citations
        "url": "<canonical news URL>",
        "published_ts": "<ISO UTC>",
        "protocol": "<protocol-tag>",         # for protocol-equality matching
        "freshness_tier": "live_only",        # not in static corpus
    }
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol, runtime_checkable

_log = logging.getLogger(__name__)


# Maximum news chunks to merge per panel call. Keeps the round-1 context
# budget bounded; sentiment_analyst doesn't need 50 headlines, ~5 covers
# the dominant narrative for any protocol.
_DEFAULT_MAX_NEWS_CHUNKS = 5


@runtime_checkable
class NewsProvider(Protocol):
    """Provider for live news context to inject into the trade panel.

    Implementations:
      - `NullNewsProvider` — default; returns empty list (no behavior change)
      - `OKXNewsProvider` — wraps okx-agent-trade-kit news_* MCP tools
      - (future) `TavilyNewsProvider`, `ExaSearchNewsProvider`, etc

    The trade_panel does NOT depend on any provider — it only knows the
    protocol shape. Tests pass a fake adapter; production wires the OKX one.
    """

    async def fetch_news_chunks(
        self,
        protocol: str,
        *,
        max_results: int = _DEFAULT_MAX_NEWS_CHUNKS,
        as_of: Any = None,
    ) -> list[dict[str, Any]]:
        """Return up to max_results news chunks for the given protocol.

        Each chunk MUST match the panel's corpus chunk shape (see module
        docstring). Implementations should:
          - Filter to last 72h (rolling window — sentiment_analyst needs recency)
          - Truncate body to ≤600 chars (keep total round-1 budget reasonable)
          - Set `provider_kind="okx_news_live"` (or equivalent) so the
            partition helper places them into evidence_citations
          - Set `freshness_tier="live_only"` so the retrieval gate doesn't
            try to find them in the static corpus

        Returns an empty list if no news is available (always-safe fallback).
        """
        ...


class NullNewsProvider:
    """No-op default. Returns no news chunks. Drop-in for tests + when no
    provider is wired."""

    async def fetch_news_chunks(
        self,
        protocol: str,
        *,
        max_results: int = _DEFAULT_MAX_NEWS_CHUNKS,
        as_of: Any = None,
    ) -> list[dict[str, Any]]:
        return []


def _chunk_id_for(headline: str, url: str | None) -> str:
    """Stable id from headline + URL — dedupe across runs."""
    key = (url or "") + "|" + headline
    return "okx-news-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def build_news_chunk(
    headline: str,
    body: str,
    *,
    source: str = "okx-news",
    url: str | None = None,
    published_ts: str | None = None,
    protocol: str | None = None,
    provider_kind: str = "okx_news_live",
    body_char_cap: int = 600,
) -> dict[str, Any]:
    """Build a chunk in the trade-panel's expected shape.

    Use this from provider implementations to guarantee shape conformance.
    """
    truncated = body.strip()
    if len(truncated) > body_char_cap:
        truncated = truncated[:body_char_cap] + "…"
    text_body = f"{headline.strip()}. {truncated}" if truncated else headline.strip()
    return {
        "id": _chunk_id_for(headline, url),
        "text": text_body,
        "source": source,
        "provider_kind": provider_kind,
        "url": url or "",
        "published_ts": published_ts or datetime.now(timezone.utc).isoformat(),
        "protocol": (protocol or "").lower(),
        "freshness_tier": "live_only",
    }


async def merge_news_chunks(
    chunks: Iterable[dict[str, Any]],
    *,
    provider: NewsProvider | None,
    protocol: str,
    max_results: int = _DEFAULT_MAX_NEWS_CHUNKS,
    as_of: Any = None,
) -> list[dict[str, Any]]:
    """Convenience helper for callers in run_trade_panel_with_retrieval.

    Merges live news chunks onto an existing chunks list. If provider is
    None (default), returns the input unchanged — zero behavior delta for
    existing callers. Used by the panel wrapper at the same merge point
    as the backtest reconstruction.

    Returns the combined list. Order: corpus + news (news goes at the end
    so corpus chunk indices stay stable across calls with/without news).
    """
    existing = list(chunks)
    if provider is None:
        return existing
    try:
        news = await provider.fetch_news_chunks(
            protocol, max_results=max_results, as_of=as_of
        )
    except Exception as exc:  # pragma: no cover — defensive
        _log.warning(
            "trade_panel.news_provider.error protocol=%s err=%s",
            protocol, exc,
        )
        return existing
    if not news:
        return existing
    # Dedupe: if a news chunk's id already exists in the static corpus,
    # skip it. Corpus wins (it's been through retrieval gate + reranking).
    existing_ids = {c.get("id") for c in existing if c.get("id")}
    merged_news = [c for c in news if c.get("id") not in existing_ids]
    _log.info(
        "trade_panel.news_merge protocol=%s corpus=%d news_fetched=%d news_added=%d",
        protocol, len(existing), len(news), len(merged_news),
    )
    return existing + merged_news


__all__ = [
    "NewsProvider",
    "NullNewsProvider",
    "build_news_chunk",
    "merge_news_chunks",
]
