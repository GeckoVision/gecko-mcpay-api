"""Strategy A — `trend_breakout` (momentum / trend-following).

Rides confirmed intraday breakouts on a TRENDING tape. The cleaned-up version
of the live memecoin logic, re-pointed at majors. Long-only v0.

Entry (all must hold) — spec §2 Strategy A:
  Donchian breakout   close > max(high, prior 48 bars)   (donchian_break)
  Breakout magnitude  >= 0.5% over the prior high          (breakout_pct)
  Trend strength      ADX(14) >= 22                        ← orthogonality gate
  Direction           close > EMA(50)
  Not blow-off        RSI(14) < 75
  Flow confirm        MFI in [50, 70)  (S30: MFI>=70 = stall bleed, excluded)
"""

from __future__ import annotations

from .base import ExitPolicy, Signal, _f
from .spec import StrategySpec


def default_spec() -> StrategySpec:
    return StrategySpec(
        strategy_id="trend_breakout",
        version="v0",
        universe=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        timeframe="5m",
        venue="okx_spot",
        entry_gates={
            "donchian_lookback": 48,
            "breakout_magnitude_min_pct": 0.5,
            "adx_min": 22.0,
            "ema_filter": 50,
            "rsi_max": 75.0,
            "mfi_min": 50.0,
            "mfi_max": 70.0,
            # S33: decline "breakouts" born in churn/noise (path ≫ displacement) —
            # those are the fake-outs that immediately revert. None = gate off.
            "churn_max": 4.0,
        },
        exit={
            "tp_pct": 1.0,
            "sl_pct": 0.8,
            "trail_activate_pct": 0.5,
            "trail_give_pct": 0.3,
            "trail_floor_pct": 1.0,
            "stall_green_age_min": 60,
            "stall_green_min_pct": 0.5,
            "flat_stall_no_new_high_min": 30,
            "flat_stall_lo": -1.0,
            "flat_stall_hi": 0.5,
            "time_stop_min": 360,
        },
    )


class TrendBreakout:
    def __init__(self, spec: StrategySpec | None = None) -> None:
        self.spec = spec or default_spec()

    def should_enter(self, features: dict[str, object]) -> Signal | None:
        g = self.spec.entry_gates
        close = _f(features, "close") or _f(features, "price")
        adx = _f(features, "adx")
        rsi = _f(features, "rsi")
        mfi = _f(features, "mfi")
        ema50 = _f(features, "ema50")
        breakout_pct = _f(features, "breakout_pct")
        donchian_break = bool(features.get("donchian_break"))

        # required features — fail CLOSED if any missing (don't enter on partial data)
        if (
            close is None
            or adx is None
            or rsi is None
            or mfi is None
            or ema50 is None
            or breakout_pct is None
        ):
            return None

        # Donchian new high (either the explicit flag or a positive breakout_pct)
        if not (donchian_break or breakout_pct > 0):
            return None
        if breakout_pct < g["breakout_magnitude_min_pct"]:
            return None
        if adx < g["adx_min"]:
            return None
        if close <= ema50:
            return None
        if rsi >= g["rsi_max"]:
            return None
        if not (g["mfi_min"] <= mfi < g["mfi_max"]):
            return None
        # S33 churn gate: decline a breakout born in noise (path ≫ net move).
        # churn_max None ⇒ gate off (for backtest A/B). Fail-open if feature absent.
        churn_max = g.get("churn_max")
        churn = _f(features, "churn_ratio")
        if churn_max is not None and churn is not None and churn >= churn_max:
            return None

        reason = (
            f"trend_breakout: brk={breakout_pct:.2f}%>={g['breakout_magnitude_min_pct']} "
            f"adx={adx:.1f}>={g['adx_min']} close>ema50 rsi={rsi:.0f}<{g['rsi_max']:.0f} "
            f"mfi={mfi:.0f}∈[{g['mfi_min']:.0f},{g['mfi_max']:.0f})"
        )
        if churn is not None:
            reason += f" churn={churn:.1f}<{churn_max}"
        return Signal(side="long", reason=reason, features=dict(features))

    def exit_policy(self) -> ExitPolicy:
        e = self.spec.exit
        return ExitPolicy(
            tp_pct=e["tp_pct"],
            sl_pct=e["sl_pct"],
            time_stop_min=e["time_stop_min"],
            use_trailing=True,
            trail_activate_pct=e["trail_activate_pct"],
            trail_give_pct=e["trail_give_pct"],
            trail_floor_pct=e["trail_floor_pct"],
            stall_green_age_min=e["stall_green_age_min"],
            stall_green_min_pct=e["stall_green_min_pct"],
            flat_stall_no_new_high_min=e["flat_stall_no_new_high_min"],
            flat_stall_lo=e["flat_stall_lo"],
            flat_stall_hi=e["flat_stall_hi"],
            revert_to_mean=False,
        )


# ── T1 — regime-gated arm of trend_breakout (adaptive-slate §2 T1) ───
def default_spec_regime_gated() -> StrategySpec:
    """Same gates as trend_breakout, but only fires in a clean point-in-time
    TREND-UP regime. The ONE new question (quant-gate review §2 T1): does
    regime-gating flip the -0.47%-net live baseline from -EV to >=0?"""
    s = default_spec()
    s.strategy_id = "trend_breakout_regime"
    s.universe = ["BTC", "ETH", "SOL"]
    s.entry_gates = dict(s.entry_gates)
    # regime gate is applied in should_enter; thresholds are frozen-from-prior
    # (compute_regime_1h's ADX/CHOP cutoffs) and declared frozen in the pre-reg
    # so they do NOT add to n_trials.
    return s


class TrendBreakoutRegimeGated(TrendBreakout):
    """trend_breakout that fires ONLY when the instrument's 1h regime is TREND-UP
    and BTC's 1h regime is not TREND-DOWN. Everything else is identical to the
    base — so the A/B isolates the regime gate, nothing else.

    The regime labels MUST be supplied point-in-time (computed from bars up to
    and including the decision bar) by the caller; this rule only reads them."""

    def __init__(self, spec: StrategySpec | None = None) -> None:
        super().__init__(spec or default_spec_regime_gated())

    def should_enter(self, features: dict[str, object]) -> Signal | None:
        reg = str(features.get("regime_1h", "")).upper().replace("_", "-")
        btc = str(features.get("btc_regime_1h", "")).upper().replace("_", "-")
        # regime gate FIRST — fail closed unless we explicitly see TREND-UP
        if reg != "TREND-UP":
            return None
        if btc == "TREND-DOWN":
            return None
        sig = super().should_enter(features)
        if sig is not None:
            sig.reason = f"[regime-gated TREND-UP btc={btc}] " + sig.reason
        return sig
