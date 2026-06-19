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


def test_warm_hit_from_monitor_is_served(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Launch Firewall step 4 — Pattern-E reachability: an attack driven through
    the monitor lands in the shared cache and /safety serves it WARM (gate=block,
    source=monitor) without ever calling the on-demand read."""
    import asyncio

    # The on-demand path must NOT be hit on a warm read — make it explode if it is.
    import gecko_core.orchestration.trade_panel.safety_check as sc
    from gecko_api import main as api_main
    from gecko_api.safety_fast import serve_safety
    from gecko_core.trade_agent.hotpath.token_state import SwapEvent
    from gecko_core.trade_agent.hotpath.wash_signals import PoolSnapshot

    async def _must_not_run(*_a: object, **_k: object) -> SafetyBlock:
        raise AssertionError("warm hit must not call evaluate_contract_safety")

    monkeypatch.setattr(sc, "evaluate_contract_safety", _must_not_run)

    store = api_main.app.state.safety_store
    monitor = api_main.app.state.safety_monitor
    now = 100_000.0
    created = int(now - 120)
    monitor.track(_BRCA, pool_created_ts=created)
    price = 1.0
    for i in range(38):
        monitor.ingest_swap(
            _BRCA,
            SwapEvent(
                ts=float(created + i),
                wallet=f"bot{i % 3}",
                side="buy",
                notional_usd=30.0,
                price_usd=price,
            ),
        )
        price *= 1.01
    monitor.update_pool(
        _BRCA,
        PoolSnapshot(pool_addr="deep", spot_price_usd=1.45, tvl_usd=400_000.0, swap_count_5m=38),
    )
    monitor.update_pool(
        _BRCA, PoolSnapshot(pool_addr="bait", spot_price_usd=3.5, tvl_usd=200.0, swap_count_5m=0)
    )

    async def _scenario() -> dict:
        await monitor.recompute(_BRCA, now)
        return await serve_safety(_BRCA, store, monitor, now=now)

    resp = asyncio.run(_scenario())
    assert resp["gate"] == "block"
    assert resp["source"] == "monitor"
    assert resp["wash_risk"]["label"] == "manipulated"
    assert resp["staleness_s"] == 0.0
