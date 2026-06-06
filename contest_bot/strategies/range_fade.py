"""R1 — `range_fade` (disciplined mean-reversion with a fee-width filter).

A refinement of `mean_reversion` (HAVE). The dead majors-5m mean-revert null
fired on tight ranges where the reversion target could not clear the 0.20%
round-trip + slippage. R1 adds the ONE structural difference: a hard
`band_width_pct_min` gate that REFUSES any range narrower than ~2x round-trip
cost. That is the only new hypothesis being tested: "does refusing tight ranges
rescue mean-reversion on majors, or not?"

Entry (all must hold) — adaptive-slate §2 R1:
  Stretch          close < lower Bollinger(20, 2sigma)        (have)
  Oversold         RSI(14) <= 30                               (have)
  Exhaustion       MFI(14) <= 25                               (have)
  No downtrend     ADX(14) < 25  OR  close > EMA(200)          (have)
  BTC overlay      BTC 1h regime not TREND-DOWN                (have)
  Fee-width filter (bb_upper - bb_lower) / bb_mid * 100 >= band_width_pct_min   ← NEW

The fee-width filter is THE candidate. (bb_upper-bb_lower)/bb_mid is the full
Bollinger band width as a percent of the mid. The reversion target is bb_mid;
from a touch of bb_lower the expected favorable excursion is ~half the band
width. Requiring full-band-width >= ~1.2% means the half-band reversion target
(~0.6%) clears the 0.20% round-trip with margin. Narrower ranges are refused.

Exit is fast-or-wrong: revert-to-mean (close >= bb_mid) OR +0.8%, tight -0.5%
stop, 2h time stop, NO trailing. Fixed fraction, no pyramiding.
"""

from __future__ import annotations

from .base import ExitPolicy, Signal, _f
from .spec import StrategySpec


def default_spec() -> StrategySpec:
    return StrategySpec(
        strategy_id="range_fade",
        version="v0",
        universe=["BTC", "ETH", "SOL", "XRP"],
        timeframe="5m",
        venue="okx_spot",
        entry_gates={
            "bb_n": 20,
            "bb_k": 2.0,
            "rsi_max": 30.0,
            "adx_max": 25.0,
            "ema_trend_filter": 200,
            "mfi_max": 25.0,
            # NEW vs mean_reversion: the fee-width filter. Full Bollinger band
            # width as a % of mid must exceed this floor or the trade is refused.
            # 1.2% full-band -> ~0.6% half-band reversion target -> clears the
            # 0.20% round-trip + slippage with margin. This is the whole R1 bet.
            "band_width_pct_min": 1.2,
        },
        exit={
            "tp_pct": 0.8,
            "sl_pct": 0.5,
            "time_stop_min": 120,
            "revert_to_mean": True,  # close >= bb_mid books the reversion
        },
    )


class RangeFade:
    def __init__(self, spec: StrategySpec | None = None) -> None:
        self.spec = spec or default_spec()

    def should_enter(self, features: dict[str, object]) -> Signal | None:
        g = self.spec.entry_gates
        close = _f(features, "close") or _f(features, "price")
        rsi = _f(features, "rsi")
        mfi = _f(features, "mfi")
        adx = _f(features, "adx")
        bb_lower = _f(features, "bb_lower")
        bb_mid = _f(features, "bb_mid")
        bb_upper = _f(features, "bb_upper")
        ema200 = _f(features, "ema200")  # may be None until warm-up
        btc_regime_1h = features.get("btc_regime_1h")

        # required (ema200 NOT required — the ADX clause covers the gate; bb_upper
        # IS required here because the fee-width filter cannot fail open).
        if (
            close is None
            or rsi is None
            or mfi is None
            or adx is None
            or bb_lower is None
            or bb_mid is None
            or bb_upper is None
            or bb_mid <= 0
        ):
            return None

        # ── THE NEW GATE: fee-width filter (fail CLOSED) ──────────────
        # Refuse ranges too tight for the reversion to clear fees.
        band_width_pct = (bb_upper - bb_lower) / bb_mid * 100.0
        floor = float(g.get("band_width_pct_min", 0.0))
        if band_width_pct < floor:
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
        # fail CLOSED only when we explicitly know TREND-DOWN; unknown -> allow.
        if str(btc_regime_1h).upper().replace("_", "-") == "TREND-DOWN":
            return None

        return Signal(
            side="long",
            reason=(
                f"range_fade: bw={band_width_pct:.2f}%>={floor:.1f}% "
                f"close<bb_lower rsi={rsi:.0f}<={g['rsi_max']:.0f} "
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
