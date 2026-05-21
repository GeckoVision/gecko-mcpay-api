"""Point-in-time pool reconstruction for the trade-panel backtest (Phase 2).

S39-#134. Resolves §2b of the backtesting scoping plan. Design doc:
``docs/strategy/2026-05-19-backtest-phase2-reconstruction-design.md``.

What this module does
----------------------

One public async function — :func:`reconstruct_pool_chunks` — that, for a
DeFiLlama pool id and a point-in-time T:

  1. fetches the pool's full APY/TVL series from DeFiLlama
     ``https://yields.llama.fi/chart/{pool}`` (free, no key),
  2. caches the raw *full* series in a dedicated Mongo collection
     ``backtest_reconstruction_cache`` keyed on the pool id,
  3. truncates the series to points with ``timestamp <= T`` (the
     no-lookahead guarantee — fail loud if zero points remain),
  4. renders the truncated series into chunk dicts through the *existing*
     ``sources/market_data.py`` renderers (no fork — Pattern E), each
     tagged ``as_of_date = T``,
  5. returns the chunk list in memory.

Corpus isolation (the settled Option C)
----------------------------------------

Reconstructed chunks are **never written to the production ``chunks``
collection** and are **never vector-indexed**. They are passed straight
into ``run_trade_panel(retrieved_chunks=...)`` by the backtest harness.
This module imports no chunk-collection writer. The only Mongo collection
it touches is ``backtest_reconstruction_cache`` — a raw-fetch cache that
the production ``$vectorSearch`` path never queries, so it carries zero
leak risk (caches are not corpora).

Caching
-------

Historical pool data is immutable, so the cache is keyed on the pool id
alone and stores the *full* fetched series. Truncation happens AFTER the
cache read — one fetch serves every T. A cache hit re-run costs $0.
The cache degrades to a no-op when Mongo is not configured (tests do not
need a live Mongo).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

from gecko_core.db.mongo import _db
from gecko_core.sources.market_data import render_tvl_chunk

if TYPE_CHECKING:  # pragma: no cover - typing only
    from motor.motor_asyncio import AsyncIOMotorCollection

_log = logging.getLogger(__name__)

# --- Constants ------------------------------------------------------------

DEFILLAMA_YIELDS_BASE_URL = "https://yields.llama.fi"
"""DeFiLlama yields host. The pool chart lives at ``/chart/{pool}``."""

RECONSTRUCTION_CACHE_COLLECTION = "backtest_reconstruction_cache"
"""Dedicated Mongo collection for raw DeFiLlama series. NOT a corpus —
the production ``$vectorSearch`` path never queries it. One doc per pool."""

# SSRF / httpx caps (CLAUDE.md security non-negotiables).
_HTTP_TIMEOUT_SECONDS = 15.0
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024  # 8 MiB — a multi-year daily series is well under this.

# Provider tagging for reconstructed chunks — the trade-panel retrieval
# $match admits `market_data` via its provider_kind clause regardless of
# protocol tagging (see market_data.py module docstring).
_PROVIDER_KIND = "market_data"
_FRESHNESS_TIER = "hot"


# --- SSRF guard -----------------------------------------------------------


def _is_safe_public_url(url: str) -> bool:
    """SSRF guard — accept https + a public hostname only.

    Rejects: non-https schemes, ``file://``, empty host, raw private /
    loopback / link-local / reserved IPs, and hostnames that resolve to
    any such IP. DeFiLlama is a public DNS name so legit fetches pass.

    Conservative by design: a resolution failure is treated as unsafe.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = parsed.hostname or ""
    if not host or host.lower() == "localhost":
        return False

    # If the host is a literal IP, check it directly.
    try:
        ip = ipaddress.ip_address(host)
        return _is_public_ip(ip)
    except ValueError:
        pass  # not a literal IP — resolve the DNS name below.

    # Resolve every A/AAAA record; reject if ANY is non-public.
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if not _is_public_ip(ip):
            return False
    return True


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True iff ``ip`` is a globally-routable public address."""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


# --- URL builder ----------------------------------------------------------


def _pool_chart_url(pool: str) -> str:
    """Build the DeFiLlama ``/chart/{pool}`` URL for ``pool``.

    ``pool`` is path-encoded so a malformed id cannot smuggle path
    segments. The result is still SSRF-checked before any fetch.
    """
    return f"{DEFILLAMA_YIELDS_BASE_URL}/chart/{quote(pool.strip(), safe='')}"


# --- Cache layer ----------------------------------------------------------


def _cache_collection() -> AsyncIOMotorCollection[Any] | None:
    """Return the reconstruction-cache collection, or None when Mongo is off."""
    db = _db()
    return None if db is None else db[RECONSTRUCTION_CACHE_COLLECTION]


def _cache_key(pool: str) -> str:
    """Cache key for a pool's full series. Historical data is immutable, so
    the pool id alone is the key — no T component (truncation is post-read)."""
    return pool.strip().lower()


async def _read_cached_series(pool: str) -> list[dict[str, Any]] | None:
    """Return the cached full series for ``pool``, or None on miss / no Mongo."""
    coll = _cache_collection()
    if coll is None:
        return None
    try:
        doc = await coll.find_one({"_id": _cache_key(pool)})
    except Exception as exc:  # pragma: no cover - defensive against test envs
        _log.warning("backtest.reconstruction.cache_read_failed pool=%s err=%s", pool, exc)
        return None
    if not doc:
        return None
    series = doc.get("series")
    if not isinstance(series, list):
        return None
    return [p for p in series if isinstance(p, dict)]


async def _write_cached_series(pool: str, series: list[dict[str, Any]]) -> None:
    """Idempotently upsert the raw full series for ``pool``. No-op without Mongo."""
    coll = _cache_collection()
    if coll is None:
        return
    try:
        await coll.update_one(
            {"_id": _cache_key(pool)},
            {
                "$set": {
                    "series": series,
                    "point_count": len(series),
                    "fetched_at": datetime.now(UTC).isoformat(),
                }
            },
            upsert=True,
        )
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("backtest.reconstruction.cache_write_failed pool=%s err=%s", pool, exc)


# --- Fetch ----------------------------------------------------------------


async def _fetch_pool_series(pool: str) -> list[dict[str, Any]]:
    """Fetch the raw DeFiLlama ``/chart/{pool}`` series.

    SSRF-guards the URL, caps the response body, applies a timeout.
    Returns the ``data`` array (ascending by timestamp as DeFiLlama
    serves it). Raises :class:`PoolReconstructionError` on a hard failure.
    """
    import httpx

    url = _pool_chart_url(pool)
    if not _is_safe_public_url(url):
        raise PoolReconstructionError(
            f"reconstruction: refusing to fetch unsafe URL for pool={pool!r}"
        )

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise PoolReconstructionError(
            f"reconstruction: DeFiLlama fetch failed for pool={pool!r}: {exc}"
        ) from exc

    if resp.status_code != 200:
        raise PoolReconstructionError(
            f"reconstruction: DeFiLlama returned HTTP {resp.status_code} for pool={pool!r}"
        )

    body = resp.content
    if len(body) > _MAX_RESPONSE_BYTES:
        raise PoolReconstructionError(
            f"reconstruction: DeFiLlama response for pool={pool!r} "
            f"exceeds {_MAX_RESPONSE_BYTES} bytes"
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise PoolReconstructionError(
            f"reconstruction: DeFiLlama response for pool={pool!r} is not JSON"
        ) from exc

    return _extract_series(payload, pool=pool)


def _extract_series(payload: Any, *, pool: str) -> list[dict[str, Any]]:
    """Pull the ``data`` array out of a DeFiLlama ``/chart`` payload.

    DeFiLlama wraps the series as ``{"status": "success", "data": [...]}``.
    Each point is ``{"timestamp": ISO8601, "tvlUsd": .., "apy": .., ...}``.
    """
    if not isinstance(payload, dict):
        raise PoolReconstructionError(
            f"reconstruction: unexpected DeFiLlama payload shape for pool={pool!r}"
        )
    data = payload.get("data")
    if not isinstance(data, list):
        raise PoolReconstructionError(
            f"reconstruction: DeFiLlama payload for pool={pool!r} has no `data` array"
        )
    return [p for p in data if isinstance(p, dict)]


# --- Truncation -----------------------------------------------------------


def _point_ts(point: dict[str, Any]) -> datetime | None:
    """Parse a series point's timestamp into a tz-aware UTC datetime.

    DeFiLlama emits ISO-8601 with a ``Z`` suffix. Returns None on a
    malformed/missing timestamp so the caller can drop that point.
    """
    raw = point.get("timestamp")
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def truncate_series(series: list[dict[str, Any]], *, as_of: str) -> list[dict[str, Any]]:
    """Drop every point with ``timestamp`` strictly after ``as_of``.

    This is the no-lookahead guarantee. ``as_of`` is a ``YYYY-MM-DD``
    day bucket; a point is kept iff its timestamp falls on or before the
    *end* of that day (``as_of`` 23:59:59.999999 UTC). Points with a
    malformed/missing timestamp are dropped (cannot prove they are <= T).
    """
    cutoff = _as_of_cutoff(as_of)
    kept: list[dict[str, Any]] = []
    for point in series:
        ts = _point_ts(point)
        if ts is None:
            continue
        if ts <= cutoff:
            kept.append(point)
    return kept


def _as_of_cutoff(as_of: str) -> datetime:
    """Parse a ``YYYY-MM-DD`` day bucket into its inclusive end-of-day UTC."""
    try:
        day = datetime.strptime(as_of.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError) as exc:
        raise PoolReconstructionError(
            f"reconstruction: as_of={as_of!r} is not a YYYY-MM-DD date"
        ) from exc
    return day.replace(hour=23, minute=59, second=59, microsecond=999_999, tzinfo=UTC)


# --- Render ---------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    """Best-effort float coercion. Returns None on a non-numeric value."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta_pct(series: list[dict[str, Any]], *, field: str, lookback: int) -> float:
    """Percentage change of ``field`` from ``lookback`` points ago to the
    last point. ``series`` must be ascending and non-empty. Returns 0.0
    when there is no comparable earlier point or the earlier value is 0."""
    if len(series) <= lookback:
        return 0.0
    latest = _coerce_float(series[-1].get(field))
    earlier = _coerce_float(series[-1 - lookback].get(field))
    if latest is None or earlier is None or earlier == 0.0:
        return 0.0
    return (latest - earlier) / earlier * 100.0


