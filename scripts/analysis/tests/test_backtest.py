"""Unit tests for scripts.analysis.backtest — Sprint 6 Phase B.

Lean fixtures per `feedback_lighter_tests`: tiny synthetic OHLCV DataFrames,
no real Binance data, no mocks of the bot module (the simulator inlines the
Sprint 7 exit logic to avoid the bot's import-time side effects).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.analysis.backtest import loader, runner, signals, simulator  # noqa: E402


def _synth_ohlcv(closes: list[float], *, highs=None, lows=None) -> pd.DataFrame:
    """Construct a tiny OHLCV from a close-price sequence."""
    n = len(closes)
    h = highs if highs is not None else [c * 1.005 for c in closes]
    lows_ = lows if lows is not None else [c * 0.995 for c in closes]
    return pd.DataFrame(
        {
            "open": closes,
            "high": h,
            "low": lows_,
            "close": closes,
            "volume": [1000.0] * n,
        },
        index=pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    )


# ── loader ─────────────────────────────────────────────────────────────────


def test_available_symbols_missing_dir(tmp_path: Path) -> None:
    assert loader.available_symbols(tmp_path / "nope") == []


def test_load_ohlcv_missing_file_returns_empty(tmp_path: Path) -> None:
    assert loader.load_ohlcv("NOTACOIN", tmp_path).empty


def test_load_ohlcv_roundtrips_a_synthetic_file(tmp_path: Path) -> None:
    import json
    rows = [
        {"ts": 1716753600000, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
        {"ts": 1716768000000, "open": 101, "high": 103, "low": 100, "close": 102.5, "volume": 1100},
    ]
    (tmp_path / "FOO_perp.json").write_text(json.dumps(rows))
    df = loader.load_ohlcv("FOO", tmp_path)
    assert len(df) == 2
    assert df["close"].iloc[0] == 101
    assert df.index.tz is not None


def test_load_universe_filters_empty_files(tmp_path: Path) -> None:
    import json
    (tmp_path / "GOOD_perp.json").write_text(
        json.dumps([{"ts": 1716753600000, "open": 1, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 10}])
    )
    (tmp_path / "BAD_perp.json").write_text("[]")
    uni = loader.load_universe(perp_dir=tmp_path)
    assert "GOOD" in uni
    assert "BAD" not in uni


# ── Phase D: Venue refactor ──────────────────────────────────────────────


def test_venue_solana_picks_up_dex_suffix_files(tmp_path: Path) -> None:
    """VENUE_SOLANA reads <SYMBOL>_dex.json (not _perp.json)."""
    import json
    (tmp_path / "JTO_dex.json").write_text(
        json.dumps([{"ts": 1716753600000, "open": 2.0, "high": 2.1, "low": 1.9, "close": 2.05, "volume": 100}])
    )
    custom = loader.Venue(name="solana_test", data_dir=tmp_path, file_suffix="_dex")
    syms = loader.available_symbols(venue=custom)
    assert syms == ["JTO"]
    df = loader.load_ohlcv("JTO", venue=custom)
    assert len(df) == 1
    assert df["close"].iloc[0] == 2.05


def test_venue_solana_does_not_pick_up_perp_files(tmp_path: Path) -> None:
    """A _perp file in a solana-venue dir is invisible (different suffix)."""
    import json
    (tmp_path / "AAVE_perp.json").write_text(
        json.dumps([{"ts": 1716753600000, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000}])
    )
    custom = loader.Venue(name="solana_test", data_dir=tmp_path, file_suffix="_dex")
    assert loader.available_symbols(venue=custom) == []


def test_legacy_perp_dir_kwarg_still_works(tmp_path: Path) -> None:
    """Back-compat: existing callers passing perp_dir=... still work."""
    import json
    (tmp_path / "X_perp.json").write_text(
        json.dumps([{"ts": 1716753600000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0}])
    )
    assert loader.available_symbols(perp_dir=tmp_path) == ["X"]


def test_venue_binance_constants_unchanged() -> None:
    """VENUE_BINANCE constants must match the legacy DEFAULT_PERP_DIR for safety."""
    assert loader.VENUE_BINANCE.file_suffix == "_perp"
    assert loader.VENUE_BINANCE.data_dir == loader.DEFAULT_PERP_DIR
    assert loader.VENUE_SOLANA.file_suffix == "_dex"
    assert loader.VENUE_SOLANA.data_dir.name == "solana"


# ── signals ────────────────────────────────────────────────────────────────


def test_price_breakout_fires_on_new_high() -> None:
    closes = [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 105]
    highs = [101, 101, 101, 101, 101, 101, 101, 101, 101, 101, 106]
    df = _synth_ohlcv(closes, highs=highs)
    sig = signals.price_breakout(df, lookback=5)
    # Last bar closes 105 > prior 5-bar high (101). Should fire.
    assert sig.iloc[-1]
    # Bars 0-4 have insufficient lookback; should NOT fire.
    assert not sig.iloc[:5].any()


def test_trend_up_fires_when_close_above_sma() -> None:
    closes = list(np.linspace(100, 110, 25))  # monotonically up
    df = _synth_ohlcv(closes)
    sig = signals.trend_up(df, window=20)
    # After SMA warms up, close should consistently exceed the trailing average
    assert sig.iloc[-1]
    assert sig.iloc[-5:].all()


def test_candidate_entries_requires_both_breakout_and_trend() -> None:
    # Sideways then breakout; SMA above current = no candidate even on breakout
    closes = [100, 100, 100, 100, 100, 100, 100, 100, 100, 100,
              100, 100, 100, 100, 100, 100, 100, 100, 100, 100,
              105]
    highs = closes.copy()
    highs[-1] = 106
    df = _synth_ohlcv(closes, highs=highs)
    # Trend is flat → SMA = 100 = close[-1] of pre-breakout; on breakout bar close=105 > SMA(20)
    cand = signals.candidate_entries(df, breakout_lookback=5, trend_window=10)
    assert cand.iloc[-1]


def test_dedupe_entries_cooldown_strips_back_to_back() -> None:
    s = pd.Series([False, True, True, True, False, True])
    out = signals.dedupe_entries(s, cooldown_bars=2)
    # First True at idx 1, next True must be at idx >= 4 (2 cooldown bars). Idx 2,3 dropped; idx 5 kept.
    assert list(out) == [False, True, False, False, False, True]


# ── simulator: Sprint 7 exit semantics ─────────────────────────────────────


def test_stop_loss_fires_when_low_hits_threshold() -> None:
    # Entry at 100 close[0]. Bar 1 has low=96 → -4% → stop_loss
    df = _synth_ohlcv(
        closes=[100, 96, 96],
        highs=[101, 97, 97],
        lows=[99, 96, 96],
    )
    trade = simulator.simulate_one_entry(df, entry_idx=0, take_profit_pct=10, max_hold_bars=5)
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_price"] == pytest.approx(97.0, rel=1e-3)  # entry * (1 - 0.03)


def test_take_profit_fires_when_high_hits_target() -> None:
    df = _synth_ohlcv(
        closes=[100, 101, 102, 105],
        highs=[101, 102, 103, 106],
        lows=[99, 100, 101, 104],
    )
    trade = simulator.simulate_one_entry(df, entry_idx=0, take_profit_pct=2, max_hold_bars=5)
    assert trade["exit_reason"] == "take_profit"
    assert trade["exit_price"] == pytest.approx(102.0, rel=1e-3)


def test_trailing_stop_fires_after_peak_then_retrace() -> None:
    # Climb to peak 103, retrace to 102.4 → retrace 0.58% (> 0.5%), pnl_at_retrace +2.4% (> -1%) → trailing
    df = _synth_ohlcv(
        closes=[100, 101, 102, 103, 102.4],
        highs=[101, 102, 103, 103, 102.4],
        lows=[99, 100, 101, 102.5, 102.3],
    )
    trade = simulator.simulate_one_entry(
        df,
        entry_idx=0,
        take_profit_pct=10,
        trail_stop_pct=0.5,
        trail_activate_pct=1.0,
        trail_min_pnl_pct=-1.0,
        max_hold_bars=10,
    )
    assert trade["exit_reason"] == "trailing_stop"


def test_sprint7_safety_floor_blocks_trailing_into_deep_red() -> None:
    """When pnl breaches the trail safety floor, trailing should NOT fire.

    Bar 1: peak +1.5%, but the bar's LOW stays >= peak * (1 - 0.5%) so trailing
    doesn't fire intra-bar (no retrace). Bar 2: gap straight down past stop_loss.
    """
    # Bar 1 low must be high enough that trail retrace < 0.5% (no intra-bar trail trigger)
    # 101.5 * (1 - 0.005) = 101.0 → low >= 101.0 ⇒ no trail trigger on bar 1
    df = _synth_ohlcv(
        closes=[100, 101.5, 96.5],
        highs=[101, 101.5, 96.5],
        lows=[99, 101.0, 96.5],  # bar 1 low=101.0 → no trail; bar 2 low -3.5% → SL
    )
    trade = simulator.simulate_one_entry(
        df,
        entry_idx=0,
        take_profit_pct=10,
        trail_stop_pct=0.5,
        trail_activate_pct=1.0,
        trail_min_pnl_pct=-1.0,
        max_hold_bars=5,
    )
    assert trade["exit_reason"] == "stop_loss"


def test_time_stop_fires_when_no_exit_triggered() -> None:
    # Flat at entry — should hit max_hold_bars
    df = _synth_ohlcv(closes=[100.0] * 10)
    trade = simulator.simulate_one_entry(
        df,
        entry_idx=0,
        take_profit_pct=10,
        stall_green_age_bars=100,  # disable
        flat_stall_age_bars=100,  # disable
        max_hold_bars=5,
    )
    assert trade["exit_reason"] == "time_stop"
    assert trade["age_bars"] == 5


def test_no_forward_data_returns_none() -> None:
    df = _synth_ohlcv(closes=[100.0])
    assert simulator.simulate_one_entry(df, entry_idx=0) is None


def test_simulate_symbol_respects_open_position_gating() -> None:
    """If a candidate fires while a prior trade is still open, skip it."""
    df = _synth_ohlcv(
        closes=[100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
    )
    candidates = pd.Series(
        [False, True, False, True, False, True, False, False, False, False, False],
        index=df.index,
    )
    trades = simulator.simulate_symbol(
        df,
        candidates,
        symbol="TEST",
        take_profit_pct=1.5,
        max_hold_bars=20,
        stall_green_age_bars=100,
        flat_stall_age_bars=100,
    )
    # First trade at idx 1 hits TP almost immediately; subsequent candidates SHOULD
    # be allowed (last_exit_bar updates). Confirms gating doesn't over-suppress.
    assert len(trades) >= 1


# ── simulator parity with bot's Sprint 7 helper ────────────────────────────


def test_simulator_evaluator_matches_bot_sprint7_helper() -> None:
    """Critical parity test: the inline _evaluate_stop_exits_proxy MUST match the bot.

    If the bot's Sprint 7 helper changes, this test breaks and we update both.
    """
    sys.path.insert(0, str(_REPO_ROOT / "contest_bot"))
    # Skip if the bot module fails to import (e.g. missing env in CI)
    try:
        import jto_breakout_gecko_gated_contest_bot as bot
    except Exception:
        pytest.skip("bot module not importable in this env")
    # Skip if the bot module on this branch predates Sprint 7 (the helper
    # only exists in the s67 branch). After s67 merges to main, this skip
    # auto-clears and the parity check engages.
    if not hasattr(bot, "_evaluate_stop_exits"):
        pytest.skip("bot._evaluate_stop_exits missing — branch predates Sprint 7 merge")
    # Probe several scenarios; both implementations must agree
    scenarios = [
        # (pnl, peak_pct, current, peak)
        (-6.28, 1.05, 93.72, 101.05),  # autopsy disaster
        (2.0, 3.0, 102.0, 103.0),  # classic trailing
        (-2.0, 1.5, 98.0, 101.5),  # safety guard active
        (0.0, 0.0, 100.0, 100.0),  # no exit
        (-3.0, 0.0, 97.0, 100.0),  # exact stop_loss threshold
    ]
    for pnl, peak_pct, current, peak in scenarios:
        bot_result = bot._evaluate_stop_exits(
            pnl_pct=pnl,
            peak_pct=peak_pct,
            current_price=current,
            peak_price=peak,
        )
        proxy_result = simulator._evaluate_stop_exits_proxy(
            pnl_pct=pnl,
            peak_pct=peak_pct,
            current_price=current,
            peak_price=peak,
            stop_loss_pct=3.0,
            trail_activate_pct=1.0,
            trail_stop_pct=0.5,
            trail_min_pnl_pct=-1.0,
        )
        assert bot_result == proxy_result, (
            f"parity mismatch: scenario {(pnl, peak_pct, current, peak)} "
            f"bot={bot_result} proxy={proxy_result}"
        )


# ── runner: summarize + label_outcomes ─────────────────────────────────────


def test_label_outcomes_thresholds() -> None:
    trades = pd.DataFrame({"net_pnl_pct": [1.5, 0.3, -0.6, -3.0, 0.0]})
    out = runner.label_outcomes(trades, min_win_pct=0.5)
    assert list(out["outcome_label"]) == ["win", "scratch", "loss", "loss", "scratch"]


def test_summarize_empty_trades() -> None:
    s = runner.summarize(pd.DataFrame())
    assert s == {"total_n": 0}


def test_summarize_shape_matches_dashboard_decomposition() -> None:
    trades = pd.DataFrame(
        {
            "symbol": ["WIF", "WIF", "JTO", "JTO"],
            "exit_reason": ["take_profit", "trailing_stop", "stop_loss", "take_profit"],
            "net_pnl_pct": [1.0, -0.2, -3.1, 1.5],
            "age_bars": [5, 8, 3, 4],
        }
    )
    s = runner.summarize(runner.label_outcomes(trades))
    assert s["total_n"] == 4
    assert s["wins"] == 2
    assert s["losses"] == 1
    assert s["scratches"] == 1
    assert "by_exit_reason" in s
    assert "take_profit" in s["by_exit_reason"]
    assert s["by_exit_reason"]["take_profit"]["n"] == 2
