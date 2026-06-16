"""OKX OnchainOS Market source client.

Wire reference: the OKX OnchainOS DEX Market/Token REST API at
``https://web3.okx.com``. Endpoints (confirmed against the founder's OnchainOS
skill CLI, ``okx-files/onchainos-skills/cli/src/commands/{token,market}.rs``):

- POST ``/api/v6/dex/market/price-info`` — body ``[{chainIndex, tokenContractAddress}]``;
  returns price + ``marketCap`` + ``liquidity`` + ``circSupply`` + ``holders`` +
  ``volume24H`` (and multi-timeframe price/volume fields we ignore).
- GET  ``/api/v6/dex/market/token/holder`` — ``chainIndex`` + ``tokenContractAddress``
  + ``limit`` (max 100); returns the top-N holder rows with ``holdPercent``.
- POST ``/api/v6/dex/index/current-price`` — body ``[{chainIndex, tokenContractAddress}]``;
  returns the composite, manipulation-resistant **index price** (aggregated
  across CEX + DEX + oracle sources).

Why this matters for the safety / Information-MEV read:
- ``holders`` count + the top-20 holder ``holdPercent`` give holder concentration
  WITHOUT a separate Helius / QuickNode holders call.
- The **index price** resists single-venue distortion — a token whose live DEX
  price diverges sharply from the OKX index is a manipulation signal.

Auth: header ``OK-ACCESS-KEY: <developer key>`` (OnchainOS developer-key model),
read from ``OKX_ONCHAINOS_API_KEY``. Without it the client is *disabled* and
every method fails-OPEN to ``None`` / ``[]`` so the safety read degrades to its
other sources rather than erroring.

Response envelope is the OKX standard ``{"code": "0", "msg": "", "data": [...]}``;
``data`` is an array for all three endpoints (we take the first element for the
single-token reads). ``code != "0"`` is treated as a soft failure (fail-OPEN).

Structured market-data source — httpx + pydantic only; not a RAG/corpus source.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

OKX_ONCHAINOS_BASE_URL = "https://web3.okx.com"

# Env var holding the OnchainOS developer key. Distinct from ``OKX_API_KEY``
# (the Bearer-token news adapter) so the two surfaces stay independently
# provisionable. SSM ships ``__unset__`` for not-yet-provisioned keys.
OKX_ONCHAINOS_API_KEY_ENV = "OKX_ONCHAINOS_API_KEY"

# OnchainOS chain *names* → numeric ``chainIndex`` (from the skill's chains.rs).
# Callers may also pass a raw numeric chainIndex string, which is passed through.
_CHAIN_INDEX = {
    "ethereum": "1",
    "eth": "1",
    "solana": "501",
    "sol": "501",
    "bsc": "56",
    "bnb": "56",
    "base": "8453",
    "polygon": "137",
    "arbitrum": "42161",
    "optimism": "10",
    "avalanche": "43114",
}


def _env_clean(name: str) -> str:
    """Env value, stripped, treating the SSM ``__unset__`` sentinel as empty.

    House convention (mirrors ``safety_check._env_clean`` /
    ``news_factory._env_clean``): infra pushes a ``__unset__`` sentinel for
    not-yet-provisioned keys so ECS resolves ``secrets:`` at boot without error;
    runtime code treats the sentinel as truly unset.
    """
    value = os.environ.get(name, "").strip()
    return "" if value == "__unset__" else value


def _resolve_chain_index(chain: str) -> str:
    """Map a chain name to its numeric ``chainIndex``; pass numeric strings through."""
    c = (chain or "").strip().lower()
    if c.isdigit():
        return c
    return _CHAIN_INDEX.get(c, c)


def _coerce_float(value: object) -> float | None:
    """OnchainOS returns all numeric figures as JSON strings — coerce safely."""
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int | None:
    f = _coerce_float(value)
    return int(f) if f is not None else None


def _coerce_str(value: object) -> str | None:
    """Return a stripped str for str-typed fields; ``None`` for anything else."""
    return value.strip() if isinstance(value, str) and value.strip() else None


class OnchainOSToken(BaseModel):
    """Token market read from ``/api/v6/dex/market/price-info``.

    The load-bearing fields for the safety read are ``market_cap_usd`` (fake
    market-cap detection), ``liquidity_usd`` (thin-liquidity detection),
    ``holders`` (concentration denominator), and ``volume_24h_usd`` (wash /
    dead-token detection).
    """

    model_config = ConfigDict(extra="ignore")

    chain_index: str | None = None
    token_contract_address: str | None = None
    price_usd: float | None = None
    market_cap_usd: float | None = None
    liquidity_usd: float | None = None
    volume_24h_usd: float | None = None
    holders: int | None = None
    circulating_supply: float | None = None
    price_change_24h_pct: float | None = None


class Holder(BaseModel):
    """One row of ``/api/v6/dex/market/token/holder``.

    ``hold_percent`` is the fraction-of-total-supply held, already computed by
    OnchainOS — returned as a percentage string (e.g. ``"3.5"`` = 3.5%).
    """

    model_config = ConfigDict(extra="ignore")

    address: str | None = None
    hold_amount: float | None = None
    hold_percent: float | None = None


@dataclass(frozen=True)
class HolderConcentration:
    """Concentration read derived from the top-N holders.

    ``top_holder_pct`` near a large value (one whale owns a big slice) or a high
    ``topN_pct`` (the top N together dominate) is a risk-off signal for the gate.
    """

    holder_count: int
    top_holder_pct: float
    topN_pct: float


def top_holder_concentration(holders: list[Holder]) -> HolderConcentration:
    """Compute single-holder + aggregate-top-N concentration from holder rows.

    Percentages are returned in the same unit OnchainOS uses (whole-number
    percent, e.g. ``12.5`` == 12.5%). Empty input yields all-zero.
    """
    pcts = [h.hold_percent for h in holders if h.hold_percent is not None]
    if not pcts:
        return HolderConcentration(holder_count=len(holders), top_holder_pct=0.0, topN_pct=0.0)
    return HolderConcentration(
        holder_count=len(holders),
        top_holder_pct=max(pcts),
        topN_pct=sum(pcts),
    )


class OKXOnchainOSMarketClient:
    """Async client for OKX OnchainOS Market data (token metrics, holders, index).

    All methods fail-OPEN: a missing/`__unset__` developer key, an HTTP error,
    a non-zero API ``code``, or a malformed payload returns ``None`` / ``[]``
    rather than raising, so the safety read degrades gracefully.
    """

    def __init__(
        self,
        base_url: str = OKX_ONCHAINOS_BASE_URL,
        *,
        api_key: str | None = None,
        timeout: float = 12.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # Explicit key wins; otherwise read env with the `__unset__` sentinel guard.
        self._api_key = (api_key or "").strip() or _env_clean(OKX_ONCHAINOS_API_KEY_ENV)
        self._timeout = timeout
        self._client = client

    @property
    def enabled(self) -> bool:
        """True only when a real developer key is present (not unset/sentinel)."""
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        # OnchainOS developer-key auth: a single OK-ACCESS-KEY header. Never log it.
        return {"OK-ACCESS-KEY": self._api_key, "Content-Type": "application/json"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: list[dict[str, str]] | None = None,
        params: dict[str, str] | None = None,
    ) -> object | None:
        """Issue a request and unwrap the OKX ``{code,msg,data}`` envelope.

        Returns the ``data`` payload (usually a list) or ``None`` on any failure.
        Errors are redacted — the developer key is never included in log output.
        """
        if not self.enabled:
            return None
        url = f"{self._base_url}{path}"
        headers = self._headers()
        try:
            if self._client is not None:
                resp = await self._client.request(
                    method,
                    url,
                    headers=headers,
                    timeout=self._timeout,
                    json=json_body,
                    params=params,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.request(
                        method, url, headers=headers, json=json_body, params=params
                    )
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as exc:
            # Redact: log only the path + exception type, never headers/key/url-with-creds.
            logger.warning("OnchainOS %s %s failed: %s", method, path, type(exc).__name__)
            return None
        except ValueError:  # non-JSON body
            logger.warning("OnchainOS %s %s returned non-JSON body", method, path)
            return None
        # Bare-array endpoints (defensive) — pass through.
        if isinstance(body, list):
            return body
        if not isinstance(body, dict):
            return None
        code = body.get("code")
        if str(code) != "0":
            logger.warning("OnchainOS %s %s soft-failed: code=%s", method, path, code)
            return None
        return body.get("data")

    @staticmethod
    def _first(data: object) -> dict[str, object] | None:
        """First dict element of a ``data`` array (single-token endpoints)."""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return None

    async def token_market(self, chain: str, address: str) -> OnchainOSToken | None:
        """mcap, liquidity, 24h volume, holders count, circulating supply.

        POST ``/api/v6/dex/market/price-info``. Fail-OPEN to ``None``.
        """
        chain_index = _resolve_chain_index(chain)
        body = [{"chainIndex": chain_index, "tokenContractAddress": address}]
        data = await self._request("POST", "/api/v6/dex/market/price-info", json_body=body)
        row = self._first(data)
        if row is None:
            return None
        return OnchainOSToken(
            chain_index=_coerce_str(row.get("chainIndex")) or chain_index,
            token_contract_address=_coerce_str(row.get("tokenContractAddress")) or address,
            price_usd=_coerce_float(row.get("price")),
            market_cap_usd=_coerce_float(row.get("marketCap")),
            liquidity_usd=_coerce_float(row.get("liquidity")),
            volume_24h_usd=_coerce_float(row.get("volume24H")),
            holders=_coerce_int(row.get("holders")),
            circulating_supply=_coerce_float(row.get("circSupply")),
            price_change_24h_pct=_coerce_float(row.get("priceChange24H")),
        )

    async def top_holders(self, chain: str, address: str, *, limit: int = 20) -> list[Holder]:
        """Top holders (default top-20) for concentration analysis.

        GET ``/api/v6/dex/market/token/holder``. Fail-OPEN to ``[]``.
        ``limit`` is clamped to OnchainOS's 1..100 range.
        """
        chain_index = _resolve_chain_index(chain)
        limit = max(1, min(int(limit), 100))
        params = {
            "chainIndex": chain_index,
            "tokenContractAddress": address,
            "limit": str(limit),
        }
        data = await self._request("GET", "/api/v6/dex/market/token/holder", params=params)
        rows = data if isinstance(data, list) else []
        out: list[Holder] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append(
                Holder(
                    address=_coerce_str(r.get("holderWalletAddress")),
                    hold_amount=_coerce_float(r.get("holdAmount")),
                    hold_percent=_coerce_float(r.get("holdPercent")),
                )
            )
        return out

    async def holder_concentration(
        self, chain: str, address: str, *, limit: int = 20
    ) -> HolderConcentration | None:
        """Convenience: fetch top holders + compute concentration in one call.

        Returns ``None`` when no holder rows are available (fail-OPEN).
        """
        holders = await self.top_holders(chain, address, limit=limit)
        if not holders:
            return None
        return top_holder_concentration(holders)

    async def index_price(self, chain: str, address: str) -> float | None:
        """Manipulation-resistant composite index price (CEX + DEX + oracle).

        POST ``/api/v6/dex/index/current-price``. Fail-OPEN to ``None``.
        """
        chain_index = _resolve_chain_index(chain)
        body = [{"chainIndex": chain_index, "tokenContractAddress": address}]
        data = await self._request("POST", "/api/v6/dex/index/current-price", json_body=body)
        row = self._first(data)
        if row is None:
            return None
        return _coerce_float(row.get("price"))


__all__ = [
    "OKX_ONCHAINOS_API_KEY_ENV",
    "OKX_ONCHAINOS_BASE_URL",
    "Holder",
    "HolderConcentration",
    "OKXOnchainOSMarketClient",
    "OnchainOSToken",
    "top_holder_concentration",
]