def _render_chunks(
    truncated: list[dict[str, Any]],
    *,
    pool: str,
    protocol: str,
    as_of: str,
) -> list[dict[str, Any]]:
    """Render the truncated series into chunk dicts.

    Renders through the existing ``market_data.render_tvl_chunk`` renderer
    — the truncated series' last point is the as-of-T TVL snapshot, with
    7d / 30d deltas computed off earlier points in the truncated window.
    No renderer fork (Pattern E): the DeFiLlama series is adapted to the
    renderer's existing ``(protocol, tvl, 7d%, 30d%, as_of)`` contract.

    The APY series rides along as a second chunk built from the same
    truncated window so the panel's yield-reading voices have a number to
    cite. Both chunks carry ``as_of_date = as_of`` and ``provider_kind =
    market_data``.
    """
    last = truncated[-1]
    tvl_usd = _coerce_float(last.get("tvlUsd")) or 0.0
    apy = _coerce_float(last.get("apy"))

    chunks: list[dict[str, Any]] = []

    # 1. TVL snapshot — rendered through the existing market_data renderer.
    tvl_text = render_tvl_chunk(
        protocol=protocol,
        tvl_usd=tvl_usd,
        tvl_7d_delta_pct=_delta_pct(truncated, field="tvlUsd", lookback=7),
        tvl_30d_delta_pct=_delta_pct(truncated, field="tvlUsd", lookback=30),
        as_of_iso=as_of,
    )
    chunks.append(
        _chunk_dict(
            chunk_id=f"backtest::recon::{pool}::tvl::{as_of}",
            text=tvl_text,
            protocol=protocol,
            pool=pool,
            as_of=as_of,
        )
    )

    # 2. APY snapshot — DeFiLlama's pool series is yield-first; the trade
    # panel's yield voices need the APY level + trend explicitly. Rendered
    # in the same prose shape the market_data renderers use.
    if apy is not None:
        apy_7d = _delta_pct(truncated, field="apy", lookback=7)
        apy_text = (
            f"DefiLlama APY snapshot for {protocol} pool {pool} (as of {as_of}).\n"
            f"As-of date: {as_of}.\n"
            f"Current APY: {apy:.2f}%.\n"
            f"7-day APY change: {apy_7d:+.2f}%.\n"
            f"Series points observed (truncated at T): {len(truncated)}.\n"
            f"Source: DefiLlama yields /chart. Provider: market_data."
        )
        chunks.append(
            _chunk_dict(
                chunk_id=f"backtest::recon::{pool}::apy::{as_of}",
                text=apy_text,
                protocol=protocol,
                pool=pool,
                as_of=as_of,
            )
        )

    return chunks


