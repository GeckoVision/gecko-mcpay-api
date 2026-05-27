"""Sprint 6 Phase B — entry signal detection.

The bot's autopsy showed 19/19 acted trades had ``signal_type=price_breakout``
and ``regime_at_entry=trend_up``. v1 mirrors exactly this slice:

- ``price_breakout`` = close[t] > max(high[t-N : t]) (the "N-bar prior high")
- Trend filter (proxy for Fix 5 regime_1h TREND-UP) = close[t] > sma(W)[t]

Both gates apply per-bar. Output: a boolean Series aligned to the OHLCV index
where True = bar t qualifies as a candidate entry. Per-bar candidates feed
the simulator which forward-walks for exits.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_BREAKOUT_LOOKBACK = 20  # bars (≈ 3.3 days on 4h candles)
DEFAULT_TREND_SMA_WINDOW = 20  # bars (same; "close > 20-bar SMA" = TREND-UP proxy)


def price_breakout(
    ohlcv: pd.DataFrame,
    lookback: int = DEFAULT_BREAKOUT_LOOKBACK,
) -> pd.Series:
    """Return Series[bool] True where close[t] > max(high[t-lookback : t]).

    The lookback window is the ``lookback`` bars STRICTLY BEFORE t (no
    self-inclusion — that would be trivially True for any new high).
    """
    if ohlcv.empty or "close" not in ohlcv.columns or "high" not in ohlcv.columns:
        return pd.Series(dtype=bool)
    prior_high = ohlcv["high"].shift(1).rolling(window=lookback, min_periods=lookback).max()
    return (ohlcv["close"] > prior_high).fillna(False).astype(bool)


def trend_up(
    ohlcv: pd.DataFrame,
    window: int = DEFAULT_TREND_SMA_WINDOW,
) -> pd.Series:
    """Return Series[bool] True where close[t] > sma(close, window)[t].

    Proxy for the bot's regime_1h=TREND-UP filter — only fire entries when
    the broader trend (sma over `window` bars) is up. The bot uses a real
    HTF EMA stack; this is the cheapest defensible 4h proxy.
    """
    if ohlcv.empty or "close" not in ohlcv.columns:
        return pd.Series(dtype=bool)
    sma = ohlcv["close"].rolling(window=window, min_periods=window).mean()
    return (ohlcv["close"] > sma).fillna(False).astype(bool)


def candidate_entries(
    ohlcv: pd.DataFrame,
    breakout_lookback: int = DEFAULT_BREAKOUT_LOOKBACK,
    trend_window: int = DEFAULT_TREND_SMA_WINDOW,
) -> pd.Series:
    """Return Series[bool] True where bar t is a candidate entry.

    Composite gate: ``price_breakout AND trend_up``. This is the bot's
    "armed for entry" state in the v1 backtest. Per Pattern E discipline:
    a candidate at t means we'd buy at close[t]; exit logic walks forward
    from bar t+1.
    """
    if ohlcv.empty:
        return pd.Series(dtype=bool)
    bo = price_breakout(ohlcv, lookback=breakout_lookback)
    tu = trend_up(ohlcv, window=trend_window)
    return (bo & tu).fillna(False).astype(bool)


def dedupe_entries(
    candidates: pd.Series,
    cooldown_bars: int = 1,
) -> pd.Series:
    """Drop back-to-back candidate signals within `cooldown_bars` of each other.

    If candidate_entries fires on consecutive bars (which it can during a
    sustained breakout), we only count the FIRST. Mirrors the bot's per-
    instrument "one open position at a time" gate without needing a stateful
    open-position tracker in the harness.
    """
    if candidates.empty:
        return candidates
    out = candidates.copy()
    last_fire_idx: int | None = None
    arr = candidates.to_numpy()
    for i in range(len(arr)):
        if not arr[i]:
            continue
        if last_fire_idx is not None and (i - last_fire_idx) <= cooldown_bars:
            out.iloc[i] = False
        else:
            last_fire_idx = i
    return out


__all__ = [
    "DEFAULT_BREAKOUT_LOOKBACK",
    "DEFAULT_TREND_SMA_WINDOW",
    "candidate_entries",
    "dedupe_entries",
    "price_breakout",
    "trend_up",
]
