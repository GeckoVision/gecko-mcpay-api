"""S42 — Kamino Multiply economics + yield-safety monitor. Pure, no network."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import pytest  # noqa: E402
from kamino import monitor as mon  # noqa: E402
from kamino.multiply import (  # noqa: E402
    LeverageStrategy,
    leverage_to_clear,
    time_to_target,
)


def _strat(yld, bor, lev, *, corr=True, max_ltv=0.90, liq=0.93, src="lst_staking"):
    return LeverageStrategy("t", yld, bor, lev, max_ltv, liq, corr, src)


# ── economics ───────────────────────────────────────────────────────────
def test_net_apy_matches_kamino_8x_example():
    # Kamino's own doc: 7% yield, 6% borrow, 8x → 14% net
    s = _strat(0.07, 0.06, 8.0)
    assert round(s.net_apy, 4) == 0.14


def test_operating_ltv_8x_is_87_5pct():
    assert round(_strat(0.07, 0.06, 8.0).operating_ltv, 4) == 0.875


def test_spread_inverted_flag():
    assert _strat(0.0632, 0.0808, 4.0).spread_inverted is True
    assert _strat(0.07, 0.06, 4.0).spread_inverted is False


def test_liquidation_drop_pct_founder_idealized():
    # liq_ltv=1.0 reproduces the founder's mental model: 10x→10%, 5x→20%
    assert round(_strat(0.2, 0.06, 10.0, corr=False, liq=1.0).liquidation_drop_pct, 4) == 0.10
    assert round(_strat(0.2, 0.06, 5.0, corr=False, liq=1.0).liquidation_drop_pct, 4) == 0.20


def test_liquidation_drop_tighter_with_real_haircut():
    # real liq_ltv 0.93 makes 10x buffer ~3%, not 10% — tighter than naive 1/L
    assert _strat(0.2, 0.06, 10.0, corr=False, liq=0.93).liquidation_drop_pct < 0.05


def test_leverage_below_one_rejected():
    with pytest.raises(ValueError):
        _strat(0.07, 0.06, 0.5)


def test_time_to_target_100_on_1000():
    # 10% APY → ~1 year to +$100 on $1000
    t = time_to_target(1000.0, 0.10, 100.0)
    assert t is not None and 0.9 < t < 1.1


def test_time_to_target_none_when_nonpositive():
    assert time_to_target(1000.0, 0.0, 100.0) is None
    assert time_to_target(1000.0, -0.05, 100.0) is None


def test_leverage_to_clear_solves_hurdle():
    # 7% yield, 6% borrow, spread 1% → to hit 12% net need L=1+(0.12-0.07)/0.01=6x
    lev = leverage_to_clear(_strat(0.07, 0.06, 1.0), 0.12, max_leverage=10.0)
    assert lev is not None and round(lev, 1) == 6.0


def test_leverage_to_clear_none_when_spread_nonpositive():
    assert leverage_to_clear(_strat(0.06, 0.08, 1.0), 0.12) is None


# ── monitor ─────────────────────────────────────────────────────────────
def test_monitor_exits_on_inverted_spread():
    v = mon.evaluate(_strat(0.0632, 0.0808, 4.0))
    assert v.action == mon.EXIT and "inverted" in v.reason


def test_monitor_rotates_below_hurdle_on_correlated():
    # 10% net < 12% fiat hurdle, correlated → ROTATE to a clearing leverage
    v = mon.evaluate(_strat(0.07, 0.06, 4.0), hurdle=mon.FIAT_CDB_BR)
    assert v.action == mon.ROTATE and v.suggested_leverage is not None


def test_monitor_holds_when_clears_hurdle_crypto_only():
    # 10% net ≥ 5.5% crypto-only hurdle → HOLD
    v = mon.evaluate(_strat(0.07, 0.06, 4.0), hurdle=mon.CRYPTO_ONLY)
    assert v.action == mon.HOLD and v.clears_hurdle


def test_monitor_exits_when_predicted_downside_exceeds_buffer():
    # volatile 10x, ~3% buffer, Oracle predicts 12% → EXIT
    s = _strat(0.2, 0.06, 10.0, corr=False, liq=0.93)
    v = mon.evaluate(s, predicted_drawdown_pct=0.12)
    assert v.action == mon.EXIT and "downside" in v.reason


def test_monitor_deleverages_when_predicted_near_buffer():
    # volatile 5x, ~14% buffer, Oracle predicts 12% (>60% of buffer) → DELEVERAGE
    s = _strat(0.2, 0.06, 5.0, corr=False, liq=0.93)
    v = mon.evaluate(s, predicted_drawdown_pct=0.12)
    assert v.action == mon.DELEVERAGE


def test_monitor_holds_volatile_when_predicted_safe():
    # volatile 3x, ~28% buffer, Oracle predicts 12%, net clears hurdle → HOLD
    s = _strat(0.2, 0.06, 3.0, corr=False, liq=0.93)
    v = mon.evaluate(s, predicted_drawdown_pct=0.12, hurdle=mon.FIAT_CDB_BR)
    assert v.action == mon.HOLD


def test_monitor_correlated_ignores_price_prediction():
    # correlated LST pair: a market drop doesn't liquidate, so prediction is moot here
    s = _strat(0.07, 0.06, 8.0, corr=True)  # clears crypto-only hurdle
    v = mon.evaluate(s, predicted_drawdown_pct=0.30, hurdle=mon.CRYPTO_ONLY)
    assert v.action == mon.HOLD


def test_hurdle_for_profile():
    assert mon.hurdle_for("crypto_only").apy == mon.CRYPTO_ONLY.apy
    assert mon.hurdle_for("balanced").apy == mon.FIAT_CDB_BR.apy