def _chunk_dict(
    *,
    chunk_id: str,
    text: str,
    protocol: str,
    pool: str,
    as_of: str,
) -> dict[str, Any]:
    """Build one chunk dict in the standard trade-panel slate shape.

    Mirrors the shape ``retrieve_trade_corpus_chunks`` projects (``id`` /
    ``text`` / ``source`` / ``source_url`` / ``provider_kind`` /
    ``freshness_tier`` / ``protocol`` / ``as_of_date`` / ``score``) so the
    panel consumes a reconstructed chunk identically to a retrieved one.
    """
    return {
        "id": chunk_id,
        "text": text,
        "source": "defillama",
        "source_url": _pool_chart_url(pool),
        "provider_kind": _PROVIDER_KIND,
        "freshness_tier": _FRESHNESS_TIER,
        "protocol": [protocol] if protocol else [],
        "vertical": "dex",
        # The point-in-time stamp — the no-lookahead gate keys on this.
        "as_of_date": as_of,
        "score": 0.0,
    }


# --- Errors ---------------------------------------------------------------


class PoolReconstructionError(RuntimeError):
    """Raised when a pool cannot be reconstructed at T.

    Fail-loud cases: unsafe URL, fetch/HTTP failure, malformed payload,
    or zero series points surviving truncation (a backtest at T with no
    point-in-time data must NOT silently render an empty slate)."""


