"""Advisor mode evaluator — pure-function checks against schema enums."""

from __future__ import annotations

from gecko_core.trade_agent.modes import AdvisorMode
from gecko_core.trade_agent.spec import load_spec


def test_advisor_buy_dip_hit(valid_spec_dict):
    spec = load_spec(valid_spec_dict)
    advisor = AdvisorMode(spec=spec)
    candidate = advisor.evaluate({"mint": "So11", "drawdown_pct": 10})
    assert candidate is not None
    assert candidate.mint == "So11"
    assert candidate.rule_id == "r-entry"


def test_advisor_buy_dip_miss(valid_spec_dict):
    spec = load_spec(valid_spec_dict)
    advisor = AdvisorMode(spec=spec)
    candidate = advisor.evaluate({"mint": "So11", "drawdown_pct": 1})
    assert candidate is None


def test_advisor_missing_mint_returns_none(valid_spec_dict):
    spec = load_spec(valid_spec_dict)
    advisor = AdvisorMode(spec=spec)
    assert advisor.evaluate({"drawdown_pct": 99}) is None


def test_advisor_dca_only_fires_on_tick(valid_spec_dict):
    valid_spec_dict["entry"] = {
        "primitive": "dca",
        "params": {"per_tick_usd": 50},
        "rule_id": "r-entry",
    }
    spec = load_spec(valid_spec_dict)
    advisor = AdvisorMode(spec=spec)
    assert advisor.evaluate({"mint": "So11"}) is None
    c = advisor.evaluate({"mint": "So11", "kind": "dca_tick"})
    assert c is not None
    assert c.nominal_size_usd == 50.0
