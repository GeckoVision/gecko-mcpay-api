"""Pegana peg-risk oracle client.

Wire reference: https://api.pegana.xyz/openapi.json (Pegana API v0.1.0).
Pegana is a peg-risk oracle for Solana — real-time peg state across LSTs and
stablecoins. We consume the **public, no-auth** read endpoints only:

    GET /v1/assets                      -> whole universe + current state
    GET /v1/assets/{symbol}/state       -> single peg state by symbol
    GET /v1/assets/by-mint/{mint}/state -> single peg state by SPL mint
    GET /v1/stats                       -> universe summary

The user-scoped ``/v1/me/*`` / ``/v1/auth/*`` / webhook endpoints require a
``telegram_jwt`` and are out of scope — they are subscription features, not
data ingest.

This module is a structured **data-provider** source (peg-risk feature), not a
RAG/corpus source: do NOT register it with the embedding dispatcher. It depends
only on ``httpx`` + ``pydantic`` so it can feed the pre-trade safety gate and
the vault safety-monitor without dragging in the data layer. See
``docs/superpowers/specs/2026-06-10-pegana-peg-risk-ingest.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

PEGANA_BASE_URL = "https://api.pegana.xyz"

# Pegana's `state` is authoritative: it already applies *class-aware* thresholds
# (an LST's normal unstaking-delay discount is wider than a fiat stable's), so a
# PEGGED asset is healthy even at a multi-percent raw discount. The gate trusts
# `state` + `stale` by default and does NOT impose a naive global discount cut.
# A caller may pass an extra `discount_threshold` for a stricter, opt-in cut.
PEGGED_STATE = "PEGGED"

# Suggested value for callers that opt into the extra discount cut (off by default).
SUGGESTED_DISCOUNT_THRESHOLD = 0.005


class PeganaAsset(BaseModel):
    """One tracked asset from ``GET /v1/assets``.

    Extra fields (``series_24h``, ``sol_per_lst``, ``thresholds``,
    ``worst_abs_24h``, ``jitter_bps_24h``) are accepted but ignored — we keep
    the model to the fields the gate reads.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    symbol: str
    name: str | None = None
    mint: str
    asset_class: str | None = Field(default=None, alias="class")
    peg_target: str | None = None
    decimals: int | None = None
    state: str
    discount: float | None = None
    intrinsic_usd: Decimal | None = None
    market_usd: Decimal | None = None
    confidence: str | None = None  # categorical: "high" | "medium" | "low"
    updated_at: datetime | None = None


class PeganaPegState(BaseModel):
    """Current peg state from ``GET /v1/assets/{symbol}/state``."""

    model_config = ConfigDict(extra="ignore")

    asset: str
    state: str
    since: datetime | None = None
    discount: float | None = None
    intrinsic_usd: Decimal | None = None
    market_usd: Decimal | None = None
    updated_at: datetime | None = None
    stale: bool = False


class PeganaStats(BaseModel):
    """Universe summary from ``GET /v1/stats``."""

    model_config = ConfigDict(extra="ignore")

    assets_tracked: int
    assets_in_drift: int
    alerts_24h: int = 0
    by_state: dict[str, int] = Field(default_factory=dict)
    delivery_health: dict[str, object] = Field(default_factory=dict)


@dataclass(frozen=True)
class DepegRisk:
    """Normalized peg-risk read for the pre-trade safety gate.

    ``risk_off`` is the gate signal: True if the asset is not cleanly PEGGED,
    is stale, or its discount exceeds the threshold.
    """

    asset: str
    state: str
    is_pegged: bool
    discount_abs: float
    stale: bool
    risk_off: bool
    as_of: datetime | None


def _risk_from_state(
    state: PeganaPegState, *, discount_threshold: float | None = None
) -> DepegRisk:
    discount_abs = abs(state.discount) if state.discount is not None else 0.0
    is_pegged = state.state == PEGGED_STATE
    risk_off = (not is_pegged) or state.stale
    if discount_threshold is not None:
        risk_off = risk_off or discount_abs > discount_threshold
    return DepegRisk(
        asset=state.asset,
        state=state.state,
        is_pegged=is_pegged,
        discount_abs=discount_abs,
        stale=state.stale,
        risk_off=risk_off,
        as_of=state.updated_at,
    )


class PeganaClient:
    """Async client for Pegana's public peg-risk read endpoints.

    Pass an ``httpx.AsyncClient`` to reuse a pooled connection (and to inject a
    ``MockTransport`` in tests); otherwise one is created per request.
    """

    def __init__(
        self,
        base_url: str = PEGANA_BASE_URL,
        *,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client

    async def _get(self, path: str) -> object:
        url = f"{self._base_url}{path}"
        if self._client is not None:
            resp = await self._client.get(url, timeout=self._timeout)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def list_assets(self) -> list[PeganaAsset]:
        data = await self._get("/v1/assets")
        rows = data if isinstance(data, list) else []
        return [PeganaAsset.model_validate(row) for row in rows]

    async def asset_state(self, symbol: str) -> PeganaPegState:
        data = await self._get(f"/v1/assets/{quote(symbol, safe='')}/state")
        return PeganaPegState.model_validate(data)

    async def asset_state_by_mint(self, mint: str) -> PeganaPegState:
        data = await self._get(f"/v1/assets/by-mint/{quote(mint, safe='')}/state")
        return PeganaPegState.model_validate(data)

    async def stats(self) -> PeganaStats:
        data = await self._get("/v1/stats")
        return PeganaStats.model_validate(data)

    async def depeg_risk(
        self,
        symbol: str,
        *,
        discount_threshold: float | None = None,
    ) -> DepegRisk:
        """Risk-off read for ``symbol``. Use :meth:`depeg_risk_by_mint` when
        you only have the SPL mint (the gate's case at trade time)."""
        state = await self.asset_state(symbol)
        return _risk_from_state(state, discount_threshold=discount_threshold)

    async def depeg_risk_by_mint(
        self,
        mint: str,
        *,
        discount_threshold: float | None = None,
    ) -> DepegRisk:
        state = await self.asset_state_by_mint(mint)
        return _risk_from_state(state, discount_threshold=discount_threshold)


__all__ = [
    "PEGANA_BASE_URL",
    "SUGGESTED_DISCOUNT_THRESHOLD",
    "DepegRisk",
    "PeganaAsset",
    "PeganaClient",
    "PeganaPegState",
    "PeganaStats",
]
