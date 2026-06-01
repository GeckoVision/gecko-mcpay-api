"""Best-effort sink: live market-news items → Mongo `market_news` collection.

Design ref:
    private/strategy/2026-05-30-mongo-behavior-news-collections-DESIGN.md
    private/strategy/2026-05-31-data-engineer-bot-behaviors-audit.md

Why a SINK, not a mutation of the existing trade-panel `NewsProvider`:

The `NewsProvider` abstraction at
`packages/gecko-core/src/gecko_core/orchestration/trade_panel/news_provider.py`
already fetches news chunks for in-process consumption by the trade panel
(Sprint 18-2, commit `be2c802`). We do NOT touch that path.

Instead, we add a fan-out sink the caller (trade panel call site, future
batch puller, future market_researcher voice) can opt into. Same shape as
`decision_store.behavior_sink.BehaviorSink` — fire-and-forget, best-effort,
never raises into the caller.

Shape:

    sink = NewsSink.from_env()           # None if MONGODB_URI unset
    sink.record(news_doc)                # dict: see build_news_doc

Idempotent: keyed on `news_id` (unique). Deterministic from
`sha256(source|source_id|ts_iso)` when caller doesn't supply it.
Best-effort: NEVER raises into the caller (mirrors `behavior_sink._do_upsert`).
Async fire-and-forget: writes happen on the sink's own thread pool so the
caller returns immediately.

Embedding fields are LEFT ABSENT in v1, per design doc §5 + the
`behavior_sink.py:147` precedent. A later script (one-shot or cron) batch-
embeds Voyage `voyage-finance-2` (1024-dim) and patches via
`patch_embedding()`. Founder gates the Voyage spend on news — see
`project_2026_05_30_overnight_app_endstate`.

Env:
    MONGODB_URI         — Atlas connection string (required to enable)
    MONGODB_DB          — defaults to "gecko_cache" (matches founder's env)
    MONGODB_NEWS_COLL   — defaults to "market_news"
    GECKO_NEWS_SINK     — "0" disables even if URI is set (kill switch)
"""

from __future__ import annotations

import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("decision_store.news_sink")

DEFAULT_DB = "gecko_cache"
DEFAULT_COLLECTION = "market_news"
SCHEMA_V = 1

REQUIRED_FIELDS = ("source", "headline")

_EXECUTOR: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(
            max_workers=int(os.environ.get("GECKO_NEWS_SINK_WORKERS", "2")),
            thread_name_prefix="news-sink",
        )
    return _EXECUTOR


