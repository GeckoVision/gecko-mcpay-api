"""Sprint 29 — Tests for oracle snapshot sink + query + clients.

Mirrors the pattern from `test_news_sink.py` (DATA-2) — light fakes for
the Mongo collection, no live network. Pyth + Jupiter REST clients are
tested via httpx mock transports.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

# Make contest_bot/ importable.
_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from oracle.jupiter_client import JupiterPriceRestClient, JupiterPriceSnapshot  # noqa: E402
from oracle.pyth_client import PythHermesRestClient, PriceSnapshot  # noqa: E402
from oracle.snapshot_query import by_source, by_symbol, latest_per_source, recent  # noqa: E402
from oracle.snapshot_sink import OracleSnapshotSink, build_snapshot_doc  # noqa: E402


# ── Fake Mongo collection ──────────────────────────────────────────────


class _FakeColl:
    """Pure-Python stand-in for a pymongo Collection. Implements only
    the surface our sink + query helpers use."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def update_one(self, flt: dict, update: dict, upsert: bool = False) -> None:
        key = flt.get("snapshot_id")
        if not key:
            raise ValueError("test fake requires snapshot_id")
        existing = self.docs.get(key, {})
        existing.update(update.get("$set", {}))
        if upsert and key not in self.docs:
            existing.update(update.get("$setOnInsert", {}))
        self.docs[key] = existing

    def find(self, flt: dict | None = None) -> "_FakeCursor":
        flt = flt or {}
        rows = list(self.docs.values())
        # Minimal filter support (symbol, source, ts range)
        if "symbol" in flt:
            rows = [r for r in rows if r.get("symbol") == flt["symbol"]]
        if "source" in flt:
            rows = [r for r in rows if r.get("source") == flt["source"]]
        if "ts" in flt and isinstance(flt["ts"], dict):
            window = flt["ts"]
            if "$gte" in window:
                rows = [r for r in rows if (r.get("ts") or "") >= window["$gte"]]
            if "$lte" in window:
                rows = [r for r in rows if (r.get("ts") or "") <= window["$lte"]]
        return _FakeCursor(rows)


class _FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def sort(self, key: str, direction: int) -> "_FakeCursor":
        reverse = direction == -1
        self._rows = sorted(self._rows, key=lambda r: r.get(key) or "", reverse=reverse)
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._rows = self._rows[: int(n)]
        return self

    def __iter__(self):
        return iter(self._rows)


# ── build_snapshot_doc ─────────────────────────────────────────────────


def test_build_snapshot_doc_pure_function() -> None:
    doc = build_snapshot_doc(
        source="pyth",
        symbol="sol",  # lowercase → upper-cased
        price=148.32,
        spread_pct=0.03,
        confidence=0.044,
        ts="2026-06-01T05:00:00Z",
        publishers_count=14,
    )
    assert doc["source"] == "pyth"
    assert doc["symbol"] == "SOL"
    assert doc["price"] == 148.32
    assert doc["spread_pct"] == 0.03
    assert doc["publishers_count"] == 14
    assert doc["snapshot_id"]  # deterministic hash
    assert doc["schema_v"] == 1
    assert "SOL @ $148.320000" in doc["embedding_summary"]
    # embedding fields absent on insert
    assert doc["embedding_model"] is None


def test_build_snapshot_doc_idempotent_id() -> None:
    """Same (source, symbol, ts) → same snapshot_id."""
    d1 = build_snapshot_doc(source="pyth", symbol="SOL", price=148.32, ts="2026-06-01T05:00:00Z")
    d2 = build_snapshot_doc(source="pyth", symbol="SOL", price=999.99, ts="2026-06-01T05:00:00Z")
    assert d1["snapshot_id"] == d2["snapshot_id"]


def test_build_snapshot_doc_distinct_id_per_ts() -> None:
    d1 = build_snapshot_doc(source="pyth", symbol="SOL", price=148.32, ts="2026-06-01T05:00:00Z")
    d2 = build_snapshot_doc(source="pyth", symbol="SOL", price=148.32, ts="2026-06-01T05:01:00Z")
    assert d1["snapshot_id"] != d2["snapshot_id"]


def test_build_snapshot_doc_extras_pass_through() -> None:
    doc = build_snapshot_doc(
        source="pyth",
        symbol="SOL",
        price=148.32,
        extras={"feed_id": "ef0d8b6f"},
    )
    assert doc["feed_id"] == "ef0d8b6f"


# ── OracleSnapshotSink ─────────────────────────────────────────────────


def test_sink_record_idempotent() -> None:
    coll = _FakeColl()
    sink = OracleSnapshotSink(coll, async_writes=False)
    doc = build_snapshot_doc(source="pyth", symbol="SOL", price=148.32, ts="2026-06-01T05:00:00Z")
    sink.record(doc)
    sink.record(doc)  # second call should upsert in place, not duplicate
    assert len(coll.docs) == 1


def test_sink_record_swallows_collection_exception() -> None:
    class _BrokenColl:
        def update_one(self, *_a, **_kw):
            raise RuntimeError("mongo down")

    sink = OracleSnapshotSink(_BrokenColl(), async_writes=False)
    doc = build_snapshot_doc(source="pyth", symbol="SOL", price=148.32, ts="2026-06-01T05:00:00Z")
    # MUST NOT raise — best-effort discipline
    sink.record(doc)


def test_sink_from_env_returns_none_when_uri_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)
    assert OracleSnapshotSink.from_env() is None


