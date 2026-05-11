"""Strategy primitives — entry, exit, sizing, risk, filter evaluators.

Each module exposes pure functions / small dataclasses that take a spec
block + an event/context and return a decision. The mode evaluators in
:mod:`gecko_core.trade_agent.modes` compose them.

Primitives are kept dependency-free (no Mongo, no MCP, no network) so
they're trivially unit-testable and so the backtest harness can reuse
the exact same code path (avoiding the eval-bypass-runner trap noted in
memory `feedback_eval_harness_rag_gap.md`).
"""

from gecko_core.trade_agent.primitives.entry import evaluate_entry
from gecko_core.trade_agent.primitives.exit import evaluate_exit
from gecko_core.trade_agent.primitives.filter import passes_filter
from gecko_core.trade_agent.primitives.risk import RiskState, would_breach
from gecko_core.trade_agent.primitives.sizing import compute_size_usd

__all__ = [
    "RiskState",
    "compute_size_usd",
    "evaluate_entry",
    "evaluate_exit",
    "passes_filter",
    "would_breach",
]