def _sink_enabled() -> bool:
    return os.environ.get("GECKO_NEWS_SINK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _now_dt() -> datetime:
    return datetime.now(UTC)


def _as_iso(value: Any) -> str | None:
    """Best-effort normalize a datetime / ISO string to ISO-8601 UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def compute_news_id(
    source: str,
    source_id: str | None,
    ts: Any,
    *,
    url: str | None = None,
    headline: str | None = None,
) -> str:
    """Deterministic news_id from the de-dupe key.

    Preferred key: `(source, source_id, ts)`. Falls back to `(source, url)`
    if source_id is missing (some RSS feeds don't expose stable IDs), then
    `(source, headline, ts)` as last resort. Always 64-char sha256 hex.
    """
    parts: tuple[str, ...]
    if source_id:
        parts = (source, source_id, _as_iso(ts) or "")
    elif url:
        parts = (source, url)
    else:
        parts = (source, headline or "", _as_iso(ts) or "")
    key = "|".join(p for p in parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build_news_doc(
    raw: dict,
    *,
    schema_v: int = SCHEMA_V,
) -> dict:
    """Project a raw news payload into the `market_news` BSON shape.

    Pure function. No I/O. Deterministic. Safe to call from tests.

    The raw dict can come from any provider — RSS, CryptoPanic, OKX news,
    Tavily, etc. Required: `source`, `headline`. Everything else defaults
    to neutral/absent. We do NOT raise — downstream upsert enforces shape
    via the unique index on `news_id`.

    Embedding fields are LEFT ABSENT (not set to None) so the future
    embedder pass can `$exists`-check them.
    """
    missing = [k for k in REQUIRED_FIELDS if not raw.get(k)]
    if missing:
        raise ValueError(f"news_doc missing required fields: {missing}")

    source = str(raw["source"])
    headline = str(raw["headline"]).strip()
    source_id = raw.get("source_id") or raw.get("id")
    url = raw.get("url")
    published_at = _as_iso(raw.get("published_at") or raw.get("ts"))
    fetched_at = _as_iso(raw.get("fetched_at")) or _now_dt().isoformat()

    news_id = raw.get("news_id") or compute_news_id(
        source,
        source_id,
        published_at or fetched_at,
        url=url,
        headline=headline,
    )

    body = raw.get("body") or ""
    if len(body) > 8000:
        body = body[:8000]

    tickers = raw.get("tickers") or []
    if isinstance(tickers, str):
        tickers = [tickers]
    tickers = [str(t).upper() for t in tickers if t]

    classification = raw.get("classification") or None
    if classification is not None and not isinstance(classification, dict):
        classification = None

    doc: dict[str, Any] = {
        "news_id": news_id,
        "source": source,
        "source_id": source_id,
        "url": url,
        "fetched_at": fetched_at,
        "published_at": published_at,
        "headline": headline,
        "body": body,
        "tickers": tickers,
        "classification": classification,
        "schema_v": schema_v,
        "ingested_at": _now_dt(),
    }
    # Embedding is patched later. Carry through if a caller already attached.
    if raw.get("embedding"):
        doc["embedding"] = raw["embedding"]
        doc["embedding_model"] = raw.get("embedding_model")
        doc["embedding_summary"] = raw.get("embedding_summary")
        doc["embedded_at"] = _now_dt()
    return doc


class NewsSink:
    """Best-effort writer to Mongo `market_news`.

    Callers invoke `record(news_doc_dict)`. All Mongo I/O happens on the
    sink's own thread pool — caller loop never blocks on Atlas latency.
    """

    def __init__(
        self,
        collection: Any,
        *,
        async_writes: bool = True,
    ) -> None:
        self._coll = collection
        self._async = async_writes

    @classmethod
    def from_env(cls, **kwargs: Any) -> NewsSink | None:
        """Construct from MONGODB_URI. Returns None if Mongo is unreachable
        or the sink is disabled. Callers treat None as 'in-process only'."""
        if not _sink_enabled():
            logger.info("news_sink: disabled via GECKO_NEWS_SINK=0")
            return None
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            logger.info("news_sink: MONGODB_URI unset; sink not enabled")
            return None
        try:
            from pymongo import MongoClient

            db = MongoClient(uri, serverSelectionTimeoutMS=3000)[
                os.environ.get("MONGODB_DB", DEFAULT_DB)
            ]
            coll = db[os.environ.get("MONGODB_NEWS_COLL", DEFAULT_COLLECTION)]
        except Exception as exc:
            logger.warning("news_sink: Mongo unavailable (%s); sink disabled", exc)
            return None
        return cls(coll, **kwargs)

    def record(self, news: dict) -> None:
        """Project + upsert. Fire-and-forget. Never raises."""
        try:
            doc = build_news_doc(news)
        except Exception as exc:
            logger.warning("news_sink: build failed (%s); skipping", exc)
            return
        news_id = doc.get("news_id")
        if not news_id:
            logger.debug("news_sink: skip — no news_id")
            return

        if self._async:
            try:
                _get_executor().submit(self._do_upsert, news_id, doc)
            except Exception as exc:
                logger.warning("news_sink: submit failed (%s); falling back sync", exc)
                self._do_upsert(news_id, doc)
        else:
            self._do_upsert(news_id, doc)

    def patch_embedding(
        self,
        news_id: str,
        vector: list[float] | None,
        model: str,
        summary: str,
    ) -> None:
        """Patch the embedding fields after a batch-embed pass.

        Vector may be None — we still store model + summary so the next
        embed pass can tell "embed was attempted, returned nothing" apart
        from "never embedded."
        """
        if not news_id:
            return
        patch: dict[str, Any] = {
            "embedding_model": model,
            "embedding_summary": summary,
            "embedded_at": _now_dt(),
        }
        if vector is not None:
            patch["embedding"] = vector

        def _do() -> None:
            try:
                self._coll.update_one({"news_id": news_id}, {"$set": patch}, upsert=False)
            except Exception as exc:
                logger.warning("news_sink: embed patch failed (%s)", exc)

        if self._async:
            try:
                _get_executor().submit(_do)
            except Exception:
                _do()
        else:
            _do()

    def patch_classification(self, news_id: str, classification: dict) -> None:
        """Patch the LLM classification block after a classifier pass."""
        if not news_id:
            return

        def _do() -> None:
            try:
                self._coll.update_one(
                    {"news_id": news_id},
                    {"$set": {"classification": classification}},
                    upsert=False,
                )
            except Exception as exc:
                logger.warning("news_sink: classification patch failed (%s)", exc)

        if self._async:
            try:
                _get_executor().submit(_do)
            except Exception:
                _do()
        else:
            _do()

    def _do_upsert(self, news_id: str, doc: dict) -> None:
        try:
            self._coll.update_one(
                {"news_id": news_id},
                {"$set": doc, "$setOnInsert": {"created_at": _now_dt()}},
                upsert=True,
            )
        except Exception as exc:
            logger.warning(
                "news_sink: upsert failed (%s); in-process panel chunks remain unaffected",
                exc,
            )


def shutdown(*, wait: bool = True) -> None:
    """Drain the sink executor. Idempotent."""
    global _EXECUTOR
    if _EXECUTOR is None:
        return
    try:
        _EXECUTOR.shutdown(wait=wait)
    except Exception as exc:
        logger.warning("news_sink: shutdown raised (%s)", exc)
    _EXECUTOR = None
