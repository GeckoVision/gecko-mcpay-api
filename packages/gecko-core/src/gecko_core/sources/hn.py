"""Hacker News source via the Algolia HN Search API.

Always applies — HN signal (front-page chatter, Show HN traction, comment
volume) is broadly useful for any builder idea regardless of category.

Public, unauthenticated, rate-limit-tolerant. We still cache for 6h to
avoid pointlessly re-asking on retries within a session.
"""

from __future__ import annotations

from typing import Any

import httpx

from gecko_core.cache.mongo import cache_key, get_cached, set_cached
from gecko_core.sources import SourceResult

ALGOLIA_HN_SEARCH = "https://hn.algolia.com/api/v1/search"
CACHE_COLLECTION = "hn_cache"
CACHE_TTL_SECONDS = 6 * 60 * 60  # 6h
SNIPPET_CHARS = 280


def _normalize_idea(idea: str) -> str:
    return " ".join(idea.lower().split())


def _categories_csv(categories: set[str]) -> str:
    return ",".join(sorted(categories))


def _hit_to_chunk(hit: dict[str, Any]) -> dict[str, Any]:
    title = hit.get("title") or hit.get("story_title") or ""
    url = hit.get("url") or (
        f"https://news.ycombinator.com/item?id={hit['objectID']}" if hit.get("objectID") else ""
    )
    story_text = hit.get("story_text") or hit.get("comment_text") or ""
    snippet = (story_text or title)[:SNIPPET_CHARS]
    return {
        "title": title,
        "url": url,
        "points": hit.get("points"),
        "comments": hit.get("num_comments"),
        "created_at": hit.get("created_at"),
        "snippet": snippet,
    }


class HackerNewsSource:
    """Hacker News (Algolia) source — always applies."""

    name: str = "hn"

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        # Test seam: callers (or tests) may inject a pre-configured client
        # so respx mounts can intercept it. Production passes None and we
        # construct a short-lived client per fetch.
        self._client = http_client

    async def applies_to(self, *, categories: set[str]) -> bool:
        return True

    async def fetch(self, *, idea: str, categories: set[str]) -> SourceResult:
        idea_norm = _normalize_idea(idea)
        key = cache_key(self.name, idea_norm, _categories_csv(categories))
        cached = await get_cached(CACHE_COLLECTION, key)
        if cached is not None and isinstance(cached.get("hits"), list):
            return SourceResult(
                source_name=self.name,
                payload={"hits": cached["hits"], "cached": True},
                cost_usd=0.0,
            )

        params: dict[str, str | int] = {
            "query": idea_norm,
            "tags": "story",
            "hitsPerPage": 10,
        }
        try:
            if self._client is not None:
                resp = await self._client.get(ALGOLIA_HN_SEARCH, params=params, timeout=10.0)
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(ALGOLIA_HN_SEARCH, params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            return SourceResult(
                source_name=self.name,
                payload={},
                fired=False,
                error=f"{type(e).__name__}: {e}",
            )

        raw_hits = data.get("hits", []) if isinstance(data, dict) else []
        hits = [_hit_to_chunk(h) for h in raw_hits if isinstance(h, dict)]
        await set_cached(CACHE_COLLECTION, key, {"hits": hits}, ttl_seconds=CACHE_TTL_SECONDS)
        return SourceResult(
            source_name=self.name,
            payload={"hits": hits, "cached": False},
            cost_usd=0.0,
        )


__all__ = ["HackerNewsSource"]
