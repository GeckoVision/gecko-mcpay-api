"""CoinGecko market + venue-distribution client.

Wire reference: https://docs.coingecko.com/reference (public API v3). Free tier
works with no key; a Pro key (``x-cg-pro-api-key``) lifts rate limits.

CoinGecko's value for the safety layer isn't price — it's **where trading is
happening**. ``/coins/{id}/tickers`` shows every venue + its share of volume, so
we can flag a token whose liquidity is concentrated on a single low-trust venue
(a real rug/illiquidity risk) versus one traded broadly across reputable venues.

Structured market-data source — httpx + pydantic only; not a RAG/corpus source.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# On-chain (GeckoTerminal) API — token data BY CONTRACT ADDRESS. Unlike the
# coin-id `/coins/markets` surface, this resolves a raw SPL mint directly and
# exposes both market cap AND on-chain DEX liquidity (`total_reserve_in_usd`),
# which is the input for the thin-liquidity / fake-market-cap manipulation read.
#
# Uses GeckoTerminal's PUBLIC API directly (free, keyless, ~30 req/min). The
# CoinGecko-hosted mirror (`api.coingecko.com/api/v3/onchain/...`) was gated to
# paid keys in 2026 — calling it keyless now 401s, which silently broke the
# manipulation read (every token fell through to manipulation_check_unavailable).
# The two share identical `data.attributes` field names, so only the base moves.
COINGECKO_ONCHAIN_BASE_URL = "https://api.geckoterminal.com/api/v2"

# A venue is "low trust" below this CoinGecko trust_score tier.
_TRUST_RANK = {"red": 0, "yellow": 1, "green": 2}


class CoinGeckoMarket(BaseModel):
    """One row of ``/coins/markets``."""

    model_config = ConfigDict(extra="ignore")

    id: str
    symbol: str | None = None
    name: str | None = None
    current_price: float | None = None
    total_volume: float | None = None
    market_cap: float | None = None
    market_cap_rank: int | None = None
    price_change_percentage_24h: float | None = None


class _MarketRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    identifier: str | None = None


class CoinGeckoTicker(BaseModel):
    """One venue ticker from ``/coins/{id}/tickers``."""

    model_config = ConfigDict(extra="ignore")

    base: str | None = None
    target: str | None = None
    market: _MarketRef = Field(default_factory=_MarketRef)
    volume: float | None = None
    converted_volume: dict[str, float] = Field(default_factory=dict)
    trust_score: str | None = None
    bid_ask_spread_percentage: float | None = None

    @property
    def venue(self) -> str:
        return self.market.name or "?"

    @property
    def usd_volume(self) -> float:
        return float(self.converted_volume.get("usd") or 0.0)


@dataclass(frozen=True)
class VenueDistribution:
    """Where a token actually trades — a liquidity-concentration risk read.

    ``top_venue_share`` near 1.0 (one venue dominates) or a high
    ``low_trust_share`` is a risk-off signal for the pre-trade gate.
    """

    coin_id: str
    venue_count: int
    total_usd_volume: float
    top_venue: str
    top_venue_share: float
    low_trust_share: float


def _venue_distribution(coin_id: str, tickers: list[CoinGeckoTicker]) -> VenueDistribution:
    by_venue: dict[str, float] = {}
    low_trust_vol = 0.0
    for t in tickers:
        v = t.usd_volume
        by_venue[t.venue] = by_venue.get(t.venue, 0.0) + v
        if t.trust_score is not None and _TRUST_RANK.get(t.trust_score, 2) < 2:
            low_trust_vol += v
    total = sum(by_venue.values())
    if total <= 0 or not by_venue:
        return VenueDistribution(coin_id, len(by_venue), 0.0, "?", 0.0, 0.0)
    top_venue, top_vol = max(by_venue.items(), key=lambda kv: kv[1])
    return VenueDistribution(
        coin_id=coin_id,
        venue_count=len(by_venue),
        total_usd_volume=total,
        top_venue=top_venue,
        top_venue_share=top_vol / total,
        low_trust_share=low_trust_vol / total,
    )


class OnchainTokenMarket(BaseModel):
    """Token market read from the on-chain ``/tokens/{address}`` endpoint.

    The two load-bearing fields for the manipulation read are
    ``market_cap_usd`` and ``total_reserve_in_usd`` (on-chain DEX liquidity).
    ``fdv_usd`` is kept as a fallback denominator when CoinGecko cannot
    resolve a circulating-supply market cap (common for thin tokens) — a fake
    market cap quoted off FDV is exactly the case we want to catch.
    """

    model_config = ConfigDict(extra="ignore")

    address: str | None = None
    name: str | None = None
    symbol: str | None = None
    price_usd: float | None = None
    market_cap_usd: float | None = None
    fdv_usd: float | None = None
    total_reserve_in_usd: float | None = None

    @property
    def effective_market_cap_usd(self) -> float | None:
        """market_cap_usd when present, else fdv_usd (thin-token fallback)."""
        if self.market_cap_usd is not None and self.market_cap_usd > 0:
            return self.market_cap_usd
        if self.fdv_usd is not None and self.fdv_usd > 0:
            return self.fdv_usd
        return None


def _coerce_float(value: object) -> float | None:
    """CoinGecko on-chain returns USD figures as JSON strings — coerce safely."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class CoinGeckoClient:
    """Async client for CoinGecko market data + venue distribution."""

    def __init__(
        self,
        base_url: str = COINGECKO_BASE_URL,
        *,
        api_key: str | None = None,
        timeout: float = 12.0,
        client: httpx.AsyncClient | None = None,
        onchain_base_url: str = COINGECKO_ONCHAIN_BASE_URL,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._onchain_base_url = onchain_base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client

    async def _get(self, path: str, *, base: str | None = None) -> object:
        url = f"{base or self._base_url}{path}"
        headers = {"x-cg-pro-api-key": self._api_key} if self._api_key else {}
        if self._client is not None:
            resp = await self._client.get(url, headers=headers, timeout=self._timeout)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def markets(self, ids: list[str], *, vs_currency: str = "usd") -> list[CoinGeckoMarket]:
        joined = quote(",".join(ids), safe="")
        data = await self._get(
            f"/coins/markets?vs_currency={vs_currency}&ids={joined}&price_change_percentage=24h"
        )
        rows = data if isinstance(data, list) else []
        return [CoinGeckoMarket.model_validate(r) for r in rows]

    async def coin_tickers(self, coin_id: str) -> list[CoinGeckoTicker]:
        data = await self._get(f"/coins/{quote(coin_id, safe='')}/tickers?depth=false")
        rows = (data or {}).get("tickers", []) if isinstance(data, dict) else []
        return [CoinGeckoTicker.model_validate(r) for r in rows]

    async def venue_distribution(self, coin_id: str) -> VenueDistribution:
        """Where the token trades — venue count + top-venue + low-trust shares."""
        return _venue_distribution(coin_id, await self.coin_tickers(coin_id))

    async def onchain_token_market(
        self, address: str, *, network: str = "solana"
    ) -> OnchainTokenMarket | None:
        """Market cap + on-chain DEX liquidity for a raw contract address.

        Calls the on-chain (GeckoTerminal) ``/networks/{network}/tokens/{addr}``
        endpoint. Returns ``None`` when the token is unknown to the source (404)
        or the payload is malformed — callers fail-OPEN on ``None`` rather than
        fabricating a read.
        """
        path = f"/networks/{quote(network, safe='')}/tokens/{quote(address, safe='')}"
        try:
            data = await self._get(path, base=self._onchain_base_url)
        except httpx.HTTPStatusError as exc:
            # 404 = the token is unknown to the on-chain index (common for very
            # new / very thin tokens). Treat as "no read" (fail-OPEN) rather
            # than an error; other statuses propagate to the caller's guard.
            if exc.response.status_code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        attrs = ((data.get("data") or {}).get("attributes")) if isinstance(data, dict) else None
        if not isinstance(attrs, dict):
            return None
        return OnchainTokenMarket(
            address=attrs.get("address"),
            name=attrs.get("name"),
            symbol=attrs.get("symbol"),
            price_usd=_coerce_float(attrs.get("price_usd")),
            market_cap_usd=_coerce_float(attrs.get("market_cap_usd")),
            fdv_usd=_coerce_float(attrs.get("fdv_usd")),
            total_reserve_in_usd=_coerce_float(attrs.get("total_reserve_in_usd")),
        )


__all__ = [
    "COINGECKO_BASE_URL",
    "COINGECKO_ONCHAIN_BASE_URL",
    "CoinGeckoClient",
    "CoinGeckoMarket",
    "CoinGeckoTicker",
    "OnchainTokenMarket",
    "VenueDistribution",
]
