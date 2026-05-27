"""Sprint 6 Phase B — forward simulator using Sprint 7 exit logic.

Per entry candidate (symbol, ts), walk forward bars updating peak / pnl_pct
and check exit conditions on each bar. Exit categories mirror the live bot:

- ``stop_loss`` / ``trailing_stop`` — via Sprint 7's pure helper
  ``contest_bot.jto_breakout_gecko_gated_contest_bot._evaluate_stop_exits``.
  Reusing the live helper means the backtest IS the bot at this layer.
- ``take_profit`` — pnl >= take_profit_pct
- ``stall_green_exit`` — age >= stall_green_age_min AND pnl >= stall_green_min_pct
- ``flat_stall_exit`` — age >= flat_stall_age_min AND -0.5% <= pnl <= 2% AND
  no new high in `flat_stall_no_new_high_min`
- ``time_stop`` — age >= max_hold_bars

Forward-walk is HIGH-low check per bar:
- Stop-loss / trailing fire on the bar's LOW (worst-case retrace)
- Take-profit fires on the bar's HIGH (capture peak)
- Other exits fire on the bar's CLOSE (deterministic eval points)

Cost / slippage modeled as a flat % round-trip applied to the realized PnL.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Bring the bot module onto sys.path so we can import the Sprint 7 helper
# directly. The helper is pure — no module-level side effects fire on import
# beyond the bot's normal startup (which does fire). Set OPENROUTER_API_KEY=
# in the env when invoking the backtest to skip the panel arming.
_BOT_DIR = Path(__file__).resolve().parents[3] / "contest_bot"
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

# Default config — mirror the live bot constants per Sprint 7.
DEFAULT_STOP_LOSS_PCT = 3.0
DEFAULT_TAKE_PROFIT_PCT = 2.0
DEFAULT_TRAIL_ACTIVATE_PCT = 1.0
DEFAULT_TRAIL_STOP_PCT = 0.5  # Sprint 7
DEFAULT_TRAIL_MIN_PNL_PCT = -1.0  # Sprint 7 safety guard

DEFAULT_STALL_GREEN_AGE_BARS = 15  # ≈60min at 4h candles? — see note below
DEFAULT_STALL_GREEN_MIN_PCT = 1.0
DEFAULT_FLAT_STALL_AGE_BARS = 22  # ≈90min in live (4h: 22 bars = 88h, way too long)
DEFAULT_FLAT_STALL_PNL_LO = -0.5
DEFAULT_FLAT_STALL_PNL_HI = 2.0
DEFAULT_FLAT_STALL_NO_NEW_HIGH_BARS = 7
DEFAULT_MAX_HOLD_BARS = 72  # 12 days at 4h candles; covers the bot's 12h cap × 24

DEFAULT_FLIP_COST_PCT = 0.20  # round-trip cost (entry + exit = 0.20% / leg = 0.40% total)


# NOTE on timescale translation (live bot is 30s polls; backtest is 4h candles):
# The live bot's age-min thresholds are quoted in minutes. On 4h candles a
# bar = 240 minutes, so a live STALL_GREEN_EXIT_AGE_MIN=60 → 60/240 = 0.25 bars
# (always met at bar 1). This means the bot's age-stall exits will fire much
# sooner in the simulator than they would in live — DOCUMENT this as a v1
# limitation. The headline stop_loss / take_profit / trailing exits are
# timescale-invariant (they're price-driven), so the v1 backtest validates
# THOSE faithfully; the stall-* exits are a directional proxy only.


def _evaluate_stop_exits_proxy(
    pnl_pct: float,
    peak_pct: float,
    current_price: float,
    peak_price: float,
    *,
    stop_loss_pct: float,
    trail_activate_pct: float,
    trail_stop_pct: float | None,
    trail_min_pnl_pct: float,
) -> str | None:
    """Inline Sprint 7 logic — kept here so the backtest never imports the bot.

    The bot module does heavy work at import (loads .env, arms voices, opens
    Mongo). For the backtest we want a pure-function call with zero startup
    cost. This MIRRORS contest_bot.jto_breakout_gecko_gated_contest_bot._evaluate_stop_exits
    exactly per Sprint 7. If/when the bot helper changes, this must change
    in lockstep — the test_simulator_evaluator_matches_bot test enforces parity.
    """
    if pnl_pct <= -stop_loss_pct:
        return "stop_loss"
    if trail_stop_pct is not None and peak_price > 0 and peak_pct >= trail_activate_pct:
        trail_retrace_pct = (peak_price - current_price) / peak_price * 100
        if trail_retrace_pct >= trail_stop_pct and pnl_pct > trail_min_pnl_pct:
            return "trailing_stop"
    return None


def simulate_one_entry(
    ohlcv: pd.DataFrame,
    entry_idx: int,
    *,
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
    take_profit_pct: float = DEFAULT_TAKE_PROFIT_PCT,
    trail_activate_pct: float = DEFAULT_TRAIL_ACTIVATE_PCT,
    trail_stop_pct: float | None = DEFAULT_TRAIL_STOP_PCT,
    trail_min_pnl_pct: float = DEFAULT_TRAIL_MIN_PNL_PCT,
    stall_green_age_bars: int = DEFAULT_STALL_GREEN_AGE_BARS,
    stall_green_min_pct: float = DEFAULT_STALL_GREEN_MIN_PCT,
    flat_stall_age_bars: int = DEFAULT_FLAT_STALL_AGE_BARS,
    flat_stall_pnl_lo: float = DEFAULT_FLAT_STALL_PNL_LO,
    flat_stall_pnl_hi: float = DEFAULT_FLAT_STALL_PNL_HI,
    flat_stall_no_new_high_bars: int = DEFAULT_FLAT_STALL_NO_NEW_HIGH_BARS,
    max_hold_bars: int = DEFAULT_MAX_HOLD_BARS,
    flip_cost_pct: float = DEFAULT_FLIP_COST_PCT,
) -> dict | None:
    """Simulate a single entry → exit and return one trade record.

    entry_idx is the index POSITION (int) of the entry bar. We buy at close[entry_idx]
    and start checking exits on bar entry_idx + 1.

    Returns None if there are no forward bars to simulate (entry at end of series).
    """
    if entry_idx >= len(ohlcv) - 1:
        return None

    entry_ts = ohlcv.index[entry_idx]
    entry_price = float(ohlcv["close"].iloc[entry_idx])
    peak_price = entry_price
    last_new_high_bar = entry_idx
    exit_idx: int | None = None
    exit_reason: str | None = None
    exit_price: float | None = None

    for fwd in range(1, max_hold_bars + 1):
        i = entry_idx + fwd
        if i >= len(ohlcv):
            # ran out of data — close at last available close as time-stop
            exit_idx = len(ohlcv) - 1
            exit_price = float(ohlcv["close"].iloc[exit_idx])
            exit_reason = "time_stop"
            break

        bar_high = float(ohlcv["high"].iloc[i])
        bar_low = float(ohlcv["low"].iloc[i])
        bar_close = float(ohlcv["close"].iloc[i])

        # ── Exit precedence convention (intra-bar ambiguity resolution) ──
        # On a 4h bar the order of touches (high vs low vs close) is unknown.
        # Convention: assume rally-first ordering — TP gets first dibs on the
        # bar's HIGH, then SL on the bar's LOW (the safety floor), then
        # trailing on the CLOSE (the settled price). This is the standard
        # MAE/MFE "favorable" convention for momentum strategies. It matches
        # the live bot's behavior in chop (the most common regime) where the
        # bot tends to see the peak before the retrace within a 4h window.
        #
        # 1. Take-profit on bar HIGH — captures the upside if it cleared TP
        pnl_at_high = (bar_high - entry_price) / entry_price * 100
        if pnl_at_high >= take_profit_pct:
            exit_idx = i
            exit_reason = "take_profit"
            exit_price = entry_price * (1 + take_profit_pct / 100)
            # peak update before exit (intra-bar peak counts for TP attribution)
            if bar_high > peak_price:
                peak_price = bar_high
                last_new_high_bar = i
            break

        # 2. Stop-loss / trailing — fire on bar LOW (worst-case retrace)
        #    Update peak from THIS bar's high first so trailing can see it
        #    (mirrors the live bot's monitor_positions order: peak update,
        #    then stop_loss + trailing evaluated together).
        if bar_high > peak_price:
            peak_price = bar_high
            last_new_high_bar = i
        pnl_at_low = (bar_low - entry_price) / entry_price * 100
        peak_pct_at_low = (peak_price - entry_price) / entry_price * 100
        stop_reason = _evaluate_stop_exits_proxy(
            pnl_pct=pnl_at_low,
            peak_pct=peak_pct_at_low,
            current_price=bar_low,
            peak_price=peak_price,
            stop_loss_pct=stop_loss_pct,
            trail_activate_pct=trail_activate_pct,
            trail_stop_pct=trail_stop_pct,
            trail_min_pnl_pct=trail_min_pnl_pct,
        )
        if stop_reason is not None:
            exit_idx = i
            exit_reason = stop_reason
            if stop_reason == "stop_loss":
                exit_price = entry_price * (1 - stop_loss_pct / 100)
            else:  # trailing_stop — fills at peak * (1 - trail_stop_pct/100)
                exit_price = peak_price * (1 - (trail_stop_pct or 0) / 100)
            break

        # 3. Stall-green / flat-stall / time-stop — eval on CLOSE
        pnl_close = (bar_close - entry_price) / entry_price * 100
        age_bars = i - entry_idx

        if age_bars >= stall_green_age_bars and pnl_close >= stall_green_min_pct:
            exit_idx = i
            exit_reason = "stall_green_exit"
            exit_price = bar_close
            break

        bars_since_high = i - last_new_high_bar
        if (
            age_bars >= flat_stall_age_bars
            and flat_stall_pnl_lo <= pnl_close <= flat_stall_pnl_hi
            and bars_since_high >= flat_stall_no_new_high_bars
        ):
            exit_idx = i
            exit_reason = "flat_stall_exit"
            exit_price = bar_close
            break

        if age_bars >= max_hold_bars:
            exit_idx = i
            exit_reason = "time_stop"
            exit_price = bar_close
            break

    if exit_reason is None:
        # max_hold_bars reached at top of loop
        exit_idx = entry_idx + max_hold_bars
        if exit_idx >= len(ohlcv):
            exit_idx = len(ohlcv) - 1
        exit_price = float(ohlcv["close"].iloc[exit_idx])
        exit_reason = "time_stop"

    gross_pnl_pct = (exit_price - entry_price) / entry_price * 100
    net_pnl_pct = gross_pnl_pct - flip_cost_pct
    return {
        "entry_ts": entry_ts,
        "entry_idx": entry_idx,
        "exit_ts": ohlcv.index[exit_idx],
        "exit_idx": exit_idx,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "peak_price": peak_price,
        "age_bars": exit_idx - entry_idx,
        "exit_reason": exit_reason,
        "gross_pnl_pct": gross_pnl_pct,
        "net_pnl_pct": net_pnl_pct,
    }


def simulate_symbol(
    ohlcv: pd.DataFrame,
    candidate_mask: pd.Series,
    *,
    symbol: str | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Simulate every candidate entry in a symbol's OHLCV.

    Returns DataFrame (one row per trade). Empty DataFrame if no candidates fired.
    """
    if ohlcv.empty or candidate_mask.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    last_exit_bar = -1
    for i, fire in enumerate(candidate_mask.tolist()):
        if not fire:
            continue
        # Don't open while a prior simulated trade would still be open
        if i <= last_exit_bar:
            continue
        rec = simulate_one_entry(ohlcv, i, **kwargs)
        if rec is None:
            continue
        if symbol is not None:
            rec["symbol"] = symbol
        rows.append(rec)
        last_exit_bar = rec["exit_idx"]
    return pd.DataFrame(rows)


__all__ = [
    "DEFAULT_FLIP_COST_PCT",
    "DEFAULT_MAX_HOLD_BARS",
    "DEFAULT_STOP_LOSS_PCT",
    "DEFAULT_TAKE_PROFIT_PCT",
    "DEFAULT_TRAIL_ACTIVATE_PCT",
    "DEFAULT_TRAIL_MIN_PNL_PCT",
    "DEFAULT_TRAIL_STOP_PCT",
    "_evaluate_stop_exits_proxy",
    "simulate_one_entry",
    "simulate_symbol",
]
