"""POST /safety — the fast deterministic safety / Information-MEV gate.

Sub-second pre-trade veto tier (no LLM panel). Tests pin the one-glance `gate`
truth table + the endpoint shape + the fail-OPEN contract (never 5xx).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

os.environ["X402_MODE"] = "stub"
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")
os.environ.setdefault("TAVILY_API_KEY", "test-stub-key")

from gecko_core.orchestration.trade_panel.models import InformationMEVBlock, SafetyBlock

_BRCA = "BCAxFqs3VJGTmVsBsyYxWL2zZG6xR1kAynCKkhBKEkxx"


@pytest.fixture
def client() -> Iterator[TestClient]:
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)
    from gecko_api import main as api_main

    with TestClient(api_main.app) as c:
        yield c


def test_gate_truth_table() -> None:
    from gecko_api.main import _safety_gate

    assert _safety_gate(SafetyBlock.unavailable(reason="x")) == "unknown"
    assert _safety_gate(SafetyBlock(checked=True, honeypot=True)) == "block"
    assert _safety_gate(SafetyBlock(checked=True, rug_flags=["fake_market_cap"])) == "block"
    assert _safety_gate(SafetyBlock(checked=True, rug_flags=["depeg_risk"])) == "block"
    imev_m = InformationMEVBlock(score=0.95, label="manipulated", reasons=["x"])
    assert _safety_gate(SafetyBlock(checked=True, information_mev=imev_m)) == "block"
    imev_e = InformationMEVBlock(score=0.4, label="elevated", reasons=["x"])
    assert _safety_gate(SafetyBlock(checked=True, information_mev=imev_e)) == "caution"
    assert (
        _safety_gate(SafetyBlock(checked=True, rug_flags=["thin_liquidity_vs_mcap"])) == "caution"
    )
    clean = InformationMEVBlock(score=0.0, label="clean", reasons=["clean"])
    assert _safety_gate(SafetyBlock(checked=True, information_mev=clean)) == "ok"


def test_endpoint_returns_block_for_manipulated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gecko_core.orchestration.trade_panel.safety_check as sc

    imev = InformationMEVBlock(score=0.95, label="manipulated", reasons=["fake mcap"])
    block = SafetyBlock(
        checked=True,
        honeypot=False,
        market_cap_usd=26_000_000.0,
        liquidity_usd=160_000.0,
        liquidity_to_mcap_pct=0.6,
        rug_flags=["thin_liquidity_vs_mcap", "fake_market_cap"],
        information_mev=imev,
        source="quicknode+coingecko",
    )

    async def _fake(*_a: object, **_k: object) -> SafetyBlock:
        return block

    monkeypatch.setattr(sc, "evaluate_contract_safety", _fake)
    r = client.post("/safety", json={"mint": _BRCA})
    assert r.status_code == 200
    body = r.json()
    assert body["gate"] == "block"
    assert body["checked"] is True
    assert body["information_mev"]["label"] == "manipulated"


def test_endpoint_fail_open_never_5xx(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import gecko_core.orchestration.trade_panel.safety_check as sc

    async def _boom(*_a: object, **_k: object) -> SafetyBlock:
        raise RuntimeError("rpc down")

    monkeypatch.setattr(sc, "evaluate_contract_safety", _boom)
    r = client.post("/safety", json={"mint": _BRCA})
    assert r.status_code == 200  # fail-OPEN, never 5xx on the fast path
    assert r.json()["gate"] == "unknown"
