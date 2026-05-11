"""Backtest harness for the trade-agent runtime.

Public surface:

* :func:`gecko_backtest` — async entry point.
* :class:`BacktestHarness` — OO entry point (most callers won't need it).
* :class:`BacktestResult` / :class:`BacktestRun` / :class:`Trade` —
  output wire shapes.

The harness reuses runtime primitives (no parallel implementation) so
replay results predict live behaviour. Per the founder constraint
(``feedback_okx_no_funding_pressure``), the harness NEVER calls
``gecko_trade_research`` for real — the oracle is always a fixture.
"""

from gecko_core.trade_agent.backtest.harness import (
    BacktestHarness,
    gecko_backtest,
    run_backtest_sync,
)
from gecko_core.trade_agent.backtest.history import (
    FixtureHistorySource,
    HistorySource,
    MongoHotpathHistorySource,
    PythHistoricalHistorySource,
)
from gecko_core.trade_agent.backtest.models import (
    BacktestResult,
    BacktestRun,
    GatingMode,
    Trade,
)
from gecko_core.trade_agent.backtest.oracle_fixture import (
    OptimisticOracleFixture,
    PessimisticOracleFixture,
    RecordedOracleFixture,
)

__all__ = [
    "BacktestHarness",
    "BacktestResult",
    "BacktestRun",
    "FixtureHistorySource",
    "GatingMode",
    "HistorySource",
    "MongoHotpathHistorySource",
    "OptimisticOracleFixture",
    "PessimisticOracleFixture",
    "PythHistoricalHistorySource",
    "RecordedOracleFixture",
    "Trade",
    "gecko_backtest",
    "run_backtest_sync",
]
