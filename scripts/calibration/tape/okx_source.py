"""OKX public market REST source adapter for the historical tape (s46).

Endpoint (NO auth):
  https://www.okx.com/api/v5/market/history-candles?instId=<SYM>-USDT&bar=<bar>&after=<ms>&limit=<n>

Response envelope: {"code": "0", "msg": "", "data": [row, ...]} where each row is
  [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]  (all strings)
  - ts            : bar open time, ms epoch
  - vol           : base-ccy volume
  - volCcyQuote   : quote-ccy (USDT ≈ USD) volume  <- this is our USD volume
  - confirm       : "1" closed, "0" still forming  <- drop the forming bar

OKX returns rows NEWEST-FIRST (descending ts). Paginate backward with
`after=<oldest ts seen>` to walk into history. We normalise to the canonical tape
shape (ascending ts, forming bar dropped, USD volume from volCcyQuote).

Public-endpoint rate limit is ~20 req / 2s; we sleep between pages and cap total
calls per (symbol, tf) to stay polite.

Pure parsing/pagination-planning functions are kept network-free so they can be
TDD'd against a captured real fixture (tests/fixtures/tape/okx_*).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

OKX_HISTORY_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles"
OKX_MAX_LIMIT = 300  # history-candles honours up to 300 rows/call
OKX_OK_CODE = "0"
OKX_INST_NOT_EXIST_CODE = "51001"

# Bars supported by the tape. OKX bar strings are case-sensitive (5m/15m lower,
# 1H/4H upper). Approx duration in ms used for pagination bounds + sanity.
TF_TO_OKX_BAR: dict[str, str] = {"5m": "5m", "15m": "15m", "1H": "1H", "4H": "4H"}
TF_MS: dict[str, int] = {
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1H": 60 * 60_000,
    "4H": 4 * 60 * 60_000,
}


class OkxSourceError(Exception):
    """Raised when OKX returns a non-OK envelope we cannot interpret."""


def okx_instrument(symbol: str) -> str:
    """Map a tape symbol to its OKX spot instId (always quoted in USDT)."""
    return f"{symbol.upper()}-USDT"


def parse_response(payload: dict[str, Any]) -> list[dict[str, float]]:
    """Parse one OKX history-candles envelope into canonical candle dicts.

    Drops the forming bar (confirm == "0"). USD volume comes from volCcyQuote.
    Returns candles in the response's native order (newest-first); the collector
    re-sorts the merged tape ascending. Raises OkxSourceError on a bad envelope
    (except the "instrument not listed" case, which the caller handles).
    """
    code = str(payload.get("code", ""))
    if code != OKX_OK_CODE:
        raise OkxSourceError(f"OKX code={code} msg={payload.get('msg')!r}")
    rows = payload.get("data") or []
    out: list[dict[str, float]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 9:
            continue
        if str(row[8]) == "0":  # forming/unconfirmed bar — never persist
            continue
        out.append(
            {
                "ts": float(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                # quote-ccy (USDT≈USD) volume; vol[5] is base-ccy, volCcyQuote[7]
                # is the USD figure the tape standardises on.
                "volume": float(row[7]),
            }
        )
    return out


def oldest_ts(candles: list[dict[str, float]]) -> float | None:
    """Smallest ts in a candle batch (the next-page `after` cursor)."""
    return min((c["ts"] for c in candles), default=None)


def is_instrument_missing(payload: dict[str, Any]) -> bool:
    """True when OKX says the instId is not listed (e.g. POPCAT-USDT -> 51001)."""
    return str(payload.get("code", "")) == OKX_INST_NOT_EXIST_CODE


def _default_fetcher(url: str, params: dict[str, Any]) -> dict[str, Any]:
    import httpx

    resp = httpx.get(url, params=params, timeout=20.0)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


def fetch_history(
    symbol: str,
    tf: str,
    *,
    lookback_ms: int,
    max_calls: int = 80,
    page_limit: int = OKX_MAX_LIMIT,
    sleep_s: float = 0.15,
    fetcher: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda _m: None,
) -> tuple[list[dict[str, float]], bool]:
    """Page OKX history backward until `lookback_ms` is covered or data ends.

    Returns (candles_ascending, instrument_missing). When the instrument is not
    listed on OKX spot the second element is True and the list is empty — the
    caller routes that symbol/tf to Birdeye instead of failing the whole run.

    `fetcher`/`sleeper` are injected so tests drive this with the captured fixture
    and zero network/sleep.
    """
    if tf not in TF_TO_OKX_BAR:
        raise OkxSourceError(f"unsupported tf {tf!r}")
    bar = TF_TO_OKX_BAR[tf]
    inst = okx_instrument(symbol)
    do_fetch = fetcher or _default_fetcher

    merged: dict[float, dict[str, float]] = {}
    after: float | None = None
    newest_seen: float | None = None
    oldest_target: float | None = None

    for call in range(max_calls):
        params: dict[str, Any] = {"instId": inst, "bar": bar, "limit": page_limit}
        if after is not None:
            params["after"] = int(after)
        payload = do_fetch(OKX_HISTORY_CANDLES_URL, params)
        if is_instrument_missing(payload):
            log(f"  {symbol}-{tf}: instrument not listed on OKX (code 51001)")
            return [], True
        batch = parse_response(payload)
        if not batch:
            break
        for c in batch:
            merged[c["ts"]] = c
        page_oldest = oldest_ts(batch)
        if newest_seen is None:
            newest_seen = max(c["ts"] for c in batch)
            oldest_target = newest_seen - lookback_ms
        log(
            f"  {symbol}-{tf}: page {call + 1} +{len(batch)} bars "
            f"(total {len(merged)}), oldest={int(page_oldest or 0)}"
        )
        if page_oldest is None or oldest_target is None:
            break
        if page_oldest <= oldest_target:
            break
        after = page_oldest
        sleeper(sleep_s)

    candles = sorted(merged.values(), key=lambda c: c["ts"])
    return candles, False
