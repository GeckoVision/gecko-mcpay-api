"""Tests for pool discovery (Launch Firewall — mint → pools to watch).

Pure orientation/ranking logic + the GeckoTerminal per-pool parser (live-shape
payload via httpx.MockTransport). No real network.
"""

from __future__ import annotations

import httpx
from gecko_core.sources.coingecko import CoinGeckoClient, OnchainPool
from gecko_core.trade_agent.pool_discovery import (
    DiscoveredPool,
    discover_pools,
    orient_to_mint,
    rank_pools,
    select_index_pool,
    select_watch_set,
)

TARGET = "TARGETmint1111111111111111111111111111111111"
SOL = "So11111111111111111111111111111111111111112"

# --- live-shape GeckoTerminal /tokens/{addr}/pools payload --------------------

_POOLS_PAYLOAD = {
    "data": [
        {
            "type": "pool",
            "attributes": {
                "address": "DeepPoolAddr",
                "base_token_price_usd": "1.45",
                "quote_token_price_usd": "150.0",
                "reserve_in_usd": "400000.0",
                "pool_created_at": "2026-06-18T00:00:00Z",
                "transactions": {"m5": {"buys": 30, "sells": 28}},
                "volume_usd": {"m5": "12000.0"},
            },
            "relationships": {
                "base_token": {"data": {"id": f"solana_{TARGET}"}},
                "quote_token": {"data": {"id": f"solana_{SOL}"}},
                "dex": {"data": {"id": "raydium"}},
            },
        },
        {
            "type": "pool",
            "attributes": {
                "address": "BaitPoolAddr",
                "base_token_price_usd": "3.50",
                "quote_token_price_usd": "150.0",
                "reserve_in_usd": "200.0",
                "transactions": {"m5": {"buys": 0, "sells": 0}},
                "volume_usd": {"m5": "0"},
            },
            "relationships": {
                "base_token": {"data": {"id": f"solana_{TARGET}"}},
                "quote_token": {"data": {"id": f"solana_{SOL}"}},
                "dex": {"data": {"id": "orca"}},
            },
        },
    ]
}


def _client(payload: dict) -> CoinGeckoClient:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/pools" in req.url.path:
            return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})

    return CoinGeckoClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


# --- parser ------------------------------------------------------------------


async def test_onchain_token_pools_parses_live_shape():
    pools = await _client(_POOLS_PAYLOAD).onchain_token_pools(TARGET)
    assert len(pools) == 2
    deep = next(p for p in pools if p.pool_address == "DeepPoolAddr")
    assert deep.dex == "raydium"
    assert deep.base_mint == TARGET  # solana_ prefix stripped
    assert deep.quote_mint == SOL
    assert deep.reserve_in_usd == 400000.0
    assert deep.quote_token_price_usd == 150.0
    assert deep.buys_5m == 30


async def test_onchain_token_pools_404_is_empty():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    c = CoinGeckoClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await c.onchain_token_pools(TARGET) == []


async def test_onchain_token_pools_skips_malformed():
    payload = {
        "data": [{"type": "pool", "attributes": {}}, "garbage", {"attributes": {"address": "OK"}}]
    }
    pools = await _client(payload).onchain_token_pools(TARGET)
    assert [p.pool_address for p in pools] == ["OK"]


# --- orientation -------------------------------------------------------------


def test_orient_when_target_is_base():
    raw = OnchainPool(
        pool_address="P",
        dex="raydium",
        base_mint=TARGET,
        quote_mint=SOL,
        base_token_price_usd=1.45,
        quote_token_price_usd=150.0,
        reserve_in_usd=400000.0,
    )
    d = orient_to_mint(raw, TARGET)
    assert d.base_mint == TARGET
    assert d.base_price_usd == 1.45
    assert d.quote_usd_per_unit == 150.0  # SOL price


def test_orient_flips_when_target_is_quote():
    raw = OnchainPool(
        pool_address="P",
        dex="raydium",
        base_mint=SOL,
        quote_mint=TARGET,
        base_token_price_usd=150.0,
        quote_token_price_usd=1.45,
        reserve_in_usd=400000.0,
    )
    d = orient_to_mint(raw, TARGET)
    assert d.base_mint == TARGET  # flipped so our mint is base
    assert d.base_price_usd == 1.45
    assert d.quote_usd_per_unit == 150.0


# --- ranking / selection -----------------------------------------------------


def _dp(addr: str, tvl: float) -> DiscoveredPool:
    return DiscoveredPool(pool_addr=addr, base_mint=TARGET, quote_mint=SOL, tvl_usd=tvl)


def test_rank_deepest_first():
    ranked = rank_pools([_dp("a", 200.0), _dp("b", 400000.0), _dp("c", 5000.0)])
    assert [p.pool_addr for p in ranked] == ["b", "c", "a"]


def test_select_index_pool_requires_min_reserve():
    # The thin bait pool must NOT be chosen as the index even if it's the only deep-ish one.
    idx = select_index_pool([_dp("bait", 200.0), _dp("deep", 400000.0)])
    assert idx is not None and idx.pool_addr == "deep"


def test_select_index_pool_falls_back_to_deepest_when_all_thin():
    idx = select_index_pool([_dp("a", 50.0), _dp("b", 300.0)])
    assert idx is not None and idx.pool_addr == "b"


def test_select_index_pool_none_when_empty():
    assert select_index_pool([]) is None


def test_select_watch_set_caps_and_includes_index():
    pools = [_dp(str(i), float(i) * 1000) for i in range(10)]
    watch = select_watch_set(pools, max_watch=3)
    assert len(watch) == 3
    assert watch[0].pool_addr == "9"  # deepest included


# --- end to end --------------------------------------------------------------


async def test_discover_pools_orients_and_ranks():
    pools = await discover_pools(TARGET, _client(_POOLS_PAYLOAD))
    assert [p.pool_addr for p in pools] == ["DeepPoolAddr", "BaitPoolAddr"]  # deepest first
    assert all(p.base_mint == TARGET for p in pools)
    idx = select_index_pool(pools)
    assert idx is not None and idx.pool_addr == "DeepPoolAddr"


async def test_discover_pools_fail_open_on_error():
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    c = CoinGeckoClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await discover_pools(TARGET, c) == []
