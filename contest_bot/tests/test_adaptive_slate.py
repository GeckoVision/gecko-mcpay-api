"""Unit tests for the adaptive slate — range_fade, vol_target_sizer, the
regime-gated trend arm, and the switcher router.

Pure-function truth tables on synthetic features. No data, no network, no LLM.
Run: uv run pytest contest_bot/tests/test_adaptive_slate.py -p no:cacheprovider
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONTEST = os.path.join(_HERE, "..")
if _CONTEST not in sys.path:
    sys.path.insert(0, _CONTEST)

from strategies import load_strategy  # noqa: E402
from strategies.range_fade import RangeFade  # noqa: E402
from strategies.switcher import (  # noqa: E402
    FLAT,
    FLAT_YIELD,
    RANGE,
    TREND,
    HysteresisState,
    SwitchConfig,
    confirm_regime,
    select_strategy,
)
from strategies.trend import TrendBreakoutRegimeGated  # noqa: E402
from strategies.vol_target_sizer import (  # noqa: E402
    VolTargetConfig,
    realized_vol,
    sized_fraction,
    vol_target_multiplier,
)


# ── R1 range_fade ────────────────────────────────────────────────────
def _wide_range_oversold() -> dict:
    """A textbook fade: oversold, below lower band, WIDE band (clears fee floor)."""
    return {
        "close": 100.0,
        "bb_lower": 101.0,  # close < bb_lower (stretch)
        "bb_mid": 105.0,
        "bb_upper": 109.0,  # full width = (109-101)/105 = 7.6% -> clears 1.2
        "rsi": 25.0,
        "mfi": 20.0,
        "adx": 18.0,
        "ema200": 99.0,
        "btc_regime_1h": "CHOP",
    }


def test_range_fade_fires_on_wide_oversold_range():
    sig = RangeFade().should_enter(_wide_range_oversold())
    assert sig is not None
    assert sig.side == "long"
    assert "range_fade" in sig.reason


def test_range_fade_REFUSES_tight_range():
    """THE key gate: a tight range (band width below floor) must be refused even
    when every other condition is met. This is the whole R1 hypothesis."""
    f = _wide_range_oversold()
    f["bb_lower"] = 104.5
    f["bb_mid"] = 105.0
    f["bb_upper"] = 105.5  # full width = 1.0/105 = 0.95% < 1.2 floor
    f["close"] = 104.0  # still below the (tight) lower band
    assert RangeFade().should_enter(f) is None


def test_range_fade_band_width_boundary():
    f = _wide_range_oversold()
    # width comfortably above the 1.2% floor -> passes
    f["bb_mid"] = 100.0
    f["bb_lower"] = 99.0
    f["bb_upper"] = 101.5  # width = 2.5 -> 2.5% > 1.2 floor
    f["close"] = 98.5
    f["ema200"] = 98.0
    assert RangeFade().should_enter(f) is not None
    # width just below the floor -> refused
    f["bb_lower"] = 99.5
    f["bb_upper"] = 100.5  # width = 1.0 -> 1.0% < 1.2 floor
    f["close"] = 99.0
    assert RangeFade().should_enter(f) is None


def test_range_fade_refuses_btc_downtrend():
    f = _wide_range_oversold()
    f["btc_regime_1h"] = "TREND-DOWN"
    assert RangeFade().should_enter(f) is None


def test_range_fade_requires_bb_upper_fail_closed():
    f = _wide_range_oversold()
    del f["bb_upper"]
    # fee-width filter cannot fail open -> no entry without bb_upper
    assert RangeFade().should_enter(f) is None


def test_range_fade_registered():
    assert isinstance(load_strategy("range_fade"), RangeFade)


# ── V1 vol_target_sizer ──────────────────────────────────────────────
def test_realized_vol_basic():
    closes = [100.0, 101.0, 100.0, 101.0, 100.0] * 10
    rv = realized_vol(closes, 24)
    assert rv is not None and rv > 0


def test_realized_vol_insufficient():
    assert realized_vol([100.0, 101.0], 24) is None


def test_vol_multiplier_high_vol_shrinks():
    # realized > target -> multiplier < 1 (shrink)
    m = vol_target_multiplier(realized=0.02, target=0.01)
    assert m < 1.0
    assert m >= VolTargetConfig().clamp_lo


def test_vol_multiplier_calm_grows_capped():
    # realized << target -> multiplier capped at clamp_hi
    m = vol_target_multiplier(realized=0.001, target=0.01)
    assert m == VolTargetConfig().clamp_hi


def test_vol_multiplier_fails_open_to_1():
    assert vol_target_multiplier(None, 0.01) == 1.0
    assert vol_target_multiplier(0.01, None) == 1.0
    assert vol_target_multiplier(0.0, 0.01) == 1.0  # degenerate -> no halt


def test_sized_fraction_scales():
    assert sized_fraction(0.10, 0.01, 0.01) == 0.10  # equal vol -> unchanged
    assert sized_fraction(0.10, 0.02, 0.01) < 0.10  # high vol -> smaller


# ── T1 regime-gated trend arm ────────────────────────────────────────
def _breakout_feats() -> dict:
    return {
        "close": 110.0,
        "ema50": 105.0,
        "adx": 30.0,
        "rsi": 60.0,
        "mfi": 60.0,
        "breakout_pct": 0.8,
        "donchian_break": True,
        "churn_ratio": 1.5,
        "regime_1h": "TREND-UP",
        "btc_regime_1h": "TREND-UP",
    }


def test_regime_gated_fires_in_trend_up():
    sig = TrendBreakoutRegimeGated().should_enter(_breakout_feats())
    assert sig is not None
    assert "regime-gated TREND-UP" in sig.reason


def test_regime_gated_blocks_outside_trend_up():
    f = _breakout_feats()
    f["regime_1h"] = "CHOP"
    assert TrendBreakoutRegimeGated().should_enter(f) is None
    f["regime_1h"] = "TREND-DOWN"
    assert TrendBreakoutRegimeGated().should_enter(f) is None


def test_regime_gated_blocks_btc_downtrend():
    f = _breakout_feats()
    f["btc_regime_1h"] = "TREND-DOWN"
    assert TrendBreakoutRegimeGated().should_enter(f) is None


def test_regime_gated_still_requires_breakout():
    f = _breakout_feats()
    f["breakout_pct"] = 0.1  # below 0.5 magnitude floor
    f["donchian_break"] = False
    assert TrendBreakoutRegimeGated().should_enter(f) is None


def test_regime_gated_registered():
    assert isinstance(load_strategy("trend_breakout_regime"), TrendBreakoutRegimeGated)


# ── switcher: hysteresis ─────────────────────────────────────────────
def test_hysteresis_requires_two_reads():
    cfg = SwitchConfig(hysteresis_reads=2)
    st0 = HysteresisState(confirmed_label="CHOP")
    st1, sw1 = confirm_regime(st0, "TREND-UP", cfg)
    assert not sw1  # one read — not yet confirmed
    assert st1.confirmed_label == "CHOP"
    st2, sw2 = confirm_regime(st1, "TREND-UP", cfg)
    assert sw2  # second consecutive read -> switch
    assert st2.confirmed_label == "TREND-UP"


def test_hysteresis_resets_on_flip_back():
    cfg = SwitchConfig(hysteresis_reads=2)
    st0 = HysteresisState(confirmed_label="CHOP")
    st1, _ = confirm_regime(st0, "TREND-UP", cfg)  # pending TREND-UP count 1
    st2, sw = confirm_regime(st1, "CHOP", cfg)  # back to confirmed -> reset
    assert not sw
    assert st2.pending_label is None and st2.pending_count == 0


# ── switcher: routing + safety precedence ────────────────────────────
def _sel(**kw):
    base = dict(
        market_temp=0.1,
        risk_off=False,
        pegana_depeg=False,
        safety_blocked=False,
        confirmed_regime="CHOP",
        btc_regime="CHOP",
        has_open_position=False,
        current_active=None,
    )
    base.update(kw)
    return select_strategy(**base)


def test_safety_risk_off_wins_first():
    d = _sel(risk_off=True, confirmed_regime="TREND-UP")
    assert d.active == FLAT_YIELD and "risk_off" in d.reason


def test_safety_temp_threshold_triggers_yield():
    d = _sel(market_temp=-0.30, confirmed_regime="TREND-UP")
    assert d.active == FLAT_YIELD


def test_pegana_depeg_flat():
    d = _sel(pegana_depeg=True, confirmed_regime="TREND-UP")
    assert d.active == FLAT and "pegana" in d.reason


def test_safety_gate_flat():
    d = _sel(safety_blocked=True, confirmed_regime="TREND-UP")
    assert d.active == FLAT and "safety_gate" in d.reason


def test_route_trend_up():
    assert _sel(confirmed_regime="TREND-UP", btc_regime="TREND-UP").active == TREND


def test_route_chop_to_range():
    assert _sel(confirmed_regime="CHOP", market_temp=0.0).active == RANGE


def test_route_chop_cold_temp_flat():
    d = _sel(confirmed_regime="CHOP", market_temp=-0.10)
    assert d.active == FLAT


def test_route_trend_down_to_yield():
    assert _sel(confirmed_regime="TREND-DOWN").active == FLAT_YIELD
    assert _sel(confirmed_regime="TREND-UP", btc_regime="TREND-DOWN").active == FLAT_YIELD


def test_never_flip_with_open_position():
    d = _sel(confirmed_regime="TREND-UP", has_open_position=True, current_active=RANGE)
    assert d.active == RANGE and d.held is True


def test_open_position_does_not_override_safety():
    # safety still wins even with an open position
    d = _sel(risk_off=True, has_open_position=True, current_active=TREND)
    assert d.active == FLAT_YIELD
