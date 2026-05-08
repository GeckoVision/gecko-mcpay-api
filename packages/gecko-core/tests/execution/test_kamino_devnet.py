import json
from decimal import Decimal
from pathlib import Path

import pytest
from gecko_core.execution.kamino_devnet import (
    KaminoIntent,
    build_simulate_intent,
    fetch_unsigned_deposit_tx,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_simulate_intent_never_signs():
    intent = build_simulate_intent(
        wallet="HzXDevnetTraderPubkey",
        market="So1anaKmK1ndDeVnetMrkt",
        reserve="USDCRsrvDeVnet",
        amount_usdc=Decimal("1.50"),
    )
    assert intent.mode == "simulate"
    assert intent.wallet == "HzXDevnetTraderPubkey"
    assert intent.amount_usdc == Decimal("1.50")
    assert intent.signed_tx_b64 is None
    assert intent.signature is None


def test_simulate_intent_renders_dict():
    intent = build_simulate_intent(
        wallet="W",
        market="M",
        reserve="R",
        amount_usdc=Decimal("2"),
    )
    d = intent.to_dict()
    assert d == {
        "mode": "simulate",
        "venue": "kamino",
        "action": "deposit",
        "wallet": "W",
        "market": "M",
        "reserve": "R",
        "amount_usdc": "2",
    }


@pytest.mark.asyncio
async def test_fetch_unsigned_deposit_tx_replays_fixture(monkeypatch):
    fixture = json.loads((FIXTURES / "ktx_deposit_response.json").read_text())

    class _Resp:
        status_code = 200

        def json(self):
            return fixture

        def raise_for_status(self):
            pass

    class _AsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **kw):
            return _Resp()

    import gecko_core.execution.kamino_devnet as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", _AsyncClient)

    tx_b64 = await fetch_unsigned_deposit_tx(
        ktx_url="https://api.kamino.finance",
        wallet="W",
        market="M",
        reserve="R",
        amount_usdc=Decimal("1.0"),
    )
    assert tx_b64 == fixture["transaction"]


def test_kamino_intent_is_frozen():
    intent = KaminoIntent(
        mode="simulate",
        wallet="W",
        market="M",
        reserve="R",
        amount_usdc=Decimal("1"),
    )
    with pytest.raises(Exception):
        intent.wallet = "X"  # type: ignore[misc]
