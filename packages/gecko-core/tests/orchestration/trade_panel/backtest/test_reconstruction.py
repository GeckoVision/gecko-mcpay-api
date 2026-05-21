"""Reconstruction tests (S39 Backtest Phase 2 — #134).

Pattern B — the fetch+truncate+render path is falsifiable offline against
a recorded DeFiLlama ``/chart`` fixture; no network, no spend. Light
fakes over heavy simulation (per ``feedback_lighter_tests``): truncation,
the SSRF guard, the cache key, and the render mapping are pure-unit
tested; one integration test threads the recorded fixture end to end.

The corpus-isolation test asserts the documented Option C invariant —
reconstruction returns chunks but never imports or calls any
``chunks``-collection writer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from gecko_core.orchestration.trade_panel.backtest import reconstruction as recon
from gecko_core.orchestration.trade_panel.backtest.reconstruction import (
    DEFILLAMA_YIELDS_BASE_URL,
    RECONSTRUCTION_CACHE_COLLECTION,
    PoolReconstructionError,
    reconstruct_pool_chunks,
    truncate_series,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "defillama_chart_pool_227050.json"
_POOL = "227050-fixture"


def _load_fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text())


def _series() -> list[dict[str, Any]]:
    return list(_load_fixture()["data"])


# --- Truncation truth table ----------------------------------------------


@pytest.mark.parametrize(
    ("as_of", "expected_kept"),
    [
        ("2023-12-31", 0),  # before the whole series
        ("2024-01-01", 1),  # exactly the first point — inclusive end-of-day
        ("2024-01-14", 2),  # between point 2 and 3
        ("2024-01-15", 3),  # exactly the third point
        ("2024-02-15", 5),  # mid-series
        ("2024-03-01", 6),  # exactly the last point
        ("2030-01-01", 6),  # far future — whole series kept, never more
    ],
)
def test_truncation_truth_table(as_of: str, expected_kept: int) -> None:
    kept = truncate_series(_series(), as_of=as_of)
    assert len(kept) == expected_kept


def test_truncation_drops_malformed_timestamps() -> None:
    """A point with a missing/bad timestamp cannot be proven <= T → dropped."""
    series = [*_series(), {"tvlUsd": 1, "apy": 1}, {"timestamp": "not-a-date", "apy": 2}]
    kept = truncate_series(series, as_of="2030-01-01")
    assert len(kept) == 6  # the two malformed points are not kept


def test_truncation_no_lookahead_guarantee() -> None:
    """Every kept point's timestamp is <= T; a known >T point is absent."""
    as_of = "2024-02-01"
    kept = truncate_series(_series(), as_of=as_of)
    cutoff = recon._as_of_cutoff(as_of)
    for point in kept:
        ts = recon._point_ts(point)
        assert ts is not None and ts <= cutoff
    # The 2024-02-15 / 2024-03-01 points are strictly after T — absent.
    kept_timestamps = {p["timestamp"] for p in kept}
    assert "2024-02-15T00:00:00.000Z" not in kept_timestamps
    assert "2024-03-01T00:00:00.000Z" not in kept_timestamps


# --- SSRF / URL guard -----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://yields.llama.fi/chart/x",  # not https
        "file:///etc/passwd",  # file scheme
        "https://localhost/chart/x",  # loopback hostname
        "https://127.0.0.1/chart/x",  # loopback IP
        "https://10.0.0.1/chart/x",  # private range
        "https://192.168.1.1/chart/x",  # private range
        "https://169.254.169.254/chart/x",  # link-local (cloud metadata)
        "https://0.0.0.0/chart/x",  # unspecified
        "",  # empty
    ],
)
def test_ssrf_guard_rejects_unsafe_urls(url: str) -> None:
    assert recon._is_safe_public_url(url) is False


def test_ssrf_guard_accepts_public_https() -> None:
    assert recon._is_safe_public_url("https://yields.llama.fi/chart/abc") is True


async def test_fetch_refuses_unsafe_pool_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unsafe URL fails loud before any httpx call is made."""
    monkeypatch.setattr(recon, "_is_safe_public_url", lambda _url: False)
    with pytest.raises(PoolReconstructionError, match="unsafe URL"):
        await recon._fetch_pool_series("evil-pool")


# --- URL builder + cache key ---------------------------------------------


def test_pool_chart_url_is_path_encoded() -> None:
    url = recon._pool_chart_url("a/b id")
    assert url.startswith(f"{DEFILLAMA_YIELDS_BASE_URL}/chart/")
    # The slash and space in the pool id must not become path segments.
    assert "/chart/a%2Fb%20id" in url


def test_cache_key_is_pool_only_and_normalized() -> None:
    """Cache key is the lowercased pool id — no T component (one fetch / many T)."""
    assert recon._cache_key("  Pool-227050  ") == "pool-227050"
    assert recon._cache_key("POOL-227050") == recon._cache_key("pool-227050")


def test_cache_collection_name_is_dedicated() -> None:
    """The cache lives in its own collection — never the `chunks` corpus."""
    assert RECONSTRUCTION_CACHE_COLLECTION == "backtest_reconstruction_cache"
    assert RECONSTRUCTION_CACHE_COLLECTION != "chunks"


# --- Light Mongo fake -----------------------------------------------------


class _FakeCacheCollection:
    """In-memory stand-in for the reconstruction-cache Mongo collection."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.reads = 0
        self.writes = 0

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        self.reads += 1
        return self.docs.get(query["_id"])

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> None:
        self.writes += 1
        key = query["_id"]
        doc = self.docs.setdefault(key, {"_id": key})
        doc.update(update["$set"])


# --- Integration over the recorded fixture --------------------------------