# --- Public surface -------------------------------------------------------


async def reconstruct_pool_chunks(
    pool: str,
    *,
    as_of: str,
    protocol: str,
) -> list[dict[str, Any]]:
    """Reconstruct a pool's APY/TVL state as-of-T into in-memory chunk dicts.

    Pipeline: cache-read (or fetch + cache) the full DeFiLlama series →
    truncate at ``as_of`` (no-lookahead) → render through the existing
    ``market_data.py`` renderers → return chunk dicts tagged with
    ``as_of_date = as_of``.

    The returned list is **never written to the production ``chunks``
    collection** and is never vector-indexed (Option C — see module
    docstring). The caller (backtest harness) merges it with gated canon
    and passes the union to ``run_trade_panel(retrieved_chunks=...)``.

    Args:
        pool: DeFiLlama pool id (the ``/chart/{pool}`` path segment).
        as_of: Point-in-time T as a ``YYYY-MM-DD`` day bucket. Every
            returned chunk's underlying series point has a timestamp
            ``<= as_of``.
        protocol: Normalized protocol slug, used for chunk tagging.

    Returns:
        Chunk dicts in the standard trade-panel slate shape.

    Raises:
        PoolReconstructionError: unsafe URL, fetch failure, malformed
            payload, or zero points surviving truncation.
    """
    pool_id = pool.strip()
    if not pool_id:
        raise PoolReconstructionError("reconstruction: pool id is empty")
    proto = protocol.strip().lower()

    # Validate as_of early — fail loud before any network call.
    _as_of_cutoff(as_of)

    # Cache-first: the full immutable series is keyed on the pool id alone.
    series = await _read_cached_series(pool_id)
    if series is None:
        series = await _fetch_pool_series(pool_id)
        await _write_cached_series(pool_id, series)
        _log.info(
            "backtest.reconstruction.fetched pool=%s points=%d",
            pool_id,
            len(series),
        )
    else:
        _log.info(
            "backtest.reconstruction.cache_hit pool=%s points=%d",
            pool_id,
            len(series),
        )

    truncated = truncate_series(series, as_of=as_of)
    if not truncated:
        # Fail loud — a point-in-time render with no <= T data is invalid.
        raise PoolReconstructionError(
            f"reconstruction: pool={pool_id!r} has zero series points "
            f"on or before as_of={as_of!r} (cannot reconstruct at T)"
        )

    chunks = _render_chunks(truncated, pool=pool_id, protocol=proto, as_of=as_of)
    _log.info(
        "backtest.reconstruction.rendered pool=%s as_of=%s truncated_points=%d chunks=%d",
        pool_id,
        as_of,
        len(truncated),
        len(chunks),
    )
    return chunks


__all__ = [
    "DEFILLAMA_YIELDS_BASE_URL",
    "RECONSTRUCTION_CACHE_COLLECTION",
    "PoolReconstructionError",
    "reconstruct_pool_chunks",
    "truncate_series",
]
