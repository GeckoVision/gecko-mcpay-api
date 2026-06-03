"""Gate truth-table tests for the shared strategies/ spine (Sprint 31).

Light, pure tests — no network, no LLM, no candle fetch. Each test asserts a
single gate flips the decision, so a regression in any gate is caught in
isolation. These rules are consumed by BOTH the backtest and the live bot, so
this file is the contract for both.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from strategies import MeanReversion, TrendBreakout, load_strategy  # noqa: E402
from strategies.spec import StrategySpec  # noqa: E402


# ── Strategy A — trend_breakout ──────────────────────────────────────
def _trend_pass() -> dict:
    """A features dict that PASSES every Strategy A gate."""
    return {
        "close": 101.0,
        "ema50": 100.0,
        "adx": 28.0,
        "rsi": 60.0,
        "mfi": 60.0,
        "breakout_pct": 0.8,
        "donchian_break": True,
    }


def test_trend_fires_when_all_gates_pass():
    sig = TrendBreakout().should_enter(_trend_pass())
    assert sig is not None and sig.side == "long"


def test_trend_blocks_low_adx():
    f = _trend_pass()
    f["adx"] = 18.0  # below 22 — chop, the orthogonality gate
    assert TrendBreakout().should_enter(f) is None


def test_trend_blocks_small_breakout():
    f = _trend_pass()
    f["breakout_pct"] = 0.3  # below 0.5% magnitude
    assert TrendBreakout().should_enter(f) is None


def test_trend_blocks_below_ema50():
    f = _trend_pass()
    f["close"] = 99.0  # below ema50
    assert TrendBreakout().should_enter(f) is None


def test_trend_blocks_blowoff_rsi():
    f = _trend_pass()
    f["rsi"] = 80.0  # >= 75 exhaustion
    assert TrendBreakout().should_enter(f) is None


def test_trend_blocks_mfi_overbought_s30():
    f = _trend_pass()
    f["mfi"] = 72.0  # >= 70 — the S30 stall-bleed band, excluded
    assert TrendBreakout().should_enter(f) is None


def test_trend_blocks_mfi_too_low():
    f = _trend_pass()
    f["mfi"] = 45.0  # < 50, no inflow confirm
    assert TrendBreakout().should_enter(f) is None


def test_trend_fails_closed_on_missing_feature():
    f = _trend_pass()
    del f["adx"]
    assert TrendBreakout().should_enter(f) is None


def test_trend_churn_gate_blocks_noisy_breakout():
    # a breakout that passes every other gate but is born in churn → declined
    f = _trend_pass()
    f["churn_ratio"] = 9.0  # >= default churn_max 4.0 (bot-noise regime)
    assert TrendBreakout().should_enter(f) is None


def test_trend_churn_gate_allows_clean_breakout():
    f = _trend_pass()
    f["churn_ratio"] = 1.5  # clean directional move
    assert TrendBreakout().should_enter(f) is not None


def test_trend_churn_gate_fails_open_when_absent():
    # no churn feature (older data path) → gate must not block
    f = _trend_pass()
    f.pop("churn_ratio", None)
    assert TrendBreakout().should_enter(f) is not None


def test_trend_churn_gate_off_when_none():
    spec = TrendBreakout().spec
    spec.entry_gates["churn_max"] = None  # backtest A/B baseline
    f = _trend_pass()
    f["churn_ratio"] = 99.0
    assert load_strategy("trend_breakout", spec).should_enter(f) is not None


# ── Strategy B — mean_reversion ──────────────────────────────────────
def _meanrev_pass() -> dict:
    """A features dict that PASSES every Strategy B gate."""
    return {
        "close": 98.0,
        "bb_lower": 99.0,  # close below lower band
        "bb_mid": 101.0,
        "rsi": 25.0,
        "adx": 18.0,  # ranging
        "mfi": 20.0,
        "ema200": 95.0,
        "btc_regime_1h": "CHOP",
    }


def test_meanrev_fires_when_all_gates_pass():
    sig = MeanReversion().should_enter(_meanrev_pass())
    assert sig is not None and sig.side == "long"


def test_meanrev_blocks_not_stretched():
    f = _meanrev_pass()
    f["close"] = 100.0  # above bb_lower
    assert MeanReversion().should_enter(f) is None


def test_meanrev_blocks_not_oversold():
    f = _meanrev_pass()
    f["rsi"] = 40.0  # > 30
    assert MeanReversion().should_enter(f) is None


def test_meanrev_blocks_downtrend_when_below_ema200():
    f = _meanrev_pass()
    f["adx"] = 30.0  # trending …
    f["ema200"] = 99.0  # … and below the long trend → falling knife, block
    assert MeanReversion().should_enter(f) is None


def test_meanrev_allows_strong_adx_if_above_ema200():
    f = _meanrev_pass()
    f["adx"] = 30.0  # trending …
    f["ema200"] = 90.0  # … but above EMA200 (uptrend dip) → allowed
    assert MeanReversion().should_enter(f) is not None


def test_meanrev_blocks_btc_trend_down():
    f = _meanrev_pass()
    f["btc_regime_1h"] = "TREND-DOWN"  # don't catch dips while the market dumps
    assert MeanReversion().should_enter(f) is None


def test_meanrev_blocks_high_mfi():
    f = _meanrev_pass()
    f["mfi"] = 40.0  # > 25, sellers not exhausted
    assert MeanReversion().should_enter(f) is None


# ── Orthogonality: A and B fire in near-disjoint regimes ─────────────
def test_strategies_are_orthogonal_on_adx():
    # A needs ADX>=22; B (without an EMA200 rescue) needs ADX<25. A high-ADX
    # breakout tape that fires A must NOT fire B, and vice-versa.
    trend_tape = _trend_pass()  # adx 28, new high
    assert TrendBreakout().should_enter(trend_tape) is not None
    # same tape can't be a mean-reversion entry (not stretched below band)
    assert MeanReversion().should_enter(trend_tape) is None


# ── Registry + spec round-trip ───────────────────────────────────────
def test_load_strategy_resolves_all_ids():
    assert isinstance(load_strategy("trend_breakout"), TrendBreakout)
    assert isinstance(load_strategy("mean_reversion"), MeanReversion)
    assert load_strategy("jto_breakout").spec.strategy_id == "jto_breakout"


def test_load_strategy_unknown_raises():
    try:
        load_strategy("nope")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown strategy_id")


def test_spec_json_roundtrip():
    s = TrendBreakout().spec
    s2 = StrategySpec.from_json(s.to_json())
    assert s2.strategy_id == s.strategy_id
    assert s2.entry_gates == s.entry_gates
    assert s2.exit == s.exit


def test_spec_override_threads_into_gates():
    # the backtest sweep overrides thresholds via a custom spec
    spec = TrendBreakout().spec
    spec.entry_gates["adx_min"] = 40.0
    strat = load_strategy("trend_breakout", spec)
    f = _trend_pass()  # adx 28 < 40 now
    assert strat.should_enter(f) is None


def test_exit_policies_differ_by_strategy():
    a = TrendBreakout().exit_policy()
    b = MeanReversion().exit_policy()
    assert a.use_trailing is True and b.use_trailing is False
    assert b.revert_to_mean is True
    assert a.tp_pct == 1.0 and b.tp_pct == 0.8