async def test_reconstruct_end_to_end_over_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture → reconstruct → assert chunk shape + as_of_date tagging."""
    fake_cache = _FakeCacheCollection()
    monkeypatch.setattr(recon, "_cache_collection", lambda: fake_cache)

    fetch_calls: list[str] = []

    async def _fake_fetch(pool: str) -> list[dict[str, Any]]:
        fetch_calls.append(pool)
        return _series()

    monkeypatch.setattr(recon, "_fetch_pool_series", _fake_fetch)

    chunks = await reconstruct_pool_chunks(_POOL, as_of="2024-02-15", protocol="kamino")

    assert len(chunks) >= 1
    for chunk in chunks:
        # Standard trade-panel slate shape.
        for key in ("id", "text", "source", "source_url", "provider_kind", "freshness_tier"):
            assert key in chunk
        assert chunk["as_of_date"] == "2024-02-15"
        assert chunk["provider_kind"] == "market_data"
        assert chunk["protocol"] == ["kamino"]
        assert isinstance(chunk["text"], str) and chunk["text"]
    # One fetch happened; the series was cached.
    assert fetch_calls == [_POOL]
    assert fake_cache.writes == 1


async def test_reconstruct_cache_hit_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """One fetch serves many T — a cached pool never re-fetches."""
    fake_cache = _FakeCacheCollection()
    fake_cache.docs[recon._cache_key(_POOL)] = {"_id": recon._cache_key(_POOL), "series": _series()}
    monkeypatch.setattr(recon, "_cache_collection", lambda: fake_cache)

    async def _no_fetch(pool: str) -> list[dict[str, Any]]:
        raise AssertionError("cache hit must not fetch")

    monkeypatch.setattr(recon, "_fetch_pool_series", _no_fetch)

    # Two different T values, one cached series, zero fetches.
    chunks_a = await reconstruct_pool_chunks(_POOL, as_of="2024-01-15", protocol="kamino")
    chunks_b = await reconstruct_pool_chunks(_POOL, as_of="2024-03-01", protocol="kamino")
    assert chunks_a and chunks_b
    assert fake_cache.writes == 0


async def test_reconstruct_no_lookahead_in_returned_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No returned chunk text references series data dated after T."""
    fake_cache = _FakeCacheCollection()
    monkeypatch.setattr(recon, "_cache_collection", lambda: fake_cache)

    async def _fake_fetch(pool: str) -> list[dict[str, Any]]:
        return _series()

    monkeypatch.setattr(recon, "_fetch_pool_series", _fake_fetch)

    chunks = await reconstruct_pool_chunks(_POOL, as_of="2024-01-15", protocol="kamino")
    text = " ".join(c["text"] for c in chunks)
    # The truncated window has 3 points — the APY chunk reports that count,
    # never the full 6. A leak would surface the post-T point count.
    assert "Series points observed (truncated at T): 3" in text
    # The as-of-T TVL is the 2024-01-15 value (11M), never the 14.2M final.
    assert "$11,000,000" in text
    assert "$14,200,000" not in text


async def test_reconstruct_fails_loud_on_zero_points_after_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A T before the whole series → fail loud, never an empty slate."""
    fake_cache = _FakeCacheCollection()
    monkeypatch.setattr(recon, "_cache_collection", lambda: fake_cache)

    async def _fake_fetch(pool: str) -> list[dict[str, Any]]:
        return _series()

    monkeypatch.setattr(recon, "_fetch_pool_series", _fake_fetch)

    with pytest.raises(PoolReconstructionError, match="zero series points"):
        await reconstruct_pool_chunks(_POOL, as_of="2023-01-01", protocol="kamino")


async def test_reconstruct_rejects_bad_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed as_of fails loud before any fetch."""

    async def _no_fetch(pool: str) -> list[dict[str, Any]]:
        raise AssertionError("must not fetch on a bad as_of")

    monkeypatch.setattr(recon, "_fetch_pool_series", _no_fetch)
    monkeypatch.setattr(recon, "_cache_collection", lambda: None)

    with pytest.raises(PoolReconstructionError, match="YYYY-MM-DD"):
        await reconstruct_pool_chunks(_POOL, as_of="not-a-date", protocol="kamino")


# --- Corpus isolation (Option C invariant) -------------------------------


async def test_reconstruction_never_writes_the_chunks_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconstruction returns chunks but never calls a `chunks`-collection writer.

    Asserts the documented Option C invariant: reconstructed chunks are
    in-memory only. The reconstruction module must not import
    `insert_chunks_mongo` or touch `chunks_collection()`.
    """
    fake_cache = _FakeCacheCollection()
    monkeypatch.setattr(recon, "_cache_collection", lambda: fake_cache)

    async def _fake_fetch(pool: str) -> list[dict[str, Any]]:
        return _series()

    monkeypatch.setattr(recon, "_fetch_pool_series", _fake_fetch)

    # Tripwire: if reconstruction ever calls the chunk writer, blow up.
    import gecko_core.db.mongo_chunks as mongo_chunks

    async def _forbidden(*args: Any, **kwargs: Any) -> int:
        raise AssertionError("reconstruction must NEVER write the chunks collection")

    monkeypatch.setattr(mongo_chunks, "insert_chunks_mongo", _forbidden)

    chunks = await reconstruct_pool_chunks(_POOL, as_of="2024-02-15", protocol="kamino")
    assert chunks  # produced chunks...
    # ...and the only Mongo collection touched was the dedicated cache.
    assert fake_cache.writes == 1

    # Static guarantee: the module source imports no chunk-collection writer.
    src = Path(recon.__file__).read_text()
    assert "insert_chunks_mongo" not in src
    assert "chunks_collection" not in src
