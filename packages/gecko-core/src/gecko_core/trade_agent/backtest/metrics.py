"""Pure-function trade statistics.

Sharpe / max-drawdown / hit-rate / PnL percentage helpers used by the
backtest harness. No I/O, no async, no Pydantic — these are math
primitives so they're trivially unit-testable and so the harness can
call them at the tail of either replay path without ceremony.

Conventions:

* Returns are *period* returns (close-to-close). Sharpe annualisation
  multiplies by ``sqrt(freq)`` with ``freq`` defaulting to 252 (trading
  days). A daily-snapshot equity curve therefore yields an annualised
  Sharpe out of the box.
* ``max_drawdown_pct`` returns a *positive* percentage — the magnitude
  of the worst peak-to-trough decline. A 20% drawdown returns ``20.0``.
* ``hit_rate`` is a fraction in ``[0.0, 1.0]``. Empty inputs return 0.0.
* All outputs rounded to 6 decimal places so JSON serialisation is
  byte-stable across runs.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from gecko_core.trade_agent.backtest.models import Trade

_PRECISION = 6


def _round(x: float) -> float:
    if not math.isfinite(x):
        return 0.0
    return round(x, _PRECISION)


def sharpe_annualized(returns: Sequence[float], freq: int = 252) -> float:
    """Annualised Sharpe of a return series. Risk-free rate assumed 0.

    Returns 0.0 for empty input or zero-variance series — the latter is
    a degenerate case (no risk taken) and we prefer 0 over inf so the
    delta arithmetic in :mod:`harness` doesn't blow up.
    """
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if var <= 0:
        return 0.0
    std = math.sqrt(var)
    return _round((mean / std) * math.sqrt(freq))


def max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    """Worst peak-to-trough decline as a positive percent.

    Empty / single-point curves → 0.0. Non-positive equity (curve hit
    zero) is treated as 100% drawdown from the peak.
    """
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        if peak <= 0:
            continue
        dd = (peak - v) / peak * 100
        if dd > worst:
            worst = dd
    return _round(worst)


def hit_rate(trades: Sequence[Trade]) -> float:
    """Fraction of trades with strictly positive PnL."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return _round(wins / len(trades))


def pnl_pct(equity_curve: Sequence[float]) -> float:
    """Total return as a percent: ``(final / initial - 1) * 100``.

    Empty curve → 0.0. Initial-equity zero → 0.0 (avoids div-by-zero;
    a backtest that starts at zero bankroll has nothing to measure).
    """
    if len(equity_curve) < 2:
        return 0.0
    initial = equity_curve[0]
    final = equity_curve[-1]
    if initial == 0:
        return 0.0
    return _round((final / initial - 1) * 100)


def returns_from_equity(equity_curve: Sequence[float]) -> list[float]:
    """Period returns derived from an equity curve.

    Helper so callers don't reimplement the diff. Skips zero/negative
    base points (treats them as a flat 0% return for the next step) to
    keep Sharpe finite on pathological inputs.
    """
    out: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        cur = equity_curve[i]
        if prev <= 0:
            out.append(0.0)
        else:
            out.append((cur - prev) / prev)
    return out


__all__ = [
    "hit_rate",
    "max_drawdown_pct",
    "pnl_pct",
    "returns_from_equity",
    "sharpe_annualized",
]
