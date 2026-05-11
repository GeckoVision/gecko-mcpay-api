"""Shared fixtures for trade-agent tests."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def valid_spec_dict() -> dict[str, Any]:
    return {
        "name": "test-strategy",
        "version": "0.1.0",
        "vertical": "dex",
        "protocol": "okx",
        "chain": "solana",
        "entry": {
            "primitive": "buy_dip",
            "params": {"drawdown_pct": 5},
            "rule_id": "r-entry",
        },
        "exit": {
            "primitive": "take_profit",
            "params": {"target_pct": 10},
            "rule_id": "r-exit",
        },
        "sizing": {
            "primitive": "fixed_usd",
            "params": {"amount_usd": 100},
            "rule_id": "r-size",
        },
        "risk": {
            "max_concurrent_positions": 3,
            "max_single_position_pct": 20,
            "max_daily_loss_pct": 10,
        },
        "oracle_grounding": {
            "tool": "gecko_trade_research",
            "rule_verdicts": [
                {
                    "rule_id": "r-entry",
                    "verdict_id": "v-1",
                    "verdict": "act",
                    "citations": ["chunk_abc"],
                }
            ],
        },
    }
