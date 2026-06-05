"""based.bid token candle feed (Arena infra) — OHLCV for launchpad tokens.

The based.bid "Agentic Trading Battle" runs on Gecko: agents trade based.bid's
tokens, our safety layer scores them. To do that, our strategies + backtest need
OHLCV for those tokens — same `get_candles` / `get_price_info` interface the OKX
spot provider exposes, so it's a DROP-IN feed (`_get_oc()` swap, no strategy change).

Data source: **GeckoTerminal** (CoinGecko's on-chain API) — free, no key, real DEX
OHLCV candles for Solana (and EVM) pools. A based.bid token that graduated to
Raydium/Uniswap has a pool there; we resolve token → top pool → OHLCV.

Scope (v1): POST-graduation tokens (those with a DEX pool). Pre-graduation tokens
still on based.bid's bonding curve have no DEX pool yet → `get_candles` returns []
(handled gracefully); covering the bonding-curve phase needs based.bid's own price
API (a documented follow-on; their public API wasn't at the obvious paths 2026-06-05).

The arena TOKEN LIST (which tokens are in play) comes from based.bid and is passed
in / configured — this module is the price feed, not the token registry.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

_GT_BASE = "https://api.geckoterminal.com/api/v2"
_HTTP_TIMEOUT = 8.0

# our bar string → (GeckoTerminal timeframe, aggregate)
_BAR: dict[str, tuple[str, int]] = {
    "1m": ("minute", 1), "5m": ("minute", 5), "15m": ("minute", 15),
    "1h": ("hour", 1), "1H": ("hour", 1), "4h": ("hour", 4), "1d": ("day", 1), "1D": ("day", 1),
}


class BasedBidCandleProvider:
    """OHLCV for based.bid tokens via GeckoTerminal. Mirrors OkxSpotCandleProvider."""

    def __init__(
        self, *, network: str = "solana", max_retries: int = 3,
        base_url: str = _GT_BASE, http_client: httpx.Client | None = None,
        min_interval: float = 2.2,
    ) -> None:
        self.network = network
        self._max_retries = max_retries
        self._base = base_url.rstrip("/")
        self._client = http_client  # injectable for tests
        self._pool_cache: dict[str, str | None] = {}  # token mint → top pool addr (or None)
        # GeckoTerminal free tier ≈ 30 req/min → throttle to stay under it. A live
        # board scores N tokens × 2 calls (pool + ohlcv); without this it trips 429
        # and the board comes back half-empty + flaky run-to-run.
        self._min_interval = min_interval
        self._last_req = 0.0

    # ── HTTP ───────────────────────────────────────────────────────────────
    def _throttle(self) -> None:
        if self._client is not None:  # injected client (tests) → no real network, no wait
            return
        wait = self._min_interval - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.time()

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base}{path}"
        headers = {"Accept": "application/json", "User-Agent": "gecko-arena/0.1"}
        if self._client is not None:
            return self._client.get(url, headers=headers, timeout=_HTTP_TIMEOUT).json()
        # 429-aware: throttle ahead of each call, back off harder on rate-limit.
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            self._throttle()
            try:
                with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
                    r = c.get(url, headers=headers)
                    if r.status_code == 429:
                        time.sleep(self._min_interval * (attempt + 2))  # widen the window
                        last_exc = httpx.HTTPStatusError("429", request=r.request, response=r)
                        continue
                    r.raise_for_status()
                    return r.json()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response is not None and exc.response.status_code != 429:
                    raise
                time.sleep(self._min_interval * (attempt + 1))
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("unreachable")

    def _resolve_pool(self, token: str) -> str | None:
        """Top (highest-liquidity) DEX pool for a token mint, or None (pre-graduation).

        Cache ONLY a definitive answer: a successful lookup (real pool, or a confirmed
        empty list = genuinely pre-graduation). A lookup that *errors* (e.g. a 429) is
        NOT cached — otherwise one rate-limited call poisons the cache and the token is
        treated as "no pool" for the life of the provider, half-emptying the board."""
        if token in self._pool_cache:
            return self._pool_cache[token]
        try:
            body = self._get(f"/networks/{self.network}/tokens/{token}/pools")
        except Exception:
            return None  # transient — do NOT cache, let the next call retry
        data = body.get("data") or []
        pool = data[0].get("attributes", {}).get("address") if data else None
        self._pool_cache[token] = pool  # definitive (real pool or confirmed empty)
        return pool

    # ── public interface (matches OkxSpotCandleProvider) ─────────────────────
    def get_candles(
        self, token: str, bar: str = "5m", limit: int = 100, drop_forming: bool = True
    ) -> list[dict[str, Any]]:
        pool = self._resolve_pool(token)
        if not pool:
            return []  # pre-graduation / unknown token — no DEX OHLCV
        tf, agg = _BAR.get(bar, ("minute", 5))
        path = f"/networks/{self.network}/pools/{pool}/ohlcv/{tf}?aggregate={agg}&limit={int(limit)}"
        rows: list[list[float]] = []
        for attempt in range(self._max_retries):
            try:
                body = self._get(path)
                rows = body.get("data", {}).get("attributes", {}).get("ohlcv_list") or []
                break
            except Exception:
                if attempt == self._max_retries - 1:
                    return []
                time.sleep(0.5 * (attempt + 1))

        result: list[dict[str, Any]] = []
        for row in rows:
            # GeckoTerminal OHLCV row: [ts_sec, open, high, low, close, volume_usd]
            ts, o, h, low_, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
            result.append({
                "ts": float(ts), "open": float(o or 0), "high": float(h or 0),
                "low": float(low_ or 0), "close": float(c or 0), "volume": float(v or 0),
                "vol_usd": float(v or 0),  # GeckoTerminal volume is already USD
                "confirm": 1,
            })
        # GeckoTerminal returns DESCENDING (newest first) → sort ascending; same
        # invariant okx_feed/onchainos enforce (mis-ordered series corrupts indicators).
        result.sort(key=lambda r: r["ts"])
        if result:
            result[-1]["confirm"] = 0  # newest = forming bar
            if drop_forming:
                result.pop()
        return result

    def get_price_info(self, token: str) -> dict[str, Any]:
        """{"data": {"price": <float>}} — last closed candle's close."""
        candles = self.get_candles(token, bar="5m", limit=2, drop_forming=False)
        price = candles[-1]["close"] if candles else 0.0
        return {"data": {"price": price}}
