"""gecko_safety — the componentized Trade-Safety SDK facade.

ONE clean import that wraps the two halves of the safety wedge:
  • verify_strategy(...)  — the rigor gate (CPCV/PBO/DSR §5 verdict) = "is this
    strategy safe to trust with money / will it blow up out-of-sample?"
  • safety_check(order)   — the pre-trade gate (caps, daily-loss breaker, allowlist,
    kill-switch, unverified-can't-trade) = "keep my agent from blowing up."

This is the consume-only surface a future public skill / partner SDK exposes
(per the Jito/Jupiter verdict: sell the verify-before-capital verdict, not a
platform). Componentized but NOT published yet — the eventual home is a clean
`packages/` module; this facade keeps the lab importable as one unit today.

    from gecko_safety import verify_strategy, safety_check, TradeSafetyPolicy, Order
    verdict = verify_strategy("trend_breakout", entry_gates={"churn_max": 3.0})
    ok = safety_check(Order("BTC/USDT", "okx", 50.0))   # SafetyVerdict(allow, reasons)
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from trade_safety import (  # noqa: E402  re-export the safety-gate surface
    DelegatedExecutionAdapter,
    ExecResult,
    Order,
    PaperExecutionAdapter,
    SafetyContext,
    SafetyVerdict,
    TradeSafetyPolicy,
    check_order,
    dispatch,
)


def verify_strategy(
    strategy_id: str = "trend_breakout",
    entry_gates: dict | None = None,
    exit: dict | None = None,
    coins: list[str] | None = None,
    fee_pct: float = 0.20,
) -> dict:
    """Verify-before-capital: run the rigor gate and return the JSON verdict
    envelope (verdict, rigor metrics, per-symbol CI, churn). Lazy-imports the
    backtest harness so importing the safety gate alone stays light. Raises
    ValueError if the majors data isn't ingested yet."""
    import backtest_strategy as _bt

    return _bt.run_backtest(
        strategy_id=strategy_id, entry_gates=entry_gates, exit_overrides=exit,
        coins=coins, fee_pct=fee_pct,
    )


def safety_check(
    order: Order, policy: TradeSafetyPolicy | None = None, ctx: SafetyContext | None = None
) -> SafetyVerdict:
    """Pre-trade gate: allow/deny + reasons. Deny-default. Defaults to a
    conservative policy + an unverified context (which blocks real money)."""
    return check_order(order, policy or TradeSafetyPolicy(), ctx or SafetyContext())


__all__ = [
    "DelegatedExecutionAdapter",
    "ExecResult",
    "Order",
    "PaperExecutionAdapter",
    "SafetyContext",
    "SafetyVerdict",
    "TradeSafetyPolicy",
    "check_order",
    "dispatch",
    "safety_check",
    "verify_strategy",
]
