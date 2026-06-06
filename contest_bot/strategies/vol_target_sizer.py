"""V1 — `vol_target_sizer` (a SIZING OVERLAY, not a standalone strategy).

This is NOT an entry rule. It has no `should_enter`. It is a pure function that
scales an existing strategy's position fraction so that $-risk per trade is
roughly constant across volatility regimes (GARCH/vol-clustering prior).

    position_fraction = base_fraction * clamp(target_vol / realized_vol, lo, hi)

High realized vol  -> smaller size (constant $-risk).
Calm  realized vol -> up to `hi`x base.

CRITICAL CONSTRAINTS (enforced by how it is consumed, see the gauntlet):
  - NEVER evaluated standalone (it has no entry signal of its own).
  - Tested ONLY as a modifier: `T1+V1 vs T1`, `R1+V1 vs R1`, on Sharpe/maxDD.
  - It CANNOT create alpha. It can flatten $-risk and cut maxDD on an existing
    stream; it cannot turn a -EV stream +EV (smaller bets on a losing edge still
    lose). A V1 Sharpe-improvement on a -EV base is NOT "the slate works".

`realized_vol` is the stdev of per-bar log-ish returns over a trailing window
(default 24 bars ~= 2h on 5m). `target_vol` is the trailing-30d median realized
vol per symbol (the "normal" vol the sizer normalizes to). Both are computed
causally (point-in-time) by the caller and passed in.
"""

from __future__ import annotations

import math
import statistics as st
from dataclasses import dataclass


@dataclass
class VolTargetConfig:
    """Sweepable knobs for the overlay (these count in the DSR n_trials)."""

    window: int = 24  # bars for realized-vol estimate
    target_window_bars: int = 8640  # ~30d of 5m bars for the median-vol target
    clamp_lo: float = 0.4
    clamp_hi: float = 1.5


def realized_vol(closes: list[float], window: int = 24) -> float | None:
    """Trailing realized volatility = stdev of bar-to-bar returns over `window`.

    Returns None if fewer than `window`+1 closes (insufficient warm-up). Uses
    simple returns (close[i]/close[i-1]-1); for the small per-bar moves on 5m
    majors this is numerically indistinguishable from log returns and avoids a
    log of a non-positive ratio on bad data."""
    if len(closes) < window + 1:
        return None
    w = closes[-(window + 1) :]
    rets = []
    for i in range(1, len(w)):
        if w[i - 1] > 0:
            rets.append(w[i] / w[i - 1] - 1.0)
    if len(rets) < 2:
        return None
    return st.pstdev(rets)


def vol_target_multiplier(
    realized: float | None,
    target: float | None,
    cfg: VolTargetConfig | None = None,
) -> float:
    """The sizing multiplier in [clamp_lo, clamp_hi].

    Returns 1.0 (no adjustment) when either input is missing/degenerate — the
    overlay fails OPEN to the base fraction, never to zero size (a sizing bug
    must not silently halt the strategy)."""
    cfg = cfg or VolTargetConfig()
    if realized is None or target is None:
        return 1.0
    if realized <= 0 or target <= 0 or math.isnan(realized) or math.isnan(target):
        return 1.0
    raw = target / realized
    return max(cfg.clamp_lo, min(cfg.clamp_hi, raw))


def sized_fraction(
    base_fraction: float,
    realized: float | None,
    target: float | None,
    cfg: VolTargetConfig | None = None,
) -> float:
    """base_fraction scaled by the vol-target multiplier. Pure; no state."""
    return base_fraction * vol_target_multiplier(realized, target, cfg)
