#!/usr/bin/env python3
"""Shared market-data feed — Phase 3 of the hosted agent flow.

N hosted agents on the same universe must NOT each hit OKX. ONE poller fetches
5m candles per (symbol, bar) and serves all agents from a TTL cache → API load
drops from O(agents) to O(universes).

Two surfaces:
  - `CandleCache` — the TTL cache over `OkxSpotCandleProvider` (ccxt public data).
  - a tiny FastAPI service so per-PROCESS agents (each monolith is its own process)
    share one cache over HTTP. Agents point at it via GECKO_FEED_URL (see okx_feed).

Run:  uv run uvicorn shared_feed:app --host 0.0.0.0 --port 8275   # from contest_bot/
"""

from __future__ import annotations

import os
import time
from typing import Any

from strategies.okx_feed import OkxSpotCandleProvider


class CandleCache:
    """Per-(symbol,bar,limit) TTL cache. `ttl_sec` defaults short relative to the
    bar so candles are near-fresh but fetches dedup across many agents within a
    tick window. Never raises — a fetch error returns the last good cache or []."""

    def __init__(self, ttl_sec: float = 45.0, price_ttl_sec: float = 5.0, provider=None) -> None:
        self._p = provider or OkxSpotCandleProvider()
        self._ttl = ttl_sec
        self._price_ttl = price_ttl_sec
        self._candles: dict[tuple, tuple[float, list[dict]]] = {}
        self._price: dict[str, tuple[float, dict]] = {}

    def get_candles(self, symbol: str, bar: str = "5m", limit: int = 210, now: float | None = None) -> list[dict]:
        key = (symbol, bar, int(limit))
        t = now if now is not None else time.time()
        hit = self._candles.get(key)
        if hit and (t - hit[0]) < self._ttl:
            return hit[1]
        rows = self._p.get_candles(symbol, bar, limit)
        if rows or hit is None:  # keep last-good on an empty fetch
            self._candles[key] = (t, rows)
            return rows
        return hit[1]

    def get_price_info(self, symbol: str, now: float | None = None) -> dict:
        t = now if now is not None else time.time()
        hit = self._price.get(symbol)
        if hit and (t - hit[0]) < self._price_ttl:
            return hit[1]
        info = self._p.get_price_info(symbol)
        self._price[symbol] = (t, info)
        return info

    def stats(self) -> dict:
        return {"candle_keys": len(self._candles), "price_keys": len(self._price),
                "ttl_sec": self._ttl, "price_ttl_sec": self._price_ttl}


# ── FastAPI service (one shared cache for all agent processes) ───────
try:
    from fastapi import FastAPI

    app = FastAPI(title="Gecko Shared Feed", version="0.3.0")
    _cache = CandleCache(ttl_sec=float(os.environ.get("GECKO_FEED_TTL_SEC", "45")))

    @app.get("/healthz")
    def _healthz() -> dict:
        return {"ok": True, **_cache.stats()}

    @app.get("/candles")
    def _candles(symbol: str, bar: str = "5m", limit: int = 210) -> dict[str, Any]:
        return {"symbol": symbol, "bar": bar, "candles": _cache.get_candles(symbol, bar, limit)}

    @app.get("/price")
    def _price(symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, **_cache.get_price_info(symbol)}
except ImportError:  # FastAPI optional for pure-cache use
    app = None  # type: ignore[assignment]
