"""Tests for the Reddit source."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from gecko_core.sources.reddit import (
    MAX_SUBREDDITS_PER_CALL,
    RedditSource,
    _select_subreddits,
)


def _reddit_fixture(subreddit: str) -> dict[str, Any]:
    return {
        "data": {
            "children": [
                {
                    "data": {
                        "title": f"[{subreddit}] How to ship fast",
                        "permalink": f"/r/{subreddit}/comments/abc/how_to_ship_fast/",
                        "url": f"https://www.reddit.com/r/{subreddit}/comments/abc/",
                        "subreddit": subreddit,
                        "score": 321,
                        "num_comments": 45,
                        "selftext": "Long story short " + ("y" * 400),
                    }
                },
                {
                    "data": {
                        "title": f"[{subreddit}] Another post",
                        "permalink": f"/r/{subreddit}/comments/def/another_post/",
                        "url": "",
                        "subreddit": subreddit,
                        "score": 10,
                        "num_comments": 2,
                        "selftext": "",
                    }
                },
            ]
        }
    }


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"store": {}, "set_calls": []}

    async def fake_get(coll: str, key: str) -> dict[str, Any] | None:
        return state["store"].get((coll, key))

    async def fake_set(coll: str, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        state["set_calls"].append((coll, key, value, ttl_seconds))
        state["store"][(coll, key)] = value

    monkeypatch.setattr("gecko_core.sources.reddit.get_cached", fake_get)
    monkeypatch.setattr("gecko_core.sources.reddit.set_cached", fake_set)
    return state


async def test_applies_to_off_list_categories_returns_false() -> None:
    src = RedditSource()
    assert await src.applies_to(categories=set()) is False
    assert await src.applies_to(categories={"random", "weather"}) is False
    assert await src.applies_to(categories={"music"}) is False


async def test_applies_to_supported_categories() -> None:
    src = RedditSource()
    for cat in ["crypto", "defi", "devtools", "saas", "regulated", "hackathon-team"]:
        assert await src.applies_to(categories={cat}) is True, cat


def test_select_subreddits_capped_at_three() -> None:
    # All categories at once -> still capped at 3.
    chosen = _select_subreddits(
        {"crypto", "defi", "devtools", "saas", "regulated", "hackathon-team"}
    )
    assert len(chosen) == MAX_SUBREDDITS_PER_CALL == 3


async def test_fetch_hits_at_most_three_subreddits() -> None:
    src = RedditSource(http_client=httpx.AsyncClient())
    try:
        async with respx.mock(assert_all_called=False) as mock:
            # Mount a catch-all for any subreddit URL pattern.
            route = mock.get(url__regex=r"https://www\.reddit\.com/r/[^/]+/search\.json").mock(
                side_effect=lambda req: httpx.Response(
                    200, json=_reddit_fixture(req.url.path.split("/")[2])
                )
            )
            result = await src.fetch(
                idea="solana defi yield",
                categories={
                    "crypto",
                    "defi",
                    "devtools",
                    "saas",
                    "regulated",
                    "hackathon-team",
                },
            )
        assert result.fired is True
        assert route.call_count <= MAX_SUBREDDITS_PER_CALL
        assert len(result.payload["subreddits"]) <= MAX_SUBREDDITS_PER_CALL
    finally:
        await src._client.aclose()  # type: ignore[union-attr]


async def test_fetch_returns_citation_shape() -> None:
    src = RedditSource(http_client=httpx.AsyncClient())
    try:
        async with respx.mock(assert_all_called=False) as mock:
            mock.get(url__regex=r"https://www\.reddit\.com/r/[^/]+/search\.json").mock(
                side_effect=lambda req: httpx.Response(
                    200, json=_reddit_fixture(req.url.path.split("/")[2])
                )
            )
            result = await src.fetch(idea="defi yield aggregator", categories={"defi"})
        posts = result.payload["posts"]
        assert len(posts) >= 1
        p0 = posts[0]
        assert p0["title"]
        assert p0["url"].startswith("https://www.reddit.com/")
        assert p0["subreddit"]
        assert isinstance(p0["score"], int)
        assert isinstance(p0["num_comments"], int)
        assert len(p0["selftext_excerpt"]) <= 280
    finally:
        await src._client.aclose()  # type: ignore[union-attr]


async def test_gated_when_no_supported_categories() -> None:
    src = RedditSource()
    result = await src.fetch(idea="x", categories={"music"})
    assert result.fired is False


async def test_second_call_within_ttl_hits_cache(_no_cache: dict[str, Any]) -> None:
    src = RedditSource(http_client=httpx.AsyncClient())
    try:
        async with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__regex=r"https://www\.reddit\.com/r/[^/]+/search\.json").mock(
                side_effect=lambda req: httpx.Response(
                    200, json=_reddit_fixture(req.url.path.split("/")[2])
                )
            )
            first = await src.fetch(idea="same idea", categories={"saas"})
            calls_after_first = route.call_count
            second = await src.fetch(idea="same idea", categories={"saas"})
        assert first.payload.get("cached") is False
        assert second.payload.get("cached") is True
        # No additional HTTP calls on the second invocation.
        assert route.call_count == calls_after_first
        assert len(_no_cache["set_calls"]) == 1
    finally:
        await src._client.aclose()  # type: ignore[union-attr]
