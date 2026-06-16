"""Phase 3.3 (context-engineering) — Pegana depeg-risk wired into safety read.

The Pegana peg-risk oracle (:mod:`gecko_core.sources.pegana`) was BUILT but DARK
— zero references in orchestration. This wires it into ``evaluate_contract_safety``
so peg-state becomes a first-class decision-integrity signal on the SafetyBlock
and reaches the voices via the synthetic onchain_live chunk.

Tests are direct unit tests against ``evaluate_contract_safety`` with an injected
fake peg client, plus the chunk-text rendering. No network, no LLM:
  - a depegged read => depeg fields + a ``depeg_risk`` flag + chunk text mentions
    the peg;
  - a healthy/PEGGED read => fields populated, NO ``depeg_risk`` flag, no crash;
  - a peg client that raises => fail-OPEN (block still returned, safety intact).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from gecko_core.orchestration.trade_panel.safety_check import (
    build_onchain_safety_chunk,
    evaluate_contract_safety,
)
from gecko_core.sources.coingecko import OnchainTokenMarket
from gecko_core.sources.pegana import DepegRisk
from gecko_core.sources.quicknode import QuickNodeClient

_FIX = Path(__file__).parent / "fixtures"

# A valid base58 32-byte SPL mint so is_spl_mint passes; the mocked QuickNode
# transport returns the fixture content regardless of the address string.
_LST_MINT = "BRcaUSDC11111111111111111111111111111111111"


def _load(name: str) -> Any:
    return json.loads((_FIX / name).read_text())


def _qn_handler(request: httpx.Request) -> httpx.Response:
    """Clean (renounced) mint so the test isolates the depeg signal."""
    body = json.loads(request.content)
    method = body["method"]
    if method == "getAccountInfo":
        return httpx.Response(200, json=_load("quicknode_mint_clean.json"))
    if method == "getTokenLargestAccounts":
        return httpx.Response(200, json=_load("quicknode_largest_clean.json"))
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})


def _safety_client() -> QuickNodeClient:
    transport = httpx.MockTransport(_qn_handler)
    return QuickNodeClient("https://rpc.example/qn", client=httpx.AsyncClient(transport=transport))


class _NoMarketClient:
    """Offline market client — keeps depeg tests off the network."""

    async def onchain_token_market(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _FakePegClient:
    """Fake Pegana client returning a canned DepegRisk per mint."""

    def __init__(self, risk: DepegRisk) -> None:
        self._risk = risk
        self.calls: list[str] = []

    async def depeg_risk_by_mint(
        self, mint: str, *, discount_threshold: float | None = None
    ) -> DepegRisk:
        self.calls.append(mint)
        return self._risk


class _RaisingPegClient:
    """Fake Pegana client that raises — proves fail-OPEN."""

    async def depeg_risk_by_mint(
        self, mint: str, *, discount_threshold: float | None = None
    ) -> DepegRisk:
        raise httpx.ConnectError("pegana down")


class _NotFoundPegClient:
    """Non-peg token: Pegana 404s on by-mint => the call raises => fail-OPEN."""

    async def depeg_risk_by_mint(
        self, mint: str, *, discount_threshold: float | None = None
    ) -> DepegRisk:
        raise httpx.HTTPStatusError(
            "404", request=httpx.Request("GET", "https://x"), response=httpx.Response(404)
        )


def _depegged() -> DepegRisk:
    return DepegRisk(
        asset="exampleLST",
        state="DEPEGGED",
        is_pegged=False,
        discount_abs=0.073,
        stale=False,
        risk_off=True,
        as_of=datetime(2026, 6, 15, tzinfo=UTC),
    )


def _healthy() -> DepegRisk:
    return DepegRisk(
        asset="exampleLST",
        state="PEGGED",
        is_pegged=True,
        discount_abs=0.001,
        stale=False,
        risk_off=False,
        as_of=datetime(2026, 6, 15, tzinfo=UTC),
    )


def _evaluate(peg_client: Any) -> Any:
    return asyncio.run(
        evaluate_contract_safety(
            "exampleLST",
            mint=_LST_MINT,
            client=_safety_client(),
            market_client=_NoMarketClient(),
            peg_client=peg_client,
        )
    )


# --- depegged read => fields + flag + chunk text ---------------------------


def test_depegged_read_surfaces_fields_and_flag() -> None:
    safety = _evaluate(_FakePegClient(_depegged()))

    assert safety.checked is True
    assert safety.depeg_risk == 0.073
    assert safety.peg_status == "DEPEGGED"
    assert "depeg_risk" in safety.rug_flags


def test_depegged_read_reaches_onchain_chunk_text() -> None:
    safety = _evaluate(_FakePegClient(_depegged()))
    chunk = build_onchain_safety_chunk(safety, protocol="exampleLST", mint=_LST_MINT)
    assert chunk is not None
    text = chunk["text"]
    assert "peg" in text.lower()
    assert "DEPEGGED" in text


# --- healthy / PEGGED read => no flag, no crash ----------------------------


def test_healthy_peg_no_flag() -> None:
    safety = _evaluate(_FakePegClient(_healthy()))

    assert safety.checked is True
    assert safety.peg_status == "PEGGED"
    assert "depeg_risk" not in safety.rug_flags


# --- peg client raises => fail-OPEN ----------------------------------------


def test_peg_client_error_fails_open() -> None:
    """A Pegana failure must NOT break the safety block — depeg fields just None."""
    safety = _evaluate(_RaisingPegClient())

    assert safety.checked is True  # chain read preserved
    assert safety.depeg_risk is None
    assert safety.peg_status is None
    assert "depeg_risk" not in safety.rug_flags


def test_non_peg_token_404_fails_open() -> None:
    """A non-peg token (Pegana 404) degrades silently — no flag, block intact."""
    safety = _evaluate(_NotFoundPegClient())

    assert safety.checked is True
    assert safety.depeg_risk is None
    assert safety.peg_status is None
    assert "depeg_risk" not in safety.rug_flags


# --- no peg_client at all is fine (default-None path under test) ------------


def test_default_no_injection_with_market() -> None:
    """When no peg client is injected and the default would build the real one,
    a market read still works — but here we inject a healthy peg so we stay off
    the network. Guards the additive shape against the manipulation path."""

    async def _market() -> OnchainTokenMarket:
        return OnchainTokenMarket(
            market_cap_usd=1_000_000.0,
            fdv_usd=1_000_000.0,
            total_reserve_in_usd=900_000.0,
        )

    class _MarketClient:
        async def onchain_token_market(self, *_a: Any, **_k: Any) -> OnchainTokenMarket:
            return await _market()

    safety = asyncio.run(
        evaluate_contract_safety(
            "exampleLST",
            mint=_LST_MINT,
            client=_safety_client(),
            market_client=_MarketClient(),
            peg_client=_FakePegClient(_healthy()),
        )
    )
    assert safety.checked is True
    assert safety.peg_status == "PEGGED"
    assert safety.market_cap_usd == 1_000_000.0
