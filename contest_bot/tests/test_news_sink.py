"""Tests for `decision_store.news_sink.NewsSink` + `news_query`.

Pattern lifted from `test_decision_store_decline_recording.py` — same
`_FakeColl`, same monkeypatch of executor, same focus on:

  1. Connection / `from_env` behavior (None when MONGODB_URI unset, None
     when GECKO_NEWS_SINK=0, returns a sink when both are set).
  2. Schema enforcement (required fields missing raises; full record
     produces the expected BSON shape).
  3. Idempotent upsert (same dedupe key → update, not duplicate).
  4. Best-effort: sink-internal raise is swallowed; caller never sees it.
  5. Query helpers return [] on no collection, return trimmed docs on hit.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from decision_store import news_query, news_sink  # noqa: E402
from decision_store.news_sink import (  # noqa: E402
    NewsSink,
    build_news_doc,
    compute_news_id,
)

# ── shared fixtures ────────────────────────────────────────────────────


class _FakeColl:
    """Mirror of the `_FakeColl` in test_decision_store_decline_recording.

    Stores docs keyed by `news_id`. `update_one` with `upsert=True` mimics
    Mongo's upsert semantics — re-recording the same key updates in place,
    not duplicates.
    """

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.fail_on_update = False

    def update_one(self, flt, update, upsert=False):
        if self.fail_on_update:
            raise RuntimeError("simulated mongo failure")
        key = flt.get("news_id") or flt.get("_id")
        if key is None:
            return
        existing = self.docs.get(key, {})
        existing.update(update.get("$set", {}))
        if upsert and key not in self.docs:
            existing.update(update.get("$setOnInsert", {}))
        self.docs[key] = existing

    def find(self, flt=None):
        flt = flt or {}
        rows = list(self.docs.values())

        def _match(row):
            for k, v in flt.items():
                if isinstance(v, dict):
                    # tiny subset of $-operators — enough for these tests
                    if "$gte" in v and row.get(k) is not None and row[k] < v["$gte"]:
                        return False
                    if "$lte" in v and row.get(k) is not None and row[k] > v["$lte"]:
                        return False
                else:
                    target = row.get(k)
                    if isinstance(target, list):
                        if v not in target:
                            return False
                    elif target != v:
                        return False
            return True

        return _Cursor([r for r in rows if _match(r)])


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, key, direction=None):
        # Accept either single (key, dir) call or list-of-tuples.
        if isinstance(key, list):
            for k, d in reversed(key):
                self._rows.sort(
                    key=lambda r, kk=k: (r.get(kk) is None, r.get(kk)),
                    reverse=(d == -1),
                )
        else:
            self._rows.sort(
                key=lambda r: (r.get(key) is None, r.get(key)),
                reverse=(direction == -1),
            )
        return self

    def limit(self, n):
        self._rows = self._rows[: int(n)]
        return self

    def __iter__(self):
        return iter(self._rows)


@pytest.fixture(autouse=True)
def _force_sync_writes(monkeypatch):
    """Sync executor — no race between submit() and assertion."""

    class _SyncExec:
        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)

            class _F:
                def result(self_inner, timeout=None):
                    return None

            return _F()

        def shutdown(self, wait=True):
            pass

    monkeypatch.setattr(news_sink, "_get_executor", lambda: _SyncExec())


def _sample_raw(**overrides):
    base = {
        "source": "cryptopanic",
        "source_id": "abc-123",
        "url": "https://cryptopanic.com/news/abc-123/",
        "headline": "BTC ETF inflows hit fresh record",
        "body": "Bitcoin spot ETF flows reached $1.2B yesterday, breaking the prior record.",
        "tickers": ["BTC"],
        "published_at": "2026-05-31T12:00:00+00:00",
    }
    base.update(overrides)
    return base


# ── 1. from_env / connection behavior ─────────────────────────────────


def test_from_env_returns_none_when_uri_unset(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    assert NewsSink.from_env() is None


def test_from_env_returns_none_when_kill_switch_set(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://fake")
    monkeypatch.setenv("GECKO_NEWS_SINK", "0")
    assert NewsSink.from_env() is None


def test_from_env_returns_none_when_mongo_unreachable(monkeypatch):
    """If pymongo raises during client construction, from_env returns
    None instead of bubbling. The bot/caller stays alive."""
    monkeypatch.setenv("MONGODB_URI", "mongodb://nowhere:1/")
    monkeypatch.delenv("GECKO_NEWS_SINK", raising=False)

    class _BoomClient:
        def __init__(self, *a, **kw):
            raise RuntimeError("dns failure simulated")

    import pymongo

    monkeypatch.setattr(pymongo, "MongoClient", _BoomClient)
    assert NewsSink.from_env() is None


# ── 2. schema enforcement + doc shape ─────────────────────────────────


def test_build_news_doc_requires_source_and_headline():
    with pytest.raises(ValueError, match="missing required fields"):
        build_news_doc({"headline": "x"})  # no source
    with pytest.raises(ValueError, match="missing required fields"):
        build_news_doc({"source": "x"})  # no headline


def test_build_news_doc_full_shape():
    doc = build_news_doc(_sample_raw())
    # required + canonical fields present
    assert doc["news_id"]
    assert doc["source"] == "cryptopanic"
    assert doc["headline"].startswith("BTC ETF")
    assert doc["tickers"] == ["BTC"]
    assert doc["schema_v"] == 1
    # embedding fields absent (NOT None) until explicit patch
    assert "embedding" not in doc
    # ingested_at + fetched_at present
    assert isinstance(doc["ingested_at"], datetime)
    assert doc["fetched_at"]


def test_build_news_doc_uppercases_tickers():
    doc = build_news_doc(_sample_raw(tickers=["btc", "sol"]))
    assert doc["tickers"] == ["BTC", "SOL"]


def test_build_news_doc_caps_body_at_8000():
    long = "x" * 10_000
    doc = build_news_doc(_sample_raw(body=long))
    assert len(doc["body"]) == 8000


def test_compute_news_id_deterministic():
    a = compute_news_id("cryptopanic", "abc", "2026-05-31T12:00:00+00:00")
    b = compute_news_id("cryptopanic", "abc", "2026-05-31T12:00:00+00:00")
    assert a == b
    c = compute_news_id("cryptopanic", "DIFFERENT", "2026-05-31T12:00:00+00:00")
    assert a != c


# ── 3. idempotent upsert ──────────────────────────────────────────────


def test_record_is_idempotent_on_same_news_id():
    coll = _FakeColl()
    sink = NewsSink(coll)
    raw = _sample_raw()
    sink.record(raw)
    sink.record(raw)
    sink.record(raw)
    # Same dedupe key → same single doc.
    assert len(coll.docs) == 1
    # The doc was updated, not appended.
    only = next(iter(coll.docs.values()))
    assert only["headline"].startswith("BTC ETF")


def test_record_distinct_news_ids_produce_distinct_rows():
    coll = _FakeColl()
    sink = NewsSink(coll)
    sink.record(_sample_raw(source_id="abc-1"))
    sink.record(_sample_raw(source_id="abc-2"))
    assert len(coll.docs) == 2


def test_record_updates_in_place_when_payload_changes():
    coll = _FakeColl()
    sink = NewsSink(coll)
    sink.record(_sample_raw(headline="v1"))
    sink.record(_sample_raw(headline="v2 — corrected"))
    assert len(coll.docs) == 1
    only = next(iter(coll.docs.values()))
    assert only["headline"] == "v2 — corrected"


# ── 4. best-effort: failures swallowed ───────────────────────────────


def test_record_swallows_mongo_failure():
    coll = _FakeColl()
    coll.fail_on_update = True
    sink = NewsSink(coll)
    # Must NOT raise.
    sink.record(_sample_raw())
    assert coll.docs == {}


def test_record_swallows_build_failure():
    coll = _FakeColl()
    sink = NewsSink(coll)
    # Missing both required fields — build_news_doc raises internally,
    # sink logs + drops. Caller never sees it.
    sink.record({"unrelated_field": 1})
    assert coll.docs == {}


def test_patch_embedding_swallows_failure():
    coll = _FakeColl()
    coll.fail_on_update = True
    sink = NewsSink(coll)
    # Must NOT raise.
    sink.patch_embedding("nid", [0.0] * 1024, "voyage-finance-2", "summary")


# ── 5. query helpers ─────────────────────────────────────────────────


def test_query_recent_returns_empty_when_no_collection(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    assert news_query.recent(10) == []


def test_query_by_symbol_returns_empty_when_no_collection(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    assert news_query.by_symbol("BTC") == []


def test_query_by_source_returns_empty_when_no_collection(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    assert news_query.by_source("cryptopanic") == []


def test_query_recent_returns_trimmed_docs_sorted():
    coll = _FakeColl()
    sink = NewsSink(coll)
    sink.record(_sample_raw(source_id="old", published_at="2026-05-30T00:00:00+00:00"))
    sink.record(_sample_raw(source_id="new", published_at="2026-05-31T12:00:00+00:00"))
    # Inject a sham embedding to confirm it gets stripped.
    for doc in coll.docs.values():
        doc["embedding"] = [0.0] * 1024
    out = news_query.recent(10, collection=coll)
    assert len(out) == 2
    assert out[0]["published_at"] == "2026-05-31T12:00:00+00:00"
    assert all("embedding" not in d for d in out)


def test_query_by_symbol_filters_and_windows():
    coll = _FakeColl()
    sink = NewsSink(coll)
    sink.record(
        _sample_raw(source_id="btc-1", tickers=["BTC"], published_at="2026-05-31T10:00:00+00:00")
    )
    sink.record(
        _sample_raw(source_id="sol-1", tickers=["SOL"], published_at="2026-05-31T11:00:00+00:00")
    )
    sink.record(
        _sample_raw(source_id="btc-2", tickers=["BTC"], published_at="2026-05-31T15:00:00+00:00")
    )
    out = news_query.by_symbol(
        "btc",  # lower-case in caller; helper upper-cases
        since=datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC),
        until=datetime(2026, 5, 31, 20, 0, 0, tzinfo=UTC),
        collection=coll,
    )
    # Only one BTC row falls inside the window.
    assert len(out) == 1
    assert out[0]["source_id"] == "btc-2"


def test_query_by_source_returns_matching():
    coll = _FakeColl()
    sink = NewsSink(coll)
    sink.record(_sample_raw(source="cryptopanic", source_id="cp-1"))
    sink.record(_sample_raw(source="theblock_rss", source_id="tb-1"))
    out = news_query.by_source("cryptopanic", collection=coll)
    assert len(out) == 1
    assert out[0]["source"] == "cryptopanic"


# ── 6. tickers as a single string get normalized ──────────────────────


def test_build_news_doc_accepts_single_ticker_string():
    doc = build_news_doc(_sample_raw(tickers="btc"))
    assert doc["tickers"] == ["BTC"]


# ── 7. _ tiny end-to-end: record N raws across one window ─────────────


def test_record_then_query_round_trip():
    coll = _FakeColl()
    sink = NewsSink(coll)
    base_ts = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)
    for i in range(5):
        sink.record(
            _sample_raw(
                source_id=f"id-{i}",
                published_at=(base_ts + timedelta(minutes=i)).isoformat(),
            )
        )
    out = news_query.recent(3, collection=coll)
    assert len(out) == 3
    assert out[0]["source_id"] == "id-4"  # newest first
