"""Judge-corpus Mongo persistence (S21-JUDGE-CORPUS-01).

Owns the ``gecko_rag.judge_corpus`` collection. Each document is one
tweet by one named judge, with embedding + provenance metadata. The
unique key is ``(judge_handle, tweet_id)`` so re-ingestion is
idempotent.

Why a dedicated collection (not ``chunks``):

  ``chunks`` requires ``session_id`` and is owned by the per-research
  ingestion pipeline. The judge corpus is operator-driven and outlives
  any session — fitting it into chunks would require either a sentinel
  session UUID (collides with session GC) or making session_id
  nullable (broad blast radius). One small collection is the cheaper
  call.

The ``ProviderKind`` Literal still grows ``judge_corpus`` — that
records the taxonomy and lets future RAG paths surface judge tweets
alongside web/twitsh chunks if we decide to retrieve from the corpus
during research.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from gecko_core.db.mongo import _db, mongo_uri
from gecko_core.sources.twit_sh import TwitshSource
from gecko_core.sources.twit_sh.embed_adapter import _render_text

logger = logging.getLogger(__name__)

JUDGE_CORPUS_COLLECTION = "judge_corpus"
EMBED_DIM = 1024


@dataclass
class JudgeTweet:
    """One stored tweet from a named judge.

    ``embedding`` is optional on read paths that don't need vectors
    (e.g. the synth pass which works on text alone).
    """

    judge_handle: str
    tweet_id: str
    text: str
    tweet_url: str
    posted_at: str
    likes: int = 0
    replies: int = 0
    reposts: int = 0
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    embedding: list[float] | None = None
    provider_kind: str = "judge_corpus"


def _judge_collection() -> Any | None:
    """Return the motor collection for the judge corpus, or None.

    Mirrors ``chunks_collection`` shape — None when Mongo isn't
    configured. Callers in CLI surfaces should error explicitly so the
    operator knows their env is missing rather than silently no-oping.
    """
    if not mongo_uri():
        return None
    db = _db()
    if db is None:
        return None
    return db[JUDGE_CORPUS_COLLECTION]


async def _ensure_index() -> None:
    """Create the unique (judge_handle, tweet_id) index if absent."""
    coll = _judge_collection()
    if coll is None:
        return
    try:
        await coll.create_index(
            [("judge_handle", 1), ("tweet_id", 1)],
            unique=True,
            name="judge_corpus_handle_tweet_id_uniq",
        )
    except Exception as exc:  # pragma: no cover — best-effort
        logger.warning("judge_corpus.index_create_failed: %s", exc)


async def ingest_judge(
    handle: str,
    *,
    max_calls: int = 5,
    twitsh: TwitshSource | None = None,
    embed: bool = True,
) -> tuple[int, int, float]:
    """Fetch tweets for ``handle`` and write to Mongo. Idempotent.

    Returns ``(new_inserted, corpus_total, spent_usd)``.

    ``embed=False`` is used by tests that don't have an OpenAI key —
    the corpus document is still written, just without an embedding
    vector. Live runs always embed at write time so similarity queries
    later are free.
    """
    clean = handle.lstrip("@").lower()
    src = twitsh or TwitshSource()
    try:
        tweets, spent = await src.fetch_user_tweets(clean, max_calls=max_calls)
    finally:
        # If we created the source ourselves, close its http client.
        if twitsh is None:
            await src.aclose()

    coll = _judge_collection()
    if coll is None:
        # Still return fetch results so the CLI can render something useful;
        # but flag zero inserts so the operator notices their env is wrong.
        logger.warning("judge_corpus.mongo_unavailable; not persisting")
        return 0, 0, spent

    await _ensure_index()

    # Optionally embed text bodies in one batch.
    embeddings: list[list[float]] = []
    if embed and tweets:
        try:
            from gecko_core.ingestion.embedder import embed as embed_texts

            texts = [_render_text(t) or t.get("text", "") for t in tweets]
            vectors, _tokens = await embed_texts(texts)
            embeddings = vectors
        except Exception as exc:
            logger.warning("judge_corpus.embed_failed: %s", exc)
            embeddings = []

    now = datetime.now(UTC)
    new_inserted = 0
    for idx, t in enumerate(tweets):
        tid = str(t.get("id_str") or t.get("url") or "")
        if not tid:
            continue
        doc: dict[str, Any] = {
            "judge_handle": clean,
            "tweet_id": tid,
            "text": str(t.get("text") or ""),
            "tweet_url": str(t.get("url") or ""),
            "posted_at": str(t.get("created_at") or ""),
            "likes": int((t.get("engagement") or {}).get("likes") or 0),
            "replies": int((t.get("engagement") or {}).get("replies") or 0),
            "reposts": int((t.get("engagement") or {}).get("reposts") or 0),
            "captured_at": now,
            "provider_kind": "judge_corpus",
        }
        if idx < len(embeddings) and len(embeddings[idx]) == EMBED_DIM:
            doc["embedding"] = embeddings[idx]
        try:
            await coll.insert_one(doc)
            new_inserted += 1
        except Exception as exc:
            # 11000 duplicate key → already stored, skip silently.
            code = getattr(exc, "code", None)
            details = getattr(exc, "details", None)
            is_dup = code == 11000 or (isinstance(details, dict) and details.get("code") == 11000)
            if not is_dup:
                logger.warning("judge_corpus.insert_failed tweet_id=%s: %s", tid, exc)

    total = await coll.count_documents({"judge_handle": clean})
    return new_inserted, int(total), spent


async def load_corpus(handle: str, *, limit: int = 100) -> list[JudgeTweet]:
    """Return stored tweets for ``handle``, newest-first by posted_at.

    Empty list when Mongo isn't configured or the handle has no rows —
    callers must distinguish "no corpus" from "Mongo down" themselves
    if it matters; the synth path treats both as "insufficient corpus".
    """
    clean = handle.lstrip("@").lower()
    coll = _judge_collection()
    if coll is None:
        return []
    out: list[JudgeTweet] = []
    cursor = coll.find({"judge_handle": clean}).sort("posted_at", -1).limit(limit)
    async for doc in cursor:
        out.append(
            JudgeTweet(
                judge_handle=clean,
                tweet_id=str(doc.get("tweet_id") or ""),
                text=str(doc.get("text") or ""),
                tweet_url=str(doc.get("tweet_url") or ""),
                posted_at=str(doc.get("posted_at") or ""),
                likes=int(doc.get("likes") or 0),
                replies=int(doc.get("replies") or 0),
                reposts=int(doc.get("reposts") or 0),
                captured_at=doc.get("captured_at") or datetime.now(UTC),
                embedding=doc.get("embedding"),
            )
        )
    return out


async def delete_corpus(handle: str) -> int:
    """Drop every stored tweet for ``handle``. Returns the deleted count.

    Used by tests to keep runs hermetic; not exposed via CLI on
    purpose — operator-facing "wipe a judge" is a footgun.
    """
    clean = handle.lstrip("@").lower()
    coll = _judge_collection()
    if coll is None:
        return 0
    res = await coll.delete_many({"judge_handle": clean})
    return int(res.deleted_count or 0)


__all__ = [
    "JUDGE_CORPUS_COLLECTION",
    "JudgeTweet",
    "delete_corpus",
    "ingest_judge",
    "load_corpus",
]
