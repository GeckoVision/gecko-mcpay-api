"""Reddit source via the public JSON API.

Public reads, no auth. We must set a descriptive User-Agent or Reddit
returns 429s aggressively.

Gating: only applies for builder categories where Reddit is a real signal
(crypto/defi/devtools/saas/regulated/hackathon-team). For each matching
category we hit a curated subreddit allowlist — capped at 3 subreddits
per call to bound latency and avoid drift toward "search every sub".
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from gecko_core.cache.mongo import cache_key, get_cached, set_cached
from gecko_core.sources import SourceResult

REDDIT_USER_AGENT = "Gecko/0.1 (gecko-mcpay-api)"
REDDIT_SEARCH_URL = "https://www.reddit.com/r/{subreddit}/search.json"
CACHE_COLLECTION = "reddit_cache"
CACHE_TTL_SECONDS = 6 * 60 * 60
SNIPPET_CHARS = 280
MAX_SUBREDDITS_PER_CALL = 3

# Category -> ordered subreddit allowlist. Order within each list is
# "most-relevant first" for that category; we trim globally to 3.
CATEGORY_SUBREDDITS: dict[str, list[str]] = {
    "crypto": ["CryptoCurrency", "solana", "ethereum", "defi"],
    "defi": ["defi", "CryptoCurrency", "ethereum", "solana"],
    "devtools": ["programming", "webdev", "devops"],
    "saas": ["SaaS", "startups", "Entrepreneur"],
    "regulated": ["fintech", "legaltech"],
    "hackathon-team": ["startups", "Entrepreneur", "programming"],
}

SUPPORTED_CATEGORIES: set[str] = set(CATEGORY_SUBREDDITS.keys())


def _normalize_idea(idea: str) -> str:
    return " ".join(idea.lower().split())


def _categories_csv(categories: set[str]) -> str:
    return ",".join(sorted(categories))


def _select_subreddits(categories: set[str]) -> list[str]:
    """Iterate categories in a stable order, taking subreddits round-robin
    so a multi-category idea spreads across categories rather than
    consuming all 3 slots from the first one."""
    matched = [c for c in sorted(categories) if c in CATEGORY_SUBREDDITS]
    seen: set[str] = set()
    ordered: list[str] = []
    # Round-robin pull
    idx = 0
    while len(ordered) < MAX_SUBREDDITS_PER_CALL and matched:
        progressed = False
        for cat in matched:
            subs = CATEGORY_SUBREDDITS[cat]
            if idx < len(subs):
                progressed = True
                sub = subs[idx]
                if sub not in seen:
                    seen.add(sub)
                    ordered.append(sub)
                    if len(ordered) >= MAX_SUBREDDITS_PER_CALL:
                        break
        if not progressed:
            break
        idx += 1
    return ordered


def _post_to_chunk(child: dict[str, Any]) -> dict[str, Any]:
    data = child.get("data", {}) if isinstance(child, dict) else {}
    permalink = data.get("permalink", "")
    url = f"https://www.reddit.com{permalink}" if permalink else data.get("url", "")
    selftext = data.get("selftext") or ""
    return {
        "title": data.get("title", ""),
        "url": url,
        "subreddit": data.get("subreddit", ""),
        "score": data.get("score"),
        "num_comments": data.get("num_comments"),
        "selftext_excerpt": selftext[:SNIPPET_CHARS],
    }


class RedditSource:
    """Reddit (public JSON) source — gated by category."""

    name: str = "reddit"

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def applies_to(self, *, categories: set[str]) -> bool:
        return bool(categories & SUPPORTED_CATEGORIES)

    async def _fetch_subreddit(
        self, client: httpx.AsyncClient, subreddit: str, idea: str
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {
            "q": idea,
            "limit": 10,
            "sort": "relevance",
            "restrict_sr": 1,
        }
        url = REDDIT_SEARCH_URL.format(subreddit=subreddit)
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        children = data.get("data", {}).get("children", []) if isinstance(data, dict) else []
        return [_post_to_chunk(c) for c in children if isinstance(c, dict)]

    async def fetch(self, *, idea: str, categories: set[str]) -> SourceResult:
        idea_norm = _normalize_idea(idea)
        subreddits = _select_subreddits(categories)
        if not subreddits:
            return SourceResult(source_name=self.name, payload={}, fired=False)

        key = cache_key(self.name, idea_norm, _categories_csv(categories))
        cached = await get_cached(CACHE_COLLECTION, key)
        if cached is not None and isinstance(cached.get("posts"), list):
            return SourceResult(
                source_name=self.name,
                payload={
                    "posts": cached["posts"],
                    "subreddits": cached.get("subreddits", subreddits),
                    "cached": True,
                },
                cost_usd=0.0,
            )

        headers = {"User-Agent": REDDIT_USER_AGENT}
        try:
            if self._client is not None:
                # Use injected client; trust caller set headers (tests do).
                tasks = [self._fetch_subreddit(self._client, sub, idea_norm) for sub in subreddits]
                results = await asyncio.gather(*tasks, return_exceptions=True)
            else:
                async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                    tasks = [self._fetch_subreddit(client, sub, idea_norm) for sub in subreddits]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
        except httpx.HTTPError as e:
            return SourceResult(
                source_name=self.name,
                payload={},
                fired=False,
                error=f"{type(e).__name__}: {e}",
            )

        posts: list[dict[str, Any]] = []
        errors: list[str] = []
        for sub, res in zip(subreddits, results, strict=True):
            if isinstance(res, BaseException):
                errors.append(f"{sub}: {type(res).__name__}: {res}")
                continue
            posts.extend(res)

        if not posts and errors:
            return SourceResult(
                source_name=self.name,
                payload={},
                fired=False,
                error="; ".join(errors),
            )

        await set_cached(
            CACHE_COLLECTION,
            key,
            {"posts": posts, "subreddits": subreddits},
            ttl_seconds=CACHE_TTL_SECONDS,
        )
        return SourceResult(
            source_name=self.name,
            payload={"posts": posts, "subreddits": subreddits, "cached": False},
            cost_usd=0.0,
        )


__all__ = ["SUPPORTED_CATEGORIES", "RedditSource"]
