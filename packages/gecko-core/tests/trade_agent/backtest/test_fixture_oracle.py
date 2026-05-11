"""Tests for the offline oracle fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from gecko_core.trade_agent.backtest.oracle_fixture import (
    OptimisticOracleFixture,
    PessimisticOracleFixture,
    RecordedOracleFixture,
)
from gecko_core.trade_agent.oracle import idea_hash


@pytest.mark.asyncio
async def test_recorded_round_trip(tmp_path: Path) -> None:
    key = idea_hash("buy_dip:MINT_X")
    payload = {key: {"verdict": "act", "confidence": 0.9, "verdict_id": "v1", "citations": []}}
    p = tmp_path / "verdicts.json"
    p.write_text(json.dumps(payload))
    fix = RecordedOracleFixture(p)
    out = await fix(idea="buy_dip:MINT_X", tier="basic", agent_id="a")
    assert out["verdict"] == "act"
    assert out["verdict_id"] == "v1"
    # Second call same key — cache hit metric should bump
    await fix(idea="buy_dip:MINT_X", tier="basic", agent_id="a")
    assert fix.call_count == 2
    assert fix.cache_hits == 1


@pytest.mark.asyncio
async def test_recorded_default_for_unknown() -> None:
    fix = RecordedOracleFixture(records={})
    out = await fix(idea="buy_dip:UNKNOWN", tier="basic", agent_id="a")
    # Default policy is conservative pass
    assert out["verdict"] == "pass"


@pytest.mark.asyncio
async def test_optimistic_always_act() -> None:
    fix = OptimisticOracleFixture()
    for idea in ("buy_dip:A", "momentum_follow:B", "snipe_new:C"):
        out = await fix(idea=idea)
        assert out["verdict"] == "act"
        assert out["confidence"] == 1.0
    assert fix.call_count == 3


@pytest.mark.asyncio
async def test_pessimistic_always_pass() -> None:
    fix = PessimisticOracleFixture()
    out = await fix(idea="anything")
    assert out["verdict"] == "pass"
