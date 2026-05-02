"""twit.sh -> ProviderChunk adapter.

S17-WEDGE-WIRE-02 — Renders normalized tweet dicts (the shape returned
by ``_normalize_tweet`` in ``gecko_core.sources.twit_sh``) into shared
:class:`ProviderChunk` records so tweets reach the embedder + the
``chunks`` table the same way Tavily web content does.

Source-row strategy: per the design memo §1.4, twit.sh chunks land
under a single synthetic ``sources`` row per session
(``twitsh://session/<session_id>``). Each tweet is one chunk under that
source — the ``resource_id`` returned here is a session-level sentinel
that the dispatcher overrides via the ``synthetic_uri`` argument. The
``metadata`` dict carries the tweet URL so the citation renderer can
link out to the real tweet later (CITE-03 ticket).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from gecko_core.ingestion.types import ProviderChunk

_MAX_TEXT_CHARS = 6000

# twit.sh adapter sentinel — the dispatcher rewrites this to
# ``twitsh://session/<session_id>`` (one source row per session) but the
# adapter itself doesn't know the session id, so it returns a placeholder
# resource_id. ``ingest_provider_chunks`` ignores per-chunk ``resource_id``
# when given a single ``synthetic_uri`` and groups everything under it.
_SESSION_RESOURCE = "twitsh-session"


def _engagement_line(tweet: dict[str, Any]) -> str:
    """Compact engagement footer; omitted entirely when all metrics are 0."""
    eng = tweet.get("engagement") or {}
    if not isinstance(eng, dict):
        return ""
    likes = int(eng.get("likes") or 0)
    replies = int(eng.get("replies") or 0)
    reposts = int(eng.get("reposts") or 0)
    if not (likes or replies or reposts):
        return ""
    bits: list[str] = []
    if likes:
        bits.append(f"{likes} likes")
    if reposts:
        bits.append(f"{reposts} reposts")
    if replies:
        bits.append(f"{replies} replies")
    return "Engagement: " + ", ".join(bits)


def _render_text(tweet: dict[str, Any]) -> str:
    """Render a normalized tweet into embedding-friendly text.

    Layout: ``@handle (timestamp): body \\n\\n Engagement: ...``. Handle
    + timestamp lead because they discriminate the chunk against
    near-duplicate tweet bodies during retrieval; the body carries the
    actual claim; engagement footer is light social-proof signal.
    """
    body = str(tweet.get("text") or "").strip()
    if not body:
        return ""
    handle = str(tweet.get("author_handle") or "").strip()
    if handle and not handle.startswith("@"):
        handle = "@" + handle
    timestamp = str(tweet.get("created_at") or "").strip()

    header = handle
    if timestamp:
        header = f"{header} ({timestamp})" if header else f"({timestamp})"

    parts: list[str] = []
    if header:
        parts.append(f"{header}:\n{body}")
    else:
        parts.append(body)
    eng = _engagement_line(tweet)
    if eng:
        parts.append(eng)

    text = "\n\n".join(parts).strip()
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS]
    return text


def to_chunks(payload: Sequence[dict[str, Any]]) -> list[ProviderChunk]:
    """Convert normalized tweet dicts into ProviderChunk records.

    One tweet == one ProviderChunk. ``chunk_index`` is the position in
    the input list; the dispatcher groups all chunks under one synthetic
    ``twitsh://session/<session_id>`` source row.
    """
    out: list[ProviderChunk] = []
    for idx, tweet in enumerate(payload):
        if not isinstance(tweet, dict):
            continue
        text = _render_text(tweet)
        if not text:
            continue
        out.append(
            ProviderChunk(
                resource_id=_SESSION_RESOURCE,
                chunk_index=idx,
                text=text,
                metadata={
                    "tweet_url": str(tweet.get("url") or ""),
                    "author_handle": str(tweet.get("author_handle") or ""),
                    "created_at": str(tweet.get("created_at") or ""),
                    "engagement": dict(tweet.get("engagement") or {}),
                },
            )
        )
    return out


__all__ = ["to_chunks"]
