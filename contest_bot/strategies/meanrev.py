"""Strategy B — `mean_reversion` (counter-trend bounce).

Fades over-extension back to the mean, but ONLY in a ranging or uptrending tape,
never in a downtrend (the falling-knife killer of mean-reversion). Long-only v0.

Entry (all must hold) — spec §2 Strategy B:
  Stretch          close < lower Bollinger(20, 2σ)
  Oversold         RSI(14) <= 30
  No downtrend     ADX(14) < 25  OR  close > EMA(200)        ← orthogonality gate
  Exhaustion       MFI <= 25
  BTC overlay      BTC 1h regime not TREND-DOWN  (don't catch dips while market dumps)

Exit is fast-or-wrong: revert-to-mean (close >= bb_mid) OR +0.8%, tight -0.5% stop,
2h time stop, NO trailing (book the snap-back).
"""

from __future__ import annotations

from .base import ExitPolicy, Signal, _f
from .spec import StrategySpec


def default_spec() -> StrategySpec:
    return StrategySpec(
        strategy_id="mean_reversion",
        version="v0",
        universe=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        timeframe="5m",
        venue="okx_spot",
        entry_gates={
            "bb_n": 20,
            "bb_k": 2.0,
            "rsi_max": 30.0,
            "adx_max": 25.0,
            "ema_trend_filter": 200,
            "mfi_max": 25.0,
        },
        exit={
            "tp_pct": 0.8,
            "sl_pct": 0.5,
            "time_stop_min": 120,
            "revert_to_mean": True,  # close >= bb_mid books the reversion
        },
    )


class MeanReversion:
    def __init__(self, spec: StrategySpec | None = None) -> None:
        self.spec = spec or default_spec()

    def should_enter(self, features: dict[str, object]) -> Signal | None:
        g = self.spec.entry_gates
        close = _f(features, "close") or _f(features, "price")
        rsi = _f(features, "rsi")
        mfi = _f(features, "mfi")
        adx = _f(features, "adx")
        bb_lower = _f(features, "bb_lower")
        ema200 = _f(features, "ema200")  # may be None until warm-up
        btc_regime_1h = features.get("btc_regime_1h")

        # required (ema200 NOT required — the ADX clause covers the gate)
        if close is None or rsi is None or mfi is None or adx is None or bb_lower is None:
            return None

        # stretch below the lower band
        if close >= bb_lower:
            return None
        if rsi > g["rsi_max"]:
            return None
        # no-downtrend: range (ADX<max) OR above the long trend (close>EMA200)
        above_long_trend = ema200 is not None and close > ema200
        if not (adx < g["adx_max"] or above_long_trend):
            return None
        if mfi > g["mfi_max"]:
            return None
        # market-wide overlay: don't fade a dip while BTC is trending DOWN on 1h.
        # fail CLOSED only when we explicitly know it's TREND-DOWN; unknown ⇒ allow
        # (the ADX/EMA + per-name gates already guard the falling-knife case).
        if str(btc_regime_1h).upper().replace("_", "-") == "TREND-DOWN":
            return None

        return Signal(
            side="long",
            reason=(
                f"mean_reversion: close<bb_lower rsi={rsi:.0f}<={g['rsi_max']:.0f} "
                f"mfi={mfi:.0f}<={g['mfi_max']:.0f} "
                f"no_downtrend(adx={adx:.1f}<{g['adx_max']:.0f} or close>ema200) "
                f"btc1h={btc_regime_1h}"
            ),
            features=dict(features),
        )

    def exit_policy(self) -> ExitPolicy:
        e = self.spec.exit
        return ExitPolicy(
            tp_pct=e["tp_pct"],
            sl_pct=e["sl_pct"],
            time_stop_min=e["time_stop_min"],
            use_trailing=False,
            revert_to_mean=e.get("revert_to_mean", True),
        )
