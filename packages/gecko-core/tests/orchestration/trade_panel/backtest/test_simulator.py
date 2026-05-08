"""Naive PnL simulator tests (Phase 9 v1).

Per CLAUDE.md feedback_lighter_tests: test the pure math directly with
constructed Candle rows — no Mongo, no Pyth, no history-source. The
public ``backtest_intent`` is exercised via the unbacktestable-fallback
case so the normalize → fetch → simulate pipeline gets one end-to-end
hit without I/O.
"""

from __future__ import annotations

import pytest
from gecko_core.orchestration.trade_panel.backtest import (
    BacktestIntent,
    BacktestReport,
    Candle,
    HistorySource,
    backtest_intent,
)
from gecko_core.orchestration.trade_panel.backtest.simulator import simulate_naive_pnl


def _candle(ts: int, *, o: float, h: float, lo: float, c: float) -> Candle:
    return Candle(
        protocol="kamino",
        ts=ts,
        granularity="1d",
        source="pyth",
        open=o,
        high=h,
        low=lo,
        close=c,
    )


def test_long_winner_emits_positive_pnl_and_hit_rate_one() -> None:
    intent = BacktestIntent(protocol="kamino", direction="long", horizon_days=14)
    candles = [
        _candle(0, o=100, h=102, lo=99, c=100),
        _candle(86_400, o=100, h=110, lo=100, c=108),
        _candle(86_400 * 2, o=108, h=116, lo=108, c=115),
    ]
    report = simulate_naive_pnl(intent, candles)
    assert isinstance(report, BacktestReport)
    assert report.unbacktestable is False
    # (115 - 100) / 100 * 100 = 15.0%
    assert report.pnl_pct == pytest.approx(15.0)
    assert report.hit_rate == 1.0
    assert report.n_similar_setups == 1
    assert report.source == "pyth"
    # Drawdown is the worst (peak - low) / peak over the path:
    # day1 close lifts peak to 108; that bar's low=100 → 7.407%.
    assert report.drawdown_pct == pytest.approx(7.4074074074, abs=1e-4)


def test_short_loser_emits_negative_pnl_and_zero_hit_rate() -> None:
    intent = BacktestIntent(protocol="kamino", direction="short", horizon_days=14)
    candles = [
        _candle(0, o=100, h=101, lo=99, c=100),
        _candle(86_400, o=100, h=112, lo=100, c=110),
        _candle(86_400 * 2, o=110, h=116, lo=110, c=115),
    ]
    report = simulate_naive_pnl(intent, candles)
    # Short PnL: (entry - exit) / entry. (100 - 115) / 100 * 100 = -15.0
    assert report.pnl_pct == pytest.approx(-15.0)
    assert report.hit_rate == 0.0
    # Short drawdown = highest run-up from the trough; trough=100, peak=116
    # → (116 - 100) / 100 * 100 = 16%.
    assert report.drawdown_pct == pytest.approx(16.0)


def test_stop_loss_triggers_at_daily_granularity_for_long() -> None:
    """Long with stop at -10%; intraday low pierces the stop on day 1."""
    intent = BacktestIntent(
        protocol="kamino", direction="long", horizon_days=14, stop_loss_pct=10.0
    )
    candles = [
        _candle(0, o=100, h=102, lo=99, c=100),
        # Day 1 low 89 < stop 90 → exit @ 90
        _candle(86_400, o=98, h=99, lo=89, c=92),
        # If the stop hadn't fired, exit close would be 105.
        _candle(86_400 * 2, o=92, h=106, lo=92, c=105),
    ]
    report = simulate_naive_pnl(intent, candles)
    assert report.unbacktestable is False
    # Exit at stop price 90 → (90 - 100) / 100 * 100 = -10.0
    assert report.pnl_pct == pytest.approx(-10.0)
    assert report.hit_rate == 0.0


@pytest.mark.asyncio
async def test_unbacktestable_when_history_source_returns_no_candles() -> None:
    """End-to-end: backtest_intent returns the graceful unbacktestable shape.

    Mirrors what production sees when Pyth Hermes has no OHLCV available:
    the history source returns an empty list and the public function maps
    that to ``BacktestReport(unbacktestable=True, reason='pyth_no_history')``.
    """

    class _EmptySource:
        async def fetch(
            self, protocol: str, *, granularity: str, ts_start: int, ts_end: int
        ) -> list[Candle]:
            return []

    source: HistorySource = _EmptySource()  # type: ignore[assignment]
    report = await backtest_intent(
        {"protocol": "jito", "direction": "long", "exit_horizon": "14d"},
        source,
        now_ts=1_700_000_000,
    )
    assert report.unbacktestable is True
    assert report.reason == "pyth_no_history"
    assert report.source == "pyth"
