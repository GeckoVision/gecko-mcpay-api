"""Naive PnL simulator for the trade-panel backtest (Phase 9 v1).

Pure math, no I/O. Given a normalized ``BacktestIntent`` and a list of
``Candle`` rows ordered ascending by ``ts``, replays a single setup:

    - Entry: candle[0].close (T0 mid; v1 uses close as a stand-in mid).
    - Stop-loss check: at daily granularity, scan the lows (longs) /
      highs (shorts) inside the hold window. If any candle violates the
      stop, exit at the stop price.
    - Otherwise exit: candle[-1].close (T0+horizon mid).

v1 limitations (documented in the spec, called out here so future PRs
don't accidentally claim more than the math delivers):

    - No slippage. No fee schedule. No oracle-staleness penalty.
    - One historical setup, not N. ``n_similar_setups`` is fixed at 1
      and ``hit_rate`` is 1.0 or 0.0.
    - Stop-loss check uses candle low/high — assumes the stop fires at
      the stop price, not at the intra-candle worst tick.

Realistic PnL is Phase 9.5 (post-falsifier validation).
"""

from __future__ import annotations

from gecko_core.orchestration.trade_panel.backtest.models import (
    BacktestIntent,
    BacktestReport,
    Candle,
)


def _max_drawdown_long(candles: list[Candle], entry: float) -> float:
    """Worst peak-to-trough drawdown for a long, expressed as positive %.

    Tracks the running peak across closes, computes the trough from each
    candle's low, and returns the max relative drop. Anchors the initial
    peak at ``entry`` so opening-bar declines count.
    """
    peak = entry
    worst = 0.0
    for c in candles:
        peak = max(peak, c.close)
        if peak <= 0:
            continue
        drop = (peak - c.low) / peak * 100.0
        if drop > worst:
            worst = drop
    return worst


def _max_drawdown_short(candles: list[Candle], entry: float) -> float:
    """Worst run-up against a short, expressed as positive %.

    Mirror of the long case: shorts bleed when price goes UP, so we track
    the running trough and the highest high above it.
    """
    trough = entry
    worst = 0.0
    for c in candles:
        trough = min(trough, c.close)
        if trough <= 0:
            continue
        rise = (c.high - trough) / trough * 100.0
        if rise > worst:
            worst = rise
    return worst


def simulate_naive_pnl(
    intent: BacktestIntent, candles: list[Candle], *, source: str = "pyth"
) -> BacktestReport:
    """Replay ``intent`` against ``candles`` using naive entry/exit math.

    Args:
        intent: Normalized intent (direction, horizon, optional stop).
        candles: Ordered ascending by ``ts``. First is T0; last is the
            exit window. Caller is responsible for slicing the right
            window — this function does not re-window.
        source: Provenance label propagated into the report.

    Returns:
        :class:`BacktestReport`. Returns ``unbacktestable=True`` with a
        stable reason when the candle list is too thin to evaluate or
        the direction is ``"neutral"`` (no PnL math defined for neutral).
    """
    src = source if source in {"pyth", "coingecko", "fallback"} else "fallback"
    if not candles or len(candles) < 2:
        return BacktestReport(
            unbacktestable=True,
            reason="no_candles",
            source=src,  # type: ignore[arg-type]
        )
    if intent.direction == "neutral":
        return BacktestReport(
            unbacktestable=True,
            reason="neutral_direction",
            source=src,  # type: ignore[arg-type]
        )

    entry = candles[0].close
    if entry <= 0:
        return BacktestReport(
            unbacktestable=True,
            reason="invalid_entry_price",
            source=src,  # type: ignore[arg-type]
        )

    # Stop-loss scan (skip T0 candle; the stop triggers on subsequent bars).
    stop_pct = intent.stop_loss_pct
    exit_price: float | None = None
    if stop_pct is not None and stop_pct > 0:
        if intent.direction == "long":
            stop_price = entry * (1.0 - stop_pct / 100.0)
            for c in candles[1:]:
                if c.low <= stop_price:
                    exit_price = stop_price
                    break
        else:  # short
            stop_price = entry * (1.0 + stop_pct / 100.0)
            for c in candles[1:]:
                if c.high >= stop_price:
                    exit_price = stop_price
                    break

    if exit_price is None:
        exit_price = candles[-1].close

    if intent.direction == "long":
        pnl_pct = (exit_price - entry) / entry * 100.0
        drawdown_pct = _max_drawdown_long(candles, entry)
    else:  # short
        pnl_pct = (entry - exit_price) / entry * 100.0
        drawdown_pct = _max_drawdown_short(candles, entry)

    hit_rate = 1.0 if pnl_pct > 0 else 0.0

    return BacktestReport(
        pnl_pct=pnl_pct,
        drawdown_pct=drawdown_pct,
        n_similar_setups=1,
        hit_rate=hit_rate,
        source=src,  # type: ignore[arg-type]
        unbacktestable=False,
        reason=None,
    )


__all__ = ["simulate_naive_pnl"]
