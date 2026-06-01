"""Pyth Hermes REST client — Sprint 29 Phase 1.

REST-only (NOT SSE — the gecko-core hotpath/pyth.py uses streaming,
which is more complex than we need for 60s polling). Free public API,
no key required.

Wire reference:
  GET https://hermes.pyth.network/v2/updates/price/latest?ids[]=<id>...
  Returns: {"binary": ..., "parsed": [{"id": "...", "price": {...}}, ...]}

Each parsed entry has:
  price: int (price × 10**(-expo))
  conf:  int (confidence interval × 10**(-expo))
  expo:  int (negative power-of-10)
  publish_time: int (unix seconds)

This client returns a dict {symbol → PriceSnapshot} so the sink can
write one Mongo row per symbol per poll.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import httpx

logger = logging.getLogger("contest_bot.oracle.pyth")

PYTH_HERMES_BASE_URL: Final[str] = "https://hermes.pyth.network"

# Feed IDs verified via https://hermes.pyth.network/v2/price_feeds.
# Pinned here so a Pyth website restructure doesn't silently break us;
# add new symbols by appending to this dict.
PYTH_FEED_IDS: Final[dict[str, str]] = {
    "SOL": "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    "USDC": "eaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
    "PYTH": "0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff",
    "WIF": "4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc",
    "BTC": "e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "ETH": "ff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
}


@dataclass(frozen=True)
class PriceSnapshot:
    """One symbol's price snapshot from Pyth at a single point in time."""

    symbol: str
    feed_id: str
    price: float
    confidence: float
    spread_pct: float  # confidence / price × 100 — how wide the band is
    publish_time: int  # unix seconds
    source: str = "pyth"


class PythHermesRestClient:
    """Stateless REST poller. Cheap to construct; reuse for multi-symbol fetch."""

    def __init__(
        self,
        base_url: str = PYTH_HERMES_BASE_URL,
        timeout_s: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def fetch(self, symbols: list[str]) -> dict[str, PriceSnapshot]:
        """Fetch latest prices for the given symbols. Synchronous (called
        from a cron'd script, not the bot's hot path)."""
        feed_ids = [
            (sym.upper(), PYTH_FEED_IDS[sym.upper()])
            for sym in symbols
            if sym.upper() in PYTH_FEED_IDS
        ]
        if not feed_ids:
            return {}

        # Build the query: ids[]=...&ids[]=...&parsed=true
        params: list[tuple[str, str]] = [("ids[]", fid) for _sym, fid in feed_ids]
        params.append(("parsed", "true"))
        url = f"{self._base_url}/v2/updates/price/latest"

        try:
            resp = httpx.get(url, params=params, timeout=self._timeout_s)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("pyth.fetch_failed err=%s", type(exc).__name__)
            return {}

        parsed_list = data.get("parsed", []) if isinstance(data, dict) else []
        # feed_id → symbol reverse lookup
        sym_by_feed = {fid: sym for sym, fid in feed_ids}

        out: dict[str, PriceSnapshot] = {}
        for entry in parsed_list:
            try:
                feed_id = str(entry.get("id", "")).lstrip("0x").lower()
                if feed_id not in sym_by_feed:
                    continue
                price_block = entry.get("price") or {}
                raw_price = int(price_block.get("price", 0))
                conf = int(price_block.get("conf", 0))
                expo = int(price_block.get("expo", 0))
                publish_time = int(price_block.get("publish_time", 0))
                scale = 10**expo
                price_float = raw_price * scale
                conf_float = conf * scale
                if price_float <= 0:
                    continue
                spread_pct = (conf_float / price_float) * 100.0
                sym = sym_by_feed[feed_id]
                out[sym] = PriceSnapshot(
                    symbol=sym,
                    feed_id=feed_id,
                    price=price_float,
                    confidence=conf_float,
                    spread_pct=spread_pct,
                    publish_time=publish_time,
                )
            except Exception as exc:
                logger.warning("pyth.parse_failed entry_keys=%s err=%s",
                               list(entry.keys()) if isinstance(entry, dict) else None,
                               type(exc).__name__)
                continue
        return out


__all__ = ["PriceSnapshot", "PythHermesRestClient", "PYTH_FEED_IDS"]
