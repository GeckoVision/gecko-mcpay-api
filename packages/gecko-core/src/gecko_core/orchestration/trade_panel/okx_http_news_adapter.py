"""OKX V5 direct-HTTP news provider — reworked (context-engineering, 2026-06-16).

Phase 2.1 shipped this adapter against a GUESSED REST shape
(``OKX_NEWS_API_URL`` + ``Authorization: Bearer``). That was wrong. This rework
hits the REAL OKX V5 news endpoint with the REAL auth model, reverse-engineered
from the ``@okx_ai/okx-trade-cli`` source (``okx-files/agent-trade-kit``):

GROUND TRUTH (packages/core/src/tools/news.ts + client/rest-client.ts):
  - Base host: ``https://www.okx.com`` (constants.ts ``OKX_API_BASE_URL``).
  - News browse/by-coin/search all hit ONE path:
    ``/api/v5/orbit/news-search`` (a "private" GET in the CLI).
  - Auth model is DUAL in the CLI (rest-client.ts ``applyAuth``):
      1. apiKey + secretKey + passphrase present -> OKX V5 HMAC signing
         (headers OK-ACCESS-KEY / -SIGN / -PASSPHRASE / -TIMESTAMP).
         **No OAuth fallback** when an API key is configured.
      2. else -> OAuth2.1 Bearer token via the ``okx-auth`` binary.
    The founder is provisioning AK + SK (+ passphrase) as env creds, so we take
    the HMAC path — it is fully reproducible in Python (stdlib hmac), needs no
    token-exchange binary, and no subprocess. CLI-shell was rejected: it would
    require shipping the Node CLI + ``~/.okx/config.toml`` into ECS and shelling
    out per request; the HMAC HTTP path is smaller, testable, and secret-clean.

OKX V5 HMAC signature (signature.ts + OKX V5 spec):
  timestamp = UTC ISO-8601 millis, e.g. "2026-06-16T12:00:00.000Z"
  prehash   = timestamp + METHOD + requestPath + body
              (requestPath INCLUDES the "?query" string; body is "" for GET)
  sign      = base64( HMAC-SHA256(secretKey, prehash) )
  headers   = OK-ACCESS-KEY / OK-ACCESS-SIGN / OK-ACCESS-PASSPHRASE /
              OK-ACCESS-TIMESTAMP  (+ Content-Type/Accept JSON, Accept-Language)

Provider-neutral by construction: satisfies the same ``NewsProvider`` protocol
as every other adapter; the panel never imports it directly (only the ENV-gated
factory does).

CONFIG (read by the factory, not here):
  - ``OKX_TRADING_API_KEY``     — OK-ACCESS-KEY. NEVER logged.
  - ``OKX_TRADING_SECRET_KEY``  — HMAC secret. NEVER logged.
  - ``OKX_TRADING_PASSPHRASE``  — OK-ACCESS-PASSPHRASE. NEVER logged.
  (The OnchainOS developer OK-ACCESS-KEY is a DIFFERENT key and does NOT serve
  news — do not wire it here.)

FAIL-OPEN: any network / parse / auth error returns an empty list. The panel
merges ``[]`` as a no-op, so news being down NEVER breaks the verdict.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from gecko_core.orchestration.trade_panel.news_provider import (
    NewsProvider,
    build_news_chunk,
)

_log = logging.getLogger(__name__)

# Canonical OKX V5 host + news path (from the okx-trade-cli source).
_OKX_BASE_URL = "https://www.okx.com"
_NEWS_SEARCH_PATH = "/api/v5/orbit/news-search"

# Network budget — the panel's round-1 must not stall on a slow news endpoint.
# Fail-OPEN on timeout: the sentiment voice runs corpus-only, exactly as today.
_HTTP_TIMEOUT_S = 4.0

# The panel passes a `protocol` — often a slug ("jupiter", "kamino") — but OKX
# news `ccyList` wants the asset TICKER ("JUP", "KMNO"). Without this map a
# protocol-shaped query resolves to e.g. "JUPITER" and OKX returns no articles
# (silently, fail-OPEN). Only HIGH-CONFIDENCE slug→ticker pairs go here; anything
# unmapped falls through to ``proto.upper()`` — correct for inputs that are
# ALREADY tickers ("SOL", "BTC") and harmlessly returns no news for unknown
# slugs (today's behavior). Add a pair only when the ticker is certain.
_SLUG_TO_TICKER: dict[str, str] = {
    "jupiter": "JUP",
    "kamino": "KMNO",
    "raydium": "RAY",
    "orca": "ORCA",
    "drift": "DRIFT",
    "marinade": "MNDE",
    "jito": "JTO",
    "tensor": "TNSR",
    "pyth": "PYTH",
    "bonk": "BONK",
    "solana": "SOL",
}


def _ccy_for(protocol: str) -> str:
    """Resolve a panel protocol/slug to an OKX ``ccyList`` ticker.

    Known slug → its ticker; otherwise upper-case passthrough (already-ticker
    inputs work; unknown slugs return no news, same as before this map).
    """
    return _SLUG_TO_TICKER.get(protocol.strip().lower(), protocol.strip().upper())


def _okx_timestamp() -> str:
    """UTC ISO-8601 with millisecond precision + ``Z`` — the OKX V5 format.

    Mirrors the CLI's ``new Date().toISOString()`` (signature.ts ``getNow``),
    which yields e.g. ``2026-06-16T12:00:00.000Z``. Python's default isoformat
    uses ``+00:00`` and microseconds, both of which OKX rejects, so we format
    explicitly.
    """
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _sign(secret_key: str, prehash: str) -> str:
    """base64(HMAC-SHA256(secret, prehash)) — the OKX V5 signature."""
    digest = hmac.new(secret_key.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class OKXHttpNewsProvider:
    """NewsProvider backed by the OKX V5 ``/api/v5/orbit/news-search`` endpoint.

    Satisfies the ``NewsProvider`` protocol. Construct only via the ENV-gated
    factory (``news_factory.build_news_provider``) so prod never wires it
    without ``OKX_TRADING_API_KEY`` + ``OKX_TRADING_SECRET_KEY`` (+ passphrase)
    present.
    """

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        passphrase: str = "",
        base_url: str = _OKX_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._passphrase = passphrase
        self._base_url = base_url.rstrip("/")
        # Injectable client for tests (httpx.MockTransport, vcr-style).
        self._client = client

    async def fetch_news_chunks(
        self,
        protocol: str,
        *,
        max_results: int = 5,
        as_of: Any = None,
    ) -> list[dict[str, Any]]:
        proto = (protocol or "").strip()
        if not proto:
            return []

        try:
            articles = await self._fetch_articles(proto, max_results)
        except Exception as exc:
            # Fail-OPEN. Class name only — the URL/key/secret/passphrase must
            # never reach logs.
            _log.warning(
                "okx_http_news.fetch_failed protocol=%s err=%s",
                proto,
                type(exc).__name__,
            )
            return []

        chunks: list[dict[str, Any]] = []
        for a in articles[:max_results]:
            headline = (a.get("title") or a.get("headline") or "").strip()
            if not headline:
                continue
            body = (
                a.get("summary") or a.get("fullText") or a.get("body") or a.get("description") or ""
            ).strip()
            chunks.append(
                build_news_chunk(
                    headline=headline,
                    body=body,
                    url=a.get("url") or a.get("link") or a.get("sourceUrl"),
                    published_ts=_extract_published(a),
                    protocol=proto,
                )
            )
        return chunks

    async def _fetch_articles(self, proto: str, max_results: int) -> list[dict[str, Any]]:
        """Signed GET against ``/api/v5/orbit/news-search`` (coin-scoped).

        Query mirrors the CLI's ``news_get_by_coin`` handler: ``sortBy=latest``,
        ``ccyList=<TICKER>``, ``limit=<n>``. ``ccyList`` needs the asset TICKER,
        so a panel protocol/slug ("jupiter") is resolved via ``_ccy_for``
        (→"JUP"); already-ticker inputs ("SOL") pass through. Anything OKX can't
        resolve simply returns no articles, which fails-OPEN at the call site.
        """
        # Build the query string in a stable order and sign over the EXACT
        # request path (path + "?query"), per the OKX V5 prehash rule.
        params: dict[str, str | int] = {
            "sortBy": "latest",
            "ccyList": _ccy_for(proto),
            "limit": max_results,
        }
        request = httpx.Request("GET", self._base_url + _NEWS_SEARCH_PATH, params=params)
        # request.url.raw_path is bytes of "/path?query"; sign over that exact string.
        request_path = request.url.raw_path.decode("ascii")
        headers = self._auth_headers("GET", request_path, body="")

        if self._client is not None:
            resp = await self._client.get(
                self._base_url + _NEWS_SEARCH_PATH, params=params, headers=headers
            )
            resp.raise_for_status()
            return _normalize_articles(resp.json())
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
            resp = await client.get(
                self._base_url + _NEWS_SEARCH_PATH, params=params, headers=headers
            )
            resp.raise_for_status()
            return _normalize_articles(resp.json())

    def _auth_headers(self, method: str, request_path: str, *, body: str) -> dict[str, str]:
        """OKX V5 HMAC auth headers. Never logged; never returned to callers."""
        timestamp = _okx_timestamp()
        prehash = f"{timestamp}{method.upper()}{request_path}{body}"
        signature = _sign(self._secret_key, prehash)
        headers = {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "en-US",
        }
        # Passphrase is part of the OKX V5 HMAC scheme; omit the header only when
        # truly absent so a key configured without a passphrase still attempts.
        if self._passphrase:
            headers["OK-ACCESS-PASSPHRASE"] = self._passphrase
        return headers


def _extract_published(a: dict[str, Any]) -> str | None:
    """Resolve a published timestamp across OKX + generic field names.

    OKX V5 ``orbit/news-search`` items carry ``cTime`` as epoch-millis (verified
    live 2026-06-16); older/other feeds may use ``publishTime`` / ``publishedAt``
    / ``created_at`` / ``published_ts``. Epoch-millis are converted to ISO-8601
    UTC so the chunk shape is uniform; non-numeric values pass through unchanged
    (build_news_chunk stores as-is).
    """
    raw = (
        a.get("cTime")
        or a.get("publishTime")
        or a.get("published_ts")
        or a.get("publishedAt")
        or a.get("created_at")
    )
    if raw is None:
        return None
    # Epoch-millis (OKX) -> ISO-8601 UTC.
    s = str(raw)
    if s.isdigit():
        try:
            return datetime.fromtimestamp(int(s) / 1000, tz=UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            return s
    return s


def _normalize_articles(payload: Any) -> list[dict[str, Any]]:
    """Pull the article list out of the OKX V5 news response shape.

    GROUND TRUTH (verified live 2026-06-16 against /api/v5/orbit/news-search):
    the real shape nests articles one level below ``data`` ::

        {"code": "0", "data": [{"details": [<article>, ...], "nextCursor": ...}]}

    i.e. ``data`` is a one-element list of *envelope* objects, each carrying the
    real articles under ``details`` (NOT directly under ``data``). The original
    adapter returned ``data`` itself — a list of ``{details, nextCursor}`` dicts
    with no ``title`` — so the chunk-build loop skipped every item and news was
    silently empty (0 chunks, no error). We unwrap ``details`` when present, and
    still tolerate a flat list / the other common wrappers for forward-compat.
    """
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        # OKX V5: unwrap each envelope's ``details`` list when present.
        unwrapped: list[dict[str, Any]] = []
        envelope_seen = False
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("details"), list):
                envelope_seen = True
                unwrapped.extend(a for a in item["details"] if isinstance(a, dict))
        if envelope_seen:
            return unwrapped
        # No ``details`` envelope → ``data`` is already a flat article list.
        return [a for a in data if isinstance(a, dict)]
    for key in ("articles", "news", "results", "items"):
        v = payload.get(key)
        if isinstance(v, list):
            return [a for a in v if isinstance(a, dict)]
    return []


# Import-time protocol-conformance guard (catches drift, like okx_news_adapter).
assert isinstance(OKXHttpNewsProvider(api_key="k", secret_key="s", passphrase="p"), NewsProvider)


__all__ = ["OKXHttpNewsProvider"]
