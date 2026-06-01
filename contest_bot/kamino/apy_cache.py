"""Cached Kamino USDC supply-APY lookup.

We don't want to hit Kamino's REST API on every poll. The bot polls every
few seconds — Kamino's supply APY moves on the scale of hours. A 6h TTL
on a single GET keeps the network footprint trivial and keeps us within
"published APY" accuracy bands.

Failure mode: if the API call fails, we DO NOT raise into the bot loop.
We fall back to the env-configurable `GECKO_KAMINO_APY_FALLBACK` (default
0.0 — accrue NOTHING rather than overstate). The caller can inspect
`last_fetch_status` to log staleness.

Live snapshot verified 2026-05-31 from
    https://api.kamino.finance/kamino-market/{MAIN_MARKET}/reserves/metrics
USDC reserve (D6q6wuQSrifJKZYpR1M8R4YawnLDtDsMmWM1NbBmgJ59) → supply_apy = 0.04215.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Final

import httpx

# Live, verified addresses (see docs/build-plan-sprint-25-kamino-paper-sink.md §4).
KAMINO_MAIN_MARKET: Final[str] = "7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF"
KAMINO_USDC_RESERVE: Final[str] = "D6q6wuQSrifJKZYpR1M8R4YawnLDtDsMmWM1NbBmgJ59"
USDC_MINT: Final[str] = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

KAMINO_API_BASE: Final[str] = "https://api.kamino.finance"
_RESERVES_ENDPOINT: Final[str] = "/kamino-market/{market}/reserves/metrics"

_DEFAULT_TTL_SEC: Final[int] = 21_600  # 6h
_DEFAULT_FALLBACK_APY: Final[float] = 0.0  # accrue nothing on error
_HTTP_TIMEOUT_SEC: Final[float] = 5.0

logger = logging.getLogger("kamino.apy_cache")


@dataclass
class APYReading:
    apy: float
    fetched_at: float  # unix sec
    source: str  # "live" | "fallback" | "override" | "cache"


@dataclass
class KaminoAPYCache:
    """Per-process cache. Cheap to construct; safe to share across threads
    only insofar as the bot is single-threaded (it is).

    `last_fetch_status` is purely diagnostic — never load-bearing.
    """

    ttl_sec: int = _DEFAULT_TTL_SEC
    fallback_apy: float = _DEFAULT_FALLBACK_APY
    override_apy: float | None = None  # if set, bypass network entirely
    api_base: str = KAMINO_API_BASE
    market: str = KAMINO_MAIN_MARKET
    reserve: str = KAMINO_USDC_RESERVE

    _cached: APYReading | None = field(default=None, init=False)
    last_fetch_status: str = field(default="never", init=False)

    @classmethod
    def from_env(cls) -> KaminoAPYCache:
        return cls(
            ttl_sec=int(os.environ.get("GECKO_KAMINO_APY_TTL_SEC", _DEFAULT_TTL_SEC)),
            fallback_apy=float(os.environ.get("GECKO_KAMINO_APY_FALLBACK", _DEFAULT_FALLBACK_APY)),
            override_apy=_parse_optional_float(os.environ.get("GECKO_KAMINO_APY_OVERRIDE")),
        )

    def get_apy(self, now: float | None = None) -> float:
        """Return the current supply APY as a fraction (e.g. 0.0421).

        - Override > cache (if fresh) > network > fallback.
        - Never raises.
        """
        if self.override_apy is not None:
            self._cached = APYReading(self.override_apy, now or time.time(), "override")
            self.last_fetch_status = "override"
            return self.override_apy

        ts = now if now is not None else time.time()
        if self._cached is not None and (ts - self._cached.fetched_at) < self.ttl_sec:
            self.last_fetch_status = "cache_hit"
            return self._cached.apy

        try:
            fresh = self._fetch_live()
            self._cached = APYReading(fresh, ts, "live")
            self.last_fetch_status = "live"
            return fresh
        except Exception as exc:
            logger.warning(
                "kamino apy fetch failed (%s: %s); falling back to %.4f",
                type(exc).__name__,
                exc,
                self.fallback_apy,
            )
            # If we had a stale cache, prefer it over fallback — it's still
            # a real number even if past TTL. Otherwise fallback.
            if self._cached is not None:
                self.last_fetch_status = f"stale_cache:{type(exc).__name__}"
                return self._cached.apy
            self._cached = APYReading(self.fallback_apy, ts, "fallback")
            self.last_fetch_status = f"fallback:{type(exc).__name__}"
            return self.fallback_apy

    def _fetch_live(self) -> float:
        url = self.api_base + _RESERVES_ENDPOINT.format(market=self.market)
        with httpx.Client(timeout=_HTTP_TIMEOUT_SEC) as client:
            resp = client.get(url)
            resp.raise_for_status()
            body = resp.json()
        if not isinstance(body, list):
            raise ValueError(f"Kamino reserves endpoint returned non-list: {type(body)}")
        for row in body:
            if row.get("reserve") == self.reserve:
                apy = row.get("supplyApy")
                if apy is None:
                    raise ValueError(f"Reserve {self.reserve} has no supplyApy")
                return float(apy)
        raise ValueError(f"USDC reserve {self.reserve} not found in {len(body)} reserves")


def _parse_optional_float(raw: str | None) -> float | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid GECKO_KAMINO_APY_OVERRIDE=%r; ignoring", raw)
        return None
