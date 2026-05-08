"""History sources for the trade-panel backtest (Phase 9 v1).

Public types
------------

``HistorySource`` (Protocol): the contract the simulator consumes.
Anything that returns ``list[Candle]`` for a (protocol, granularity,
window) request satisfies it. Tests inject a canned source; production
wires :class:`PythHermesHistorySource`.

``PythHermesHistorySource``: tries to read cached candles from Mongo
first; on miss, attempts a Pyth Hermes fetch.

Pyth Hermes reality check
-------------------------

Pyth Hermes (``https://hermes.pyth.network``) is **real-time-focused**.
The endpoints we audited:

    - ``GET /v2/price_feeds``        — list of feed IDs + metadata.
    - ``GET /v2/updates/price/latest`` — current price.
    - ``GET /v2/updates/price/{publish_time}`` — point-in-time price at
      a specific publish_time (single tick, not OHLCV).

Hermes does NOT expose an OHLCV-bars endpoint. Building 1y/1d candles
from Hermes would require sampling latest-price every N minutes via a
cron and aggregating server-side — Phase 9.5 work.

For Phase 9 v1, the in-process behavior is:

    1. Read candles from the ``protocol_price_history`` Mongo cache.
    2. If cache is empty, return ``[]`` and let the caller emit a
       ``BacktestReport(unbacktestable=True, reason="pyth_no_history")``.
    3. The cache is intentionally empty until a separate ingestion job
       populates it. Phase 9.5 swaps in Birdeye / CoinGecko OHLCV.

This degrades gracefully and avoids a fake "we backtested it" report.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from gecko_core.orchestration.trade_panel.backtest.models import (
    BacktestGranularity,
    Candle,
)
from gecko_core.orchestration.trade_panel.backtest.storage import read_candles

if TYPE_CHECKING:  # pragma: no cover - typing only
    import httpx

_log = logging.getLogger(__name__)

# Canonical Pyth feed IDs for the Solana DeFi protocols our trading-oracle
# corpus already covers. Source: Pyth's published price-feeds manifest at
# https://pyth.network/developers/price-feed-ids — values pinned here so a
# Pyth manifest update does not silently re-route lookups. Add a protocol
# = touch this dict only.
_PROTOCOL_TO_FEED: dict[str, str] = {
    "jupiter": "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996",  # JUP/USD
    "kamino": "0xb17e5bc5de742a8a378b54c8c4f25b2a9d7e8e80e4a1a7e1aa1ad8b5a2e8d2e8",  # KMNO/USD (placeholder)
    "pyth": "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff",  # PYTH/USD
    "drift": "0x6c7e07a8a1e5f3f9a3d2c1d7cd2e2a3a3e2c1e5e7c4a9b8c7d6e5f4a3b2c1d0e",  # DRIFT/USD (placeholder)
    "jito": "0xa0255134973f4fdf2f8f7808354274a3b1ebc6ee438be898d045e8b56ba1fe13",  # JTO/USD
}

PYTH_HERMES_BASE_URL = "https://hermes.pyth.network"


class HistorySource(Protocol):
    """Returns ascending-by-ts candles for a protocol+granularity window.

    Implementations must be async + safe to call repeatedly. The simulator
    treats an empty list as "no history" and emits an unbacktestable
    report — implementations should not raise on missing data.
    """

    async def fetch(
        self,
        protocol: str,
        *,
        granularity: BacktestGranularity,
        ts_start: int,
        ts_end: int,
    ) -> list[Candle]:  # pragma: no cover - protocol
        ...


class PythHermesHistorySource:
    """Cache-first source backed by Mongo's ``protocol_price_history``.

    Hermes itself does not expose OHLCV; this class reads from the local
    Mongo cache. The ``_attempt_pyth_fetch`` hook is wired for Phase 9.5
    where we'll either sample-and-aggregate Hermes ourselves or swap in
    a real OHLCV provider behind the same Protocol surface.
    """

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = PYTH_HERMES_BASE_URL,
    ) -> None:
        self._http = http_client
        self._base_url = base_url

    async def fetch(
        self,
        protocol: str,
        *,
        granularity: BacktestGranularity,
        ts_start: int,
        ts_end: int,
    ) -> list[Candle]:
        proto = protocol.strip().lower()
        if not proto:
            return []
        # Cache hit path — the Mongo cache is the load-bearing source for v1.
        cached = await read_candles(
            proto,
            granularity=granularity,
            ts_start=ts_start,
            ts_end=ts_end,
        )
        if cached:
            return cached
        # Cache miss — Hermes does not serve OHLCV; degrade quietly.
        return await self._attempt_pyth_fetch(
            proto, granularity=granularity, ts_start=ts_start, ts_end=ts_end
        )

    async def _attempt_pyth_fetch(
        self,
        protocol: str,
        *,
        granularity: BacktestGranularity,
        ts_start: int,
        ts_end: int,
    ) -> list[Candle]:
        """Hook for live Pyth fetches. Returns ``[]`` in v1 (no OHLCV API).

        Kept as a method (not inlined) so Phase 9.5's CoinGecko/Birdeye
        swap is a small change here, not in ``fetch``. Tests subclass
        and override this to assert the cache-miss code path.
        """
        feed_id = _PROTOCOL_TO_FEED.get(protocol)
        if feed_id is None:
            return []
        # Pyth Hermes has no historical OHLCV endpoint as of 2026-05.
        # Returning empty triggers the unbacktestable=pyth_no_history path
        # in the caller. See module docstring for the upgrade plan.
        _log.info(
            "backtest.history.pyth_no_history protocol=%s granularity=%s ts_start=%s ts_end=%s",
            protocol,
            granularity,
            ts_start,
            ts_end,
        )
        return []


__all__ = [
    "PYTH_HERMES_BASE_URL",
    "HistorySource",
    "PythHermesHistorySource",
]
