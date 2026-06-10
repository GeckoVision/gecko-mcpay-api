"""Recorded-fixture contract tests for the QuickNode Solana-RPC client.

Fixtures are real captures (2026-06-10, mainnet getAccountInfo jsonParsed):
  - USDC: mint + freeze authority PRESENT (not renounced)
  - JTO : both authorities None (renounced) → safer

No network in CI — an httpx.MockTransport routes by JSON-RPC method + mint.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from gecko_core.sources.quicknode import QuickNodeClient

_FIX = Path(__file__).parent / "fixtures"
_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_JTO = "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL"


def _load(name: str) -> object:
    return json.loads((_FIX / name).read_text())


def _handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    method, params = body["method"], body.get("params", [])
    if method == "getAccountInfo":
        mint = params[0]
        if mint == _USDC:
            return httpx.Response(200, json=_load("quicknode_mint_usdc.json"))
        if mint == _JTO:
            return httpx.Response(200, json=_load("quicknode_mint_jto.json"))
    if method == "getTokenLargestAccounts":
        return httpx.Response(200, json=_load("quicknode_largest_jto.json"))
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})


def _client() -> QuickNodeClient:
    transport = httpx.MockTransport(_handler)
    return QuickNodeClient("https://rpc.example/qn", client=httpx.AsyncClient(transport=transport))


def test_mint_info_parses() -> None:
    info = asyncio.run(_client().get_mint_info(_USDC))
    assert info.decimals == 6
    assert info.mint_authority is not None  # USDC keeps a mint authority


def test_authority_present_is_rug_risk() -> None:
    """USDC: mint + freeze authority present → rug_risk True (raw signal)."""
    safety = asyncio.run(_client().token_safety(_USDC))
    assert safety.mint_renounced is False
    assert safety.freeze_renounced is False
    assert safety.rug_risk is True


def test_renounced_is_not_rug_risk() -> None:
    """JTO: both authorities renounced (None) → rug_risk False."""
    safety = asyncio.run(_client().token_safety(_JTO))
    assert safety.mint_renounced is True
    assert safety.freeze_renounced is True
    assert safety.rug_risk is False


def test_largest_accounts_parses() -> None:
    accts = asyncio.run(_client().token_largest_accounts(_JTO))
    assert isinstance(accts, list)
    assert len(accts) > 0
