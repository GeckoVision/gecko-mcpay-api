"""Birdeye on-chain DEX OHLCV source adapter for the historical tape (s46).

Endpoint:
  GET https://public-api.birdeye.so/defi/ohlcv
    ?address=<mint>&type=<5m|15m|1H|4H>&time_from=<sec>&time_to=<sec>&currency=usd
  headers: x-api-key: <BIRDEYE_API_KEY>, x-chain: solana

Documented response shape (docs.birdeye.so):
  {"success": true, "data": {"items": [
      {"unixTime": <sec>, "o", "h", "l", "c", "v", "address", "type"}, ...]}}
  - unixTime : bar open time in SECONDS (we convert to ms for the canonical tape)
  - v        : volume in `currency` (usd) when currency=usd
  - max 1000 records / request -> paginate by walking time_from forward

WHY THIS EXISTS BUT IS SKIPPED HERE
  POPCAT (and any meme not listed on OKX spot) has no OKX -USDT history. Birdeye's
  on-chain DEX OHLCV covers it via the mint address. BIRDEYE_API_KEY is NOT set in
  this environment, so `collect_history` raises BirdeyeKeyMissing and the tape
  collector logs a clear "needs BIRDEYE_API_KEY" flag and moves on — it does NOT
  fabricate data or block the OKX-sourced tape.

The parser is real and TDD'd against the documented shape fixture so that the day
the key lands, collection is a config change, not a code change. (When the key is
present, the FIRST step is to capture a REAL response over the documented fixture
and re-run the TDD per Patterns B & E — do not trust this synthetic-shape fixture
as proof the live wire works.)
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

BIRDEYE_OHLCV_URL = "https://public-api.birdeye.so/defi/ohlcv"
BIRDEYE_MAX_RECORDS = 1000
TF_TO_BIRDEYE_TYPE: dict[str, str] = {"5m": "5m", "15m": "15m", "1H": "1H", "4H": "4H"}
TF_SECONDS: dict[str, int] = {"5m": 300, "15m": 900, "1H": 3600, "4H": 14400}


class BirdeyeKeyMissing(Exception):
    """BIRDEYE_API_KEY is not set — live Birdeye collection is skipped + flagged."""


class BirdeyeSourceError(Exception):
    """Birdeye returned a non-success envelope we cannot interpret."""


def api_key_present() -> bool:
    return bool(os.environ.get("BIRDEYE_API_KEY"))


def parse_response(payload: dict[str, Any]) -> list[dict[str, float]]:
    """Parse a Birdeye /defi/ohlcv envelope into canonical candle dicts.

    Converts unixTime (seconds) -> ts (ms) to match the OKX-sourced tape. Volume
    is taken as-is (usd when the request used currency=usd). Raises
    BirdeyeSourceError on success=false.
    """
    if not payload.get("success", False):
        raise BirdeyeSourceError(f"birdeye success=false: {payload.get('message')!r}")
    items = (payload.get("data") or {}).get("items") or []
    out: list[dict[str, float]] = []
    for it in items:
        if not isinstance(it, dict) or "unixTime" not in it:
            continue
        out.append(
            {
                "ts": float(it["unixTime"]) * 1000.0,  # sec -> ms (canonical)
                "open": float(it["o"]),
                "high": float(it["h"]),
                "low": float(it["l"]),
                "close": float(it["c"]),
                "volume": float(it["v"]),
            }
        )
    out.sort(key=lambda c: c["ts"])
    return out


def _default_fetcher(
    url: str, params: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    import httpx

    resp = httpx.get(url, params=params, headers=headers, timeout=20.0)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


def collect_history(
    mint: str,
    tf: str,
    *,
    lookback_s: int,
    now_s: int | None = None,
    max_calls: int = 40,
    sleep_s: float = 0.2,
    fetcher: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda _m: None,
) -> list[dict[str, float]]:
    """Walk Birdeye OHLCV forward in time_from windows until `lookback_s` covered.

    Raises BirdeyeKeyMissing if BIRDEYE_API_KEY is absent (unless a `fetcher` is
    injected, which only happens under test). Pagination: each window pulls up to
    BIRDEYE_MAX_RECORDS bars; advance time_from to just past the last bar.
    """
    if tf not in TF_TO_BIRDEYE_TYPE:
        raise BirdeyeSourceError(f"unsupported tf {tf!r}")
    key = os.environ.get("BIRDEYE_API_KEY")
    if fetcher is None and not key:
        raise BirdeyeKeyMissing(
            "BIRDEYE_API_KEY not set — Birdeye collection skipped. "
            "Set the key in env to enable on-chain DEX history (e.g. POPCAT)."
        )
    do_fetch = fetcher or _default_fetcher
    headers = {"x-api-key": key or "", "x-chain": "solana"}

    bar_s = TF_SECONDS[tf]
    end_s = now_s if now_s is not None else int(time.time())
    start_s = end_s - lookback_s
    merged: dict[float, dict[str, float]] = {}
    cursor = start_s

    for call in range(max_calls):
        window_to = min(cursor + BIRDEYE_MAX_RECORDS * bar_s, end_s)
        params = {
            "address": mint,
            "type": TF_TO_BIRDEYE_TYPE[tf],
            "time_from": cursor,
            "time_to": window_to,
            "currency": "usd",
        }
        payload = do_fetch(BIRDEYE_OHLCV_URL, params, headers)
        batch = parse_response(payload)
        if not batch:
            break
        for c in batch:
            merged[c["ts"]] = c
        newest_s = int(max(c["ts"] for c in batch) / 1000.0)
        log(f"  birdeye {mint[:6]}-{tf}: page {call + 1} +{len(batch)} (total {len(merged)})")
        if window_to >= end_s or newest_s + bar_s >= end_s:
            break
        cursor = newest_s + bar_s
        sleeper(sleep_s)

    return sorted(merged.values(), key=lambda c: c["ts"])
