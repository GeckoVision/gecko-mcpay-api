"""OKXOnchainOSMarketClient contract tests.

Pattern C (recorded-fixture style): we never touch the real OKX OnchainOS
endpoint. The canned JSON below mirrors the live OnchainOS DEX Market/Token
shapes (confirmed against the founder's skill CLI command source +
cli-reference field tables) closely enough that a regression in parsing,
the {code,msg,data} envelope unwrap, the chain-name→chainIndex map, or the
fail-OPEN guards will trip these tests.

httpx.MockTransport routes each path to its canned response. All numeric
fields arrive as JSON *strings* (OnchainOS convention) — the coercion is
under test.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from gecko_core.sources.okx_onchainos_market import (
    OKX_ONCHAINOS_API_KEY_ENV,
    Holder,
    OKXOnchainOSMarketClient,
    top_holder_concentration,
)

# --- Canned OnchainOS payloads (live-shape) ------------------------------------

_PRICE_INFO = {
    "code": "0",
    "msg": "",
    "data": [
        {
            "chainIndex": "501",
            "tokenContractAddress": "So11111111111111111111111111111111111111112",
            "price": "152.34",
            "time": "1718500000000",
            "marketCap": "72500000000",
            "liquidity": "18250000",
            "circSupply": "476000000",
            "holders": "1284502",
            "tradeNum": "98213",
            "priceChange24H": "-2.15",
            "volume24H": "345000000",
        }
    ],
}

_HOLDERS = {
    "code": "0",
    "msg": "",
    "data": [
        {
            "holderWalletAddress": "Whale1111111111111111111111111111111111111",
            "holdAmount": "50000000",
            "holdPercent": "10.5",
            "totalPnlUsd": "1200000",
        },
        {
            "holderWalletAddress": "Whale2222222222222222222222222222222222222",
            "holdAmount": "25000000",
            "holdPercent": "5.25",
        },
        {
            "holderWalletAddress": "Whale3333333333333333333333333333333333333",
            "holdAmount": "10000000",
            "holdPercent": "2.1",
        },
    ],
}

_INDEX_PRICE = {
    "code": "0",
    "msg": "",
    "data": [
        {
            "chainIndex": "501",
            "tokenContractAddress": "So11111111111111111111111111111111111111112",
            "price": "151.98",
            "time": "1718500000000",
        }
    ],
}

_SOL_WSOL = "So11111111111111111111111111111111111111112"


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OKXOnchainOSMarketClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return OKXOnchainOSMarketClient(api_key="dev-key-xyz", client=http)


def _route(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/v6/dex/market/price-info":
        return httpx.Response(200, json=_PRICE_INFO)
    if path == "/api/v6/dex/market/token/holder":
        return httpx.Response(200, json=_HOLDERS)
    if path == "/api/v6/dex/index/current-price":
        return httpx.Response(200, json=_INDEX_PRICE)
    return httpx.Response(404, json={"code": "404", "msg": "not found"})


# --- token_market --------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_market_parses_mcap_liquidity_holders() -> None:
    client = _make_client(_route)
    tok = await client.token_market("solana", _SOL_WSOL)
    assert tok is not None
    assert tok.market_cap_usd == 72_500_000_000.0
    assert tok.liquidity_usd == 18_250_000.0
    assert tok.holders == 1_284_502
    assert tok.volume_24h_usd == 345_000_000.0
    assert tok.circulating_supply == 476_000_000.0
    assert tok.price_usd == 152.34
    assert tok.price_change_24h_pct == -2.15
    assert tok.chain_index == "501"


@pytest.mark.asyncio
async def test_token_market_sends_resolved_chain_index_in_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v6/dex/market/price-info":
            import json

            captured["body"] = json.loads(request.content)
            captured["okkey"] = request.headers.get("OK-ACCESS-KEY")
        return _route(request)

    client = _make_client(handler)
    await client.token_market("solana", _SOL_WSOL)
    assert captured["body"] == [{"chainIndex": "501", "tokenContractAddress": _SOL_WSOL}]
    # Developer-key auth header present (value not asserted beyond presence).
    assert captured["okkey"] == "dev-key-xyz"


# --- top_holders + concentration helper ---------------------------------------


@pytest.mark.asyncio
async def test_top_holders_parses_rows() -> None:
    client = _make_client(_route)
    holders = await client.top_holders("solana", _SOL_WSOL)
    assert len(holders) == 3
    assert holders[0].address == "Whale1111111111111111111111111111111111111"
    assert holders[0].hold_percent == 10.5
    assert holders[1].hold_percent == 5.25


def test_top_holder_concentration_computes_pct() -> None:
    holders = [
        Holder(address="a", hold_percent=10.5),
        Holder(address="b", hold_percent=5.25),
        Holder(address="c", hold_percent=2.1),
    ]
    conc = top_holder_concentration(holders)
    assert conc.holder_count == 3
    assert conc.top_holder_pct == 10.5
    assert conc.topN_pct == pytest.approx(17.85)


def test_top_holder_concentration_empty_is_zero() -> None:
    conc = top_holder_concentration([])
    assert conc.holder_count == 0
    assert conc.top_holder_pct == 0.0
    assert conc.topN_pct == 0.0


@pytest.mark.asyncio
async def test_holder_concentration_convenience() -> None:
    client = _make_client(_route)
    conc = await client.holder_concentration("solana", _SOL_WSOL)
    assert conc is not None
    assert conc.top_holder_pct == 10.5
    assert conc.topN_pct == pytest.approx(17.85)


@pytest.mark.asyncio
async def test_top_holders_clamps_limit() -> None:
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v6/dex/market/token/holder":
            captured["limit"] = request.url.params.get("limit")
        return _route(request)

    client = _make_client(handler)
    await client.top_holders("solana", _SOL_WSOL, limit=500)
    assert captured["limit"] == "100"


# --- index_price ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_price_parses() -> None:
    client = _make_client(_route)
    price = await client.index_price("solana", _SOL_WSOL)
    assert price == 151.98


# --- fail-OPEN behaviour -------------------------------------------------------


@pytest.mark.asyncio
async def test_token_market_fails_open_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "50011", "msg": "rate limit"})

    client = _make_client(handler)
    assert await client.token_market("solana", _SOL_WSOL) is None


@pytest.mark.asyncio
async def test_top_holders_fails_open_to_empty_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    client = _make_client(handler)
    assert await client.top_holders("solana", _SOL_WSOL) == []


@pytest.mark.asyncio
async def test_index_price_fails_open_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    client = _make_client(handler)
    assert await client.index_price("solana", _SOL_WSOL) is None


@pytest.mark.asyncio
async def test_nonzero_code_is_soft_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # HTTP 200 but a non-zero API code → fail-OPEN, not an exception.
        return httpx.Response(200, json={"code": "82000", "msg": "quota exceeded", "data": []})

    client = _make_client(handler)
    assert await client.token_market("solana", _SOL_WSOL) is None


# --- disabled (missing / __unset__ key) ---------------------------------------


@pytest.mark.asyncio
async def test_disabled_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OKX_ONCHAINOS_API_KEY_ENV, raising=False)
    # No explicit key, no env → disabled; methods never hit the network.
    client = OKXOnchainOSMarketClient()
    assert client.enabled is False
    assert await client.token_market("solana", _SOL_WSOL) is None
    assert await client.top_holders("solana", _SOL_WSOL) == []
    assert await client.index_price("solana", _SOL_WSOL) is None


@pytest.mark.asyncio
async def test_unset_sentinel_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    # SSM ships `__unset__` for not-yet-provisioned keys; treated as disabled.
    monkeypatch.setenv(OKX_ONCHAINOS_API_KEY_ENV, "__unset__")
    client = OKXOnchainOSMarketClient()
    assert client.enabled is False
    assert await client.index_price("solana", _SOL_WSOL) is None


@pytest.mark.asyncio
async def test_env_key_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OKX_ONCHAINOS_API_KEY_ENV, "real-dev-key")
    client = OKXOnchainOSMarketClient()
    assert client.enabled is True
