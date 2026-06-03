"""OkxSpotCandleProvider — a drop-in candle/price feed for the live runtime when
`GECKO_VENUE=okx_spot` (majors universe).

It duck-types the two methods the monolith's poll/monitor lifecycle uses via
`_get_oc()`: `get_candles()` and `get_price_info()`. Swapping `oc` to this object
re-points the whole lifecycle onto OKX spot with ZERO order-routing surface:
- ccxt.okx instantiated with NO API keys → public-data only. There is physically
  no code path here to place an order. That is the PAPER-mode safety guarantee.
- Output matches the OnchainOS contract exactly: list of
  {ts, open, high, low, close, volume, vol_usd, confirm}, ASCENDING (oldest-first),
  forming bar dropped when drop_forming=True (mirrors onchainos.get_candles, which
  fixed the "enter at exhausted micro-tops" forming-bar bug — we must not reintroduce it).

The universe builder reuses the `mint` slot to carry the ccxt market symbol
("BTC/USDT"), so every existing caller (`evaluate_breakout`, `evaluate_volume_spike`,
`btc_overlay`) passes that string straight through. Solana mint constants the bot
still references (BTC_WBTC_MINT for the always-on BTC overlay) are aliased to their
OKX symbol so the overlay keeps working on real OKX BTC candles.
"""

from __future__ import annotations

import time
from typing import Any

import ccxt  # type: ignore[import-untyped]  # project dep (ccxt_spine, ingest_ccxt_*)

# Solana mints the monolith hardcodes → OKX spot symbols (BTC overlay etc.)
_MINT_ALIAS = {
    "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh": "BTC/USDT",  # BTC_WBTC_MINT
}

# OnchainOS bar codes → ccxt timeframe codes
_BAR = {
    "1s": "1s",
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1H": "1h",
    "4H": "4h",
    "1D": "1d",
    "1W": "1w",
}


class OkxSpotCandleProvider:
    def __init__(self, *, max_retries: int = 3, feed_url: str | None = None) -> None:
        # public-data only: no apiKey/secret → cannot trade by construction
        self._x = ccxt.okx({"enableRateLimit": True})
        self._max_retries = max_retries
        # Phase 3: when a shared-feed URL is given (orchestrator sets GECKO_FEED_URL),
        # read candles/price from that ONE cache service instead of hitting OKX per
        # agent. Falls back to direct ccxt on any service error. NB: the feed service
        # itself constructs this provider WITHOUT feed_url (→ direct), so no loop.
        self._feed_url = (feed_url or "").rstrip("/") or None

    def _sym(self, token: str) -> str:
        s = _MINT_ALIAS.get(token, token)
        return s if "/" in s else f"{s}/USDT"

    def _from_feed_candles(self, sym: str, bar: str, limit: int, drop_forming: bool):
        import httpx

        r = httpx.get(
            f"{self._feed_url}/candles",
            params={"symbol": sym, "bar": bar, "limit": int(limit)},
            timeout=8.0,
        )
        r.raise_for_status()
        rows = r.json().get("candles") or []
        # the feed already dropped the forming bar; honor an explicit keep request
        if not drop_forming and rows:
            rows[-1]["confirm"] = rows[-1].get("confirm", 1)
        return rows

    def get_candles(
        self, token: str, bar: str = "1H", limit: int = 100, drop_forming: bool = True
    ) -> list[dict[str, Any]]:
        sym = self._sym(token)
        if self._feed_url:
            try:
                return self._from_feed_candles(sym, bar, limit, drop_forming)
            except Exception:  # service down → fall back to direct ccxt below
                pass
        tf = _BAR.get(bar, bar)
        raw: list[list[float]] = []
        for attempt in range(self._max_retries):
            try:
                raw = self._x.fetch_ohlcv(sym, timeframe=tf, limit=int(limit))
                break
            except Exception:
                if attempt == self._max_retries - 1:
                    return []
                time.sleep(0.5 * (attempt + 1))
        result: list[dict[str, Any]] = []
        for row in raw:
            # ccxt OHLCV row: [ts_ms, open, high, low, close, volume]
            ts_ms, o, h, low_, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
            result.append(
                {
                    "ts": float(ts_ms) / 1000.0,
                    "open": float(o or 0),
                    "high": float(h or 0),
                    "low": float(low_ or 0),
                    "close": float(c or 0),
                    "volume": float(v or 0),
                    "vol_usd": float(c or 0) * float(v or 0),  # OKX OHLCV has no USD vol field
                    "confirm": 1,
                }
            )
        # ccxt returns ascending already; guard anyway (a mis-ordered series
        # silently corrupts every indicator — same invariant onchainos enforces).
        result.sort(key=lambda r: r["ts"])
        # ccxt's last bar is the CURRENT forming candle → mark + drop it, mirroring
        # onchainos drop_forming so breakout/overlay reason over CLOSED bars only.
        if result:
            result[-1]["confirm"] = 0
            if drop_forming:
                result.pop()
        return result

    def get_price_info(self, token: str) -> dict[str, Any]:
        """Match _spot_from_price_response: {"data": {"price": <float>}}."""
        sym = self._sym(token)
        try:
            last = self._x.fetch_ticker(sym).get("last")
            return {"data": {"price": float(last or 0)}}
        except Exception:
            return {"data": {"price": 0.0}}
