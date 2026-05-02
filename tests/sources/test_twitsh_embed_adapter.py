"""S17-WEDGE-WIRE-02 — twit.sh embed adapter unit test."""

from __future__ import annotations

from gecko_core.sources.twit_sh.embed_adapter import to_chunks


def _tweet(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "text": "agentic-economy is going to eat search.",
        "author_handle": "@aeyakovenko",
        "url": "https://x.com/aeyakovenko/status/123",
        "engagement": {"likes": 200, "replies": 12, "reposts": 40},
        "created_at": "2026-04-29T12:00:00Z",
    }
    base.update(overrides)
    return base


def test_to_chunks_renders_handle_timestamp_body_engagement() -> None:
    out = to_chunks([_tweet()])

    assert len(out) == 1
    pc = out[0]
    assert pc.resource_id  # session-level sentinel; non-empty
    assert pc.chunk_index == 0
    assert "@aeyakovenko" in pc.text
    assert "(2026-04-29T12:00:00Z)" in pc.text
    assert "agentic-economy is going to eat search." in pc.text
    assert "Engagement:" in pc.text
    assert "200 likes" in pc.text
    assert "40 reposts" in pc.text
    assert pc.metadata["tweet_url"] == "https://x.com/aeyakovenko/status/123"


def test_to_chunks_drops_empty_body() -> None:
    out = to_chunks([{"text": "", "author_handle": "@x"}])
    assert out == []


def test_to_chunks_omits_engagement_when_all_zero() -> None:
    tweet = _tweet(engagement={"likes": 0, "replies": 0, "reposts": 0})
    out = to_chunks([tweet])
    assert "Engagement:" not in out[0].text


def test_to_chunks_assigns_sequential_indices_for_session_grouping() -> None:
    out = to_chunks([_tweet(), _tweet(text="another point worth citing")])
    assert [pc.chunk_index for pc in out] == [0, 1]
