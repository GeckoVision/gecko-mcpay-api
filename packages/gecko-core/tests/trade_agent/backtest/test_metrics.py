"""Pure-function metric tests."""

from __future__ import annotations

import math

import pytest
from gecko_core.trade_agent.backtest.metrics import (
    hit_rate,
    max_drawdown_pct,
    pnl_pct,
    returns_from_equity,
    sharpe_annualized,
)
from gecko_core.trade_agent.backtest.models import Trade


def _t(pnl: float) -> Trade:
    return Trade(
        entry_ts=0.0,
        exit_ts=1.0,
        entry_price=1.0,
        exit_price=1.0 + pnl,
        size=1.0,
        side="long",
        pnl=pnl,
    )


def test_sharpe_known_series() -> None:
    # All-equal returns => zero variance => 0.0 by our convention
    assert sharpe_annualized([0.01, 0.01, 0.01]) == 0.0

    # Positive mean with variance — sign should be positive.
    s = sharpe_annualized([0.01, -0.005, 0.02, 0.015, -0.01])
    assert s > 0

    # Symmetric series should give Sharpe near 0.
    s0 = sharpe_annualized([0.01, -0.01, 0.01, -0.01])
    assert abs(s0) < 0.01

    # Empty / single-point
    assert sharpe_annualized([]) == 0.0
    assert sharpe_annualized([0.01]) == 0.0


def test_max_drawdown_basic() -> None:
    # Monotone up — no drawdown
    assert max_drawdown_pct([100, 110, 120, 130]) == 0.0

    # Peak 200, trough 100 from peak => 50%
    assert max_drawdown_pct([100, 200, 100, 150]) == pytest.approx(50.0)

    # Empty
    assert max_drawdown_pct([]) == 0.0

    # Single point
    assert max_drawdown_pct([100]) == 0.0


def test_hit_rate_edges() -> None:
    assert hit_rate([]) == 0.0
    assert hit_rate([_t(1.0), _t(2.0)]) == 1.0
    assert hit_rate([_t(-1.0), _t(-2.0)]) == 0.0
    assert hit_rate([_t(1.0), _t(-1.0)]) == 0.5
    # 0 pnl is not a hit
    assert hit_rate([_t(0.0), _t(0.0)]) == 0.0


def test_pnl_pct_basic() -> None:
    assert pnl_pct([100, 110]) == pytest.approx(10.0)
    assert pnl_pct([100, 90]) == pytest.approx(-10.0)
    assert pnl_pct([]) == 0.0
    assert pnl_pct([100]) == 0.0
    assert pnl_pct([0, 100]) == 0.0  # div-by-zero guard


def test_returns_from_equity() -> None:
    r = returns_from_equity([100, 110, 99])
    assert r[0] == pytest.approx(0.1)
    assert r[1] == pytest.approx(-0.1)
    # Zero-base step => 0.0
    r2 = returns_from_equity([0, 100, 110])
    assert r2[0] == 0.0
    assert r2[1] == pytest.approx(0.1)


def test_sharpe_finite_on_nans() -> None:
    # Defensive — Sharpe must never return inf/nan
    s = sharpe_annualized([0.0, 0.0])
    assert math.isfinite(s)
