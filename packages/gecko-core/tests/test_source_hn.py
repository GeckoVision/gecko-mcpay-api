"""Tests for the Hacker News source.

We patch the cache helpers (so tests don't require Mongo) and use respx
to intercept the Algolia API call.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from gecko_core.sources.hn import ALGOLIA_HN_SEARCH, HackerNewsSource

ALGOLIA_FIXTURE: dict[str, Any] = {
    "hits": [
        {
            "objectID": "11111",
            "title": "Show HN: A neat tool for builders",
            "url": "https://example.com/show",
            "points": 142,
            "num_comments": 38,
            "created_at": "2025-12-01T10:00:00Z",
            "story_text": "We built this because " + ("x" * 400),
        },
        {
            "objectID": "22222",
            "title": "Ask HN: How do you ship faster?",
            "url": None,
            "points": 88,
            "num_comments": 120,
            "created_at": "2025-11-28T08:00:00Z",
            "story_text": None,
        },
    ],
    "nbHits": 2,
}


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Default: cache is empty and writes are tracked, not persisted."""
    state: dict[str, Any] = {"store": {}, "set_calls": []}

    async def fake_get(coll: str, key: str) -> dict[str, Any] | None:
        return state["store"].get((coll, key))

    async def fake_set(coll: str, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        state["set_calls"].append((coll, key, value, ttl_seconds))
        state["store"][(coll, key)] = value

    monkeypatch.setattr("gecko_core.sources.hn.get_cached", fake_get)
    monkeypatch.setattr("gecko_core.sources.hn.set_cached", fake_set)
    return state


async def test_fetch_returns_citation_shaped_hits() -> None:
    src = HackerNewsSource()
    async with respx.mock(assert_all_called=True) as mock:
        mock.get(ALGOLIA_HN_SEARCH).mock(return_value=httpx.Response(200, json=ALGOLIA_FIXTURE))
        result = await src.fetch(idea="builder bootstrap", categories=set())

    assert result.fired is True
    assert result.source_name == "hn"
    hits = result.payload["hits"]
    assert len(hits) == 2

    h0 = hits[0]
    assert h0["title"] == "Show HN: A neat tool for builders"
    assert h0["url"] == "https://example.com/show"
    assert h0["points"] == 142
    assert h0["comments"] == 38
    assert h0["created_at"] == "2025-12-01T10:00:00Z"
    assert len(h0["snippet"]) <= 280
    assert h0["snippet"].startswith("We built this because")

    # Falls back to HN item URL when `url` is null.
    h1 = hits[1]
    assert h1["url"] == "https://news.ycombinator.com/item?id=22222"
    # snippet falls back to title when no story_text
    assert h1["snippet"] == "Ask HN: How do you ship faster?"


async def test_applies_to_is_always_true() -> None:
    src = HackerNewsSource()
    assert await src.applies_to(categories=set()) is True
    assert await src.applies_to(categories={"crypto"}) is True
    assert await src.applies_to(categories={"random"}) is True


async def test_http_error_returns_unfired_with_error() -> None:
    src = HackerNewsSource()
    async with respx.mock() as mock:
        mock.get(ALGOLIA_HN_SEARCH).mock(return_value=httpx.Response(500))
        result = await src.fetch(idea="x", categories=set())
    assert result.fired is False
    assert result.error is not None


async def test_second_call_within_ttl_hits_cache(_no_cache: dict[str, Any]) -> None:
    src = HackerNewsSource()
    async with respx.mock() as mock:
        route = mock.get(ALGOLIA_HN_SEARCH).mock(
            return_value=httpx.Response(200, json=ALGOLIA_FIXTURE)
        )
        first = await src.fetch(idea="same idea", categories={"saas"})
        second = await src.fetch(idea="same idea", categories={"saas"})

    assert route.call_count == 1, "second call should have hit the cache"
    assert first.payload.get("cached") is False
    assert second.payload.get("cached") is True
    assert second.payload["hits"] == first.payload["hits"]
    # exactly one set_cached call
    assert len(_no_cache["set_calls"]) == 1