def test_sink_from_env_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb://nope")
    monkeypatch.setenv("GECKO_ORACLE_SINK", "0")
    assert OracleSnapshotSink.from_env() is None


# ── Query helpers (using fake collection injection) ─────────────────────


def _seeded_coll() -> _FakeColl:
    coll = _FakeColl()
    sink = OracleSnapshotSink(coll, async_writes=False)
    sink.record(build_snapshot_doc(source="pyth", symbol="SOL", price=148.30, ts="2026-06-01T05:00:00Z"))
    sink.record(build_snapshot_doc(source="pyth", symbol="SOL", price=148.50, ts="2026-06-01T05:01:00Z"))
    sink.record(build_snapshot_doc(source="jupiter", symbol="SOL", price=148.45, ts="2026-06-01T05:00:00Z"))
    sink.record(build_snapshot_doc(source="pyth", symbol="WIF", price=0.191, ts="2026-06-01T05:00:00Z"))
    return coll


def test_query_recent_returns_newest_first() -> None:
    coll = _seeded_coll()
    rows = recent(limit=10, collection=coll)
    assert len(rows) == 4
    # Newest first — the 05:01 SOL row should be first
    assert rows[0]["ts"] == "2026-06-01T05:01:00Z"


def test_query_by_symbol_filters_correctly() -> None:
    coll = _seeded_coll()
    rows = by_symbol("SOL", collection=coll)
    assert len(rows) == 3  # 2 pyth + 1 jupiter for SOL
    assert all(r["symbol"] == "SOL" for r in rows)


def test_query_by_symbol_with_source_filter() -> None:
    coll = _seeded_coll()
    rows = by_symbol("SOL", source="jupiter", collection=coll)
    assert len(rows) == 1
    assert rows[0]["source"] == "jupiter"


def test_query_latest_per_source() -> None:
    coll = _seeded_coll()
    latest = latest_per_source("SOL", collection=coll)
    assert set(latest.keys()) == {"pyth", "jupiter"}
    # Should be the NEWER pyth row (05:01, not 05:00)
    assert latest["pyth"]["ts"] == "2026-06-01T05:01:00Z"


def test_query_by_source() -> None:
    coll = _seeded_coll()
    pyth_rows = by_source("pyth", collection=coll)
    assert len(pyth_rows) == 3  # 2 SOL + 1 WIF
    jup_rows = by_source("jupiter", collection=coll)
    assert len(jup_rows) == 1


# ── PythHermesRestClient ───────────────────────────────────────────────


def _pyth_fake_handler(request: httpx.Request) -> httpx.Response:
    """Return a Hermes-shaped JSON response with one SOL feed."""
    return httpx.Response(
        200,
        json={
            "parsed": [
                {
                    "id": "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
                    "price": {
                        "price": "14832000000",  # 148.32 with expo -8
                        "conf": "4400000",
                        "expo": -8,
                        "publish_time": 1748764800,
                    },
                }
            ]
        },
    )


def test_pyth_client_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(_pyth_fake_handler)
    # httpx.get uses the default client; we'll monkeypatch httpx.get to use a mocked client.
    real_get = httpx.get

    def _patched(url, **kwargs):
        params = kwargs.get("params")
        with httpx.Client(transport=transport) as c:
            return c.get(url, params=params, timeout=kwargs.get("timeout", 5))

    monkeypatch.setattr(httpx, "get", _patched)

    client = PythHermesRestClient()
    snaps = client.fetch(["SOL"])
    assert "SOL" in snaps
    assert snaps["SOL"].symbol == "SOL"
    assert snaps["SOL"].price == pytest.approx(148.32, rel=1e-6)
    assert snaps["SOL"].source == "pyth"
    # spread_pct = conf/price * 100 = 4400000/14832000000 * 100 ≈ 0.0297%
    assert snaps["SOL"].spread_pct == pytest.approx(0.0297, rel=1e-2)


def test_pyth_client_returns_empty_on_unknown_symbol() -> None:
    client = PythHermesRestClient()
    snaps = client.fetch(["NOT_A_SYMBOL"])
    assert snaps == {}


def test_pyth_client_swallows_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken(*_a, **_kw):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(httpx, "get", _broken)
    client = PythHermesRestClient()
    # MUST NOT raise
    snaps = client.fetch(["SOL"])
    assert snaps == {}


# ── JupiterPriceRestClient ─────────────────────────────────────────────


def _jupiter_fake_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "So11111111111111111111111111111111111111112": {
                    "id": "So11111111111111111111111111111111111111112",
                    "type": "derivedPrice",
                    "price": "148.45",
                }
            }
        },
    )


def test_jupiter_client_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(_jupiter_fake_handler)

    def _patched(url, **kwargs):
        params = kwargs.get("params")
        with httpx.Client(transport=transport) as c:
            return c.get(url, params=params, timeout=kwargs.get("timeout", 5))

    monkeypatch.setattr(httpx, "get", _patched)

    client = JupiterPriceRestClient()
    snaps = client.fetch(["SOL"])
    assert "SOL" in snaps
    assert snaps["SOL"].price == pytest.approx(148.45)
    assert snaps["SOL"].source == "jupiter"


def test_jupiter_client_swallows_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken(*_a, **_kw):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx, "get", _broken)
    client = JupiterPriceRestClient()
    snaps = client.fetch(["SOL"])
    assert snaps == {}
