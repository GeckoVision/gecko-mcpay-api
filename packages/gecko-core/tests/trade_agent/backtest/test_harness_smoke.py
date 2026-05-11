"""Smoke tests — harness loads, runs, suppresses correctly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gecko_core.trade_agent.backtest import (
    BacktestResult,
    FixtureHistorySource,
    OptimisticOracleFixture,
    PessimisticOracleFixture,
    gecko_backtest,
)
from gecko_core.trade_agent.spec import load_spec

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "backtest"


def _spec_buy_dip() -> dict[str, Any]:
    return {
        "name": "smoke-buy-dip",
        "version": "0.1.0",
        "vertical": "dex",
        "protocol": "okx",
        "chain": "solana",
        "entry": {"primitive": "buy_dip", "params": {"drawdown_pct": 5}, "rule_id": "r1"},
        "exit": {"primitive": "take_profit", "params": {"target_pct": 8}, "rule_id": "r2"},
        "sizing": {"primitive": "fixed_usd", "params": {"amount_usd": 1000}, "rule_id": "r3"},
        "filter": {"require_oracle_act": True, "block_honeypot": True},
        "risk": {
            "max_concurrent_positions": 3,
            "max_single_position_pct": 50,
            "max_daily_loss_pct": 50,
        },
        "oracle_grounding": {
            "tool": "gecko_trade_research",
            "rule_verdicts": [
                {"rule_id": "r1", "verdict_id": "v-seed", "verdict": "act", "citations": ["c"]}
            ],
        },
    }


@pytest.mark.asyncio
async def test_harness_smoke_runs_both_arms() -> None:
    spec = load_spec(_spec_buy_dip())
    history = FixtureHistorySource(FIXTURE_DIR / "solana_30d_synthetic.json")
    # Use optimistic oracle so the gated arm actually trades (not zero).
    oracle = OptimisticOracleFixture()
    from gecko_core.trade_agent.backtest.harness import BacktestHarness

    result = await BacktestHarness(spec, history=history, oracle=oracle).run(
        gating="both", window_days=30
    )
    assert isinstance(result, BacktestResult)
    assert result.gated is not None
    assert result.ungated is not None
    # Optimistic oracle => gated should look ~identical to ungated.
    assert result.gated.n_trades == result.ungated.n_trades
    assert result.gated.pnl_pct == pytest.approx(result.ungated.pnl_pct, abs=1e-6)


@pytest.mark.asyncio
async def test_harness_pessimistic_suppresses_all_trades() -> None:
    spec = load_spec(_spec_buy_dip())
    history = FixtureHistorySource(FIXTURE_DIR / "solana_30d_synthetic.json")
    oracle = PessimisticOracleFixture()
    from gecko_core.trade_agent.backtest.harness import BacktestHarness

    result = await BacktestHarness(spec, history=history, oracle=oracle).run(
        gating="both", window_days=30
    )
    assert result.gated is not None
    assert result.gated.n_trades == 0
    assert result.gated.pnl_pct == 0.0
    # Ungated should be unaffected
    assert result.ungated is not None


@pytest.mark.asyncio
async def test_gecko_backtest_entry_point_default() -> None:
    spec = _spec_buy_dip()
    result = await gecko_backtest(spec, gating="both", window_days=30)
    assert result.spec_id.startswith("spec_")
    assert result.window_days == 30
    # Default oracle is Pessimistic — gated arm should have zero trades.
    assert result.gated is not None
    assert result.gated.n_trades == 0
