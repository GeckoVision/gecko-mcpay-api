"""Recorded-fixture contract tests for the CoinGecko client (Pattern C).

Fixtures are real captures from api.coingecko.com (2026-06-10):
  - markets: solana + jito-governance-token
  - tickers: JTO across its venues (the "where trading happens" signal)

No network in CI — served by an httpx.MockTransport.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from gecko_core.sources.coingecko import CoinGeckoClient

_FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> object:
    return json.loads((_FIX / name).read_text())


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p.endswith("/coins/markets"):
        return httpx.Response(200, json=_load("coingecko_markets.json"))
    if p.endswith("/tickers"):
        return httpx.Response(200, json=_load("coingecko_tickers.json"))
    return httpx.Response(404)


def _client() -> CoinGeckoClient:
    return CoinGeckoClient(client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))


def test_markets_parse() -> None:
    markets = asyncio.run(_client().markets(["solana", "jito-governance-token"]))
    by_id = {m.id: m for m in markets}
    sol = by_id["solana"]
    assert sol.symbol == "sol"
    assert sol.current_price and sol.current_price > 0
    assert sol.total_volume and sol.total_volume > 0


def test_tickers_parse_nested_fields() -> None:
    tickers = asyncio.run(_client().coin_tickers("jito-governance-token"))
    assert len(tickers) == 100
    # nested market.name + converted_volume.usd surface via the properties
    assert all(isinstance(t.venue, str) for t in tickers)
    assert any(t.usd_volume > 0 for t in tickers)


def test_venue_distribution_is_a_concentration_read() -> None:
    """JTO trades broadly (many venues, no single venue dominates) → low risk."""
    dist = asyncio.run(_client().venue_distribution("jito-governance-token"))
    assert dist.venue_count == 75
    assert dist.total_usd_volume > 0
    assert dist.top_venue  # a named venue
    # Broadly distributed: the top venue is well under half of all volume.
    assert 0.0 < dist.top_venue_share < 0.5
    assert 0.0 <= dist.low_trust_share <= 1.0
