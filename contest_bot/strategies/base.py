"""Strategy spine — the SHARED rules contract consumed by BOTH the backtest
harness and the live bot.

This is the Pattern-C kill: today `backtest_entry.py` reimplements entry/exit
in pure Python, divergent from the live monolith, so a backtest "pass" never
bound the live bot. Every strategy now implements ONE `should_enter(features)`
and ONE `exit_policy()`; the backtest and the runner both call the same code.

A strategy is pure: it reads a `features` dict (already-computed indicators) and
returns a `Signal | None`. It does NOT fetch data, hold state, or place orders —
those belong to the runner/backtest. This keeps the rules testable as a truth
table and identical across both consumption paths.

The `features` contract (every key the gates may read; producers fill what they
can, gates fail-closed on a missing REQUIRED key):

    price / close   float   last close
    adx             float   Wilder ADX(14)
    rsi             float   RSI(14)
    mfi             float   MFI(14)
    ema50           float
    ema200          float | None   (None until ~200 bars warm up)
    bb_lower        float   Bollinger(20, 2σ) lower
    bb_mid          float   Bollinger mid (SMA20) — mean-revert target
    bb_upper        float
    breakout_pct    float   % of close over the prior-N Donchian high (>=0 ⇒ new high)
    donchian_break  bool    close > max(high, prior N bars)
    regime          str     4-class regime label (trend_up/…); informational
    churn_ratio     float    Σ|Δclose|/|net Δ| over ~24 bars; ≈1 clean, ≫1 = bot churn/noise
    reversal_rate   float    bar-to-bar direction-flip rate in [0,1]; ~0.5 = oscillation/noise
    regime_1h       str     instrument 1h regime (TREND-UP/TREND-DOWN/CHOP)
    btc_regime_1h   str     BTC 1h regime — Strategy B market-wide overlay
    net_flow_verdict str|None  Solana-only; None off-chain (gates fail-open on it)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Signal:
    """An entry decision. `reason` is the gate trace (for the artifact log);
    `features` is the snapshot at decision time (for post-hoc calibration)."""

    side: str  # "long" (long-only in v0)
    reason: str
    features: dict[str, object] = field(default_factory=dict)


@dataclass
class ExitPolicy:
    """Per-strategy exit stack. The runner/backtest read these knobs; defaults
    are inert. `use_trailing=False` + `revert_to_mean=True` is the mean-reversion
    shape (snap-back trade, no trail); the breakout shape uses the trailing stack.
    All pct values are in PERCENT (1.0 == +1.0%)."""

    tp_pct: float
    sl_pct: float  # stored as a POSITIVE magnitude; -sl_pct is the trigger
    time_stop_min: int
    use_trailing: bool = False
    trail_activate_pct: float = 0.0
    trail_give_pct: float = 0.0
    trail_floor_pct: float = 0.0
    # stall-green: open >= age_min AND pnl >= min_pct → book it
    stall_green_age_min: int | None = None
    stall_green_min_pct: float = 0.0
    # flat-stall: no-new-high for N min AND pnl in [lo, hi] → cut
    flat_stall_no_new_high_min: int | None = None
    flat_stall_lo: float = 0.0
    flat_stall_hi: float = 0.0
    # mean-reversion: take profit when close reverts to the mean band
    revert_to_mean: bool = False


@runtime_checkable
class Strategy(Protocol):
    """The contract. `spec` carries the (sweepable, serializable) thresholds."""

    spec: object  # StrategySpec — avoid a circular import in the Protocol

    def should_enter(self, features: dict[str, object]) -> Signal | None: ...

    def exit_policy(self) -> ExitPolicy: ...


# ── small gate helpers (shared by trend/meanrev) ─────────────────────
def _f(features: dict[str, object], key: str) -> float | None:
    """Read a numeric feature; None if missing/None (gate decides fail open/closed)."""
    v = features.get(key)
    return float(v) if isinstance(v, (int, float)) else None
