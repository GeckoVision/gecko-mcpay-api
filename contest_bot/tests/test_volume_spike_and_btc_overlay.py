"""Tests for the volume_spike entry primitive + btc_overlay poll filter.

Light fakes only. The bot module is imported with ``OPENROUTER_API_KEY``
unset so the local panel is None; the Gecko gate is stubbed at the
instance level so no HTTP is involved.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    if "jto_breakout_gecko_gated_contest_bot" in sys.modules:
        del sys.modules["jto_breakout_gecko_gated_contest_bot"]
    import jto_breakout_gecko_gated_contest_bot as m

    m.positions.clear()
    m.signal_feed.clear()
    m._LAST_SNAPSHOTS.clear()
    m._LAST_SIGNAL_CHECK.clear()
    m._BTC_SNAPSHOT.clear()
    m._BTC_SNAPSHOT_TICK_ID = -1
    m._BTC_CURRENT_TICK_ID = 0
    m.daily_trades = 0
    m.consec_losses = 0
    m.total_spent_usd = 0.0
    m._LOCAL_PANEL = None

    class _OkDecision:
        allow = True
        shadow_mode = False
        would_have_blocked = False
        verdict = "buy"
        confidence = 0.9
        key_drivers: tuple[str, ...] = ()
        citations_count = 0
        cached = False
        error = None
        decision_id = "stub"

    async def _check_entry(instrument: str, market_state: dict) -> Any:
        return _OkDecision()

    m._GATE.check_entry = _check_entry  # type: ignore[assignment]
    m._BREAKER.check = lambda: (False, "")  # type: ignore[assignment]
    m._BREAKER.record_pnl_delta = lambda x: None  # type: ignore[assignment]

    monkeypatch.setattr(m, "passes_safety", lambda token: (True, []))
    return m


# ── helpers ──────────────────────────────────────────────────────────


def _flat_candles(price: float, vol: float, n: int = 30) -> list[dict]:
    return [
        {"ts": i, "open": price, "high": price, "low": price, "close": price, "volume": vol}
        for i in range(n)
    ]


def _spike_candles(base_vol: float, spike_vol: float, price: float = 1.0) -> list[dict]:
    bars = _flat_candles(price, base_vol, n=29)
    bars.append(
        {"ts": 29, "open": price, "high": price, "low": price, "close": price, "volume": spike_vol}
    )
    return bars


def _btc_candles_above_ma() -> list[dict]:
    # 20 closes ramping up; final close > mean of last 20.
    closes = [100.0 + i * 0.5 for i in range(24)]  # 100, 100.5 ... 111.5
    return [
        {"ts": i, "open": c, "high": c, "low": c, "close": c, "volume": 1.0}
        for i, c in enumerate(closes)
    ]


def _btc_candles_below_ma() -> list[dict]:
    closes = [100.0 - i * 0.5 for i in range(24)]  # descending
    return [
        {"ts": i, "open": c, "high": c, "low": c, "close": c, "volume": 1.0}
        for i, c in enumerate(closes)
    ]


def _install_oc_for_btc(
    bot_module,
    monkeypatch,
    btc_candles: list[dict] | Exception | None,
    token_candles: dict[str, list[dict]] | None = None,
    prices: dict[str, float] | None = None,
) -> MagicMock:
    """Mock the bot's `oc` with a router that returns BTC candles or per-token candles.

    If ``btc_candles`` is an Exception subclass instance, get_candles raises it
    when called with the BTC mint.
    """
    token_candles = token_candles or {}
    prices = prices or {}
    btc_mint = bot_module.BTC_WBTC_MINT

    def _get_candles(mint, bar, limit):
        if mint == btc_mint:
            if isinstance(btc_candles, Exception):
                raise btc_candles
            return btc_candles or []
        return token_candles.get(mint, [])

    fake = MagicMock()
    fake.get_candles = MagicMock(side_effect=_get_candles)
    fake.get_price_info = MagicMock(
        side_effect=lambda mint: {"data": {"price": prices.get(mint, 0.0)}}
    )
    monkeypatch.setattr(bot_module, "oc", fake)
    return fake


# ── evaluate_volume_spike ────────────────────────────────────────────


def test_volume_spike_fires_on_3x_median(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    inst = bot.INSTRUMENTS[0]
    candles = _spike_candles(base_vol=100.0, spike_vol=300.0)
    _install_oc_for_btc(bot, monkeypatch, btc_candles=[], token_candles={inst["mint"]: candles})
    fires, signal = bot.evaluate_volume_spike(inst, candles=candles)
    assert fires is True
    assert signal is not None
    assert signal["signal"] == "volume_spike"
    assert signal["multiplier_observed"] == pytest.approx(3.0)
    assert signal["last_vol"] == 300.0
    assert signal["median_vol"] == 100.0


def test_volume_spike_does_not_fire_on_flat_volume(bot) -> None:
    inst = bot.INSTRUMENTS[0]
    candles = _flat_candles(1.0, vol=100.0)
    fires, signal = bot.evaluate_volume_spike(inst, candles=candles)
    assert fires is False
    assert signal is None


def test_volume_spike_does_not_fire_on_zero_median(bot) -> None:
    inst = bot.INSTRUMENTS[0]
    # All-zero volumes — cold start / illiquid book.
    candles = _flat_candles(1.0, vol=0.0)
    fires, signal = bot.evaluate_volume_spike(inst, candles=candles)
    assert fires is False
    assert signal is None


# ── btc_overlay_passes ───────────────────────────────────────────────


def test_btc_overlay_passes_above_ma(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_oc_for_btc(bot, monkeypatch, btc_candles=_btc_candles_above_ma())
    bot._BTC_CURRENT_TICK_ID = 1  # simulate inside a tick
    ok, reason = bot.btc_overlay_passes()
    assert ok is True
    assert "above" in reason.lower() or reason == "BTC above 20-MA"


def test_btc_overlay_fails_below_ma(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_oc_for_btc(bot, monkeypatch, btc_candles=_btc_candles_below_ma())
    bot._BTC_CURRENT_TICK_ID = 1
    ok, reason = bot.btc_overlay_passes()
    assert ok is False
    assert reason == "BTC below 20-MA"


def test_btc_overlay_fails_open_on_oc_raise(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_oc_for_btc(bot, monkeypatch, btc_candles=RuntimeError("rpc blew up"))
    bot._BTC_CURRENT_TICK_ID = 1
    ok, reason = bot.btc_overlay_passes()
    assert ok is True
    assert reason == "btc_data_unavailable_fail_open"


def test_btc_overlay_cached_within_tick(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_oc_for_btc(bot, monkeypatch, btc_candles=_btc_candles_above_ma())
    bot._BTC_CURRENT_TICK_ID = 5
    bot.btc_overlay_passes()
    bot.btc_overlay_passes()
    bot.btc_overlay_passes()
    btc_calls = [c for c in fake.get_candles.call_args_list if c.args[0] == bot.BTC_WBTC_MINT]
    assert len(btc_calls) == 1, "BTC candles must only be fetched once per tick"


# ── integration with poll_instruments ────────────────────────────────


def test_poll_skips_all_instruments_when_btc_overlay_fails(
    bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BTC below MA → blocks the whole tick.
    token_c = {i["mint"]: _spike_candles(100.0, 1000.0) for i in bot.INSTRUMENTS}
    prices = {i["mint"]: 1.0 for i in bot.INSTRUMENTS}
    _install_oc_for_btc(
        bot,
        monkeypatch,
        btc_candles=_btc_candles_below_ma(),
        token_candles=token_c,
        prices=prices,
    )

    bot.poll_instruments()

    assert [p for p in bot.positions if p["status"] == "open"] == []
    # No per-instrument snapshots written (loop short-circuited).
    assert bot._LAST_SNAPSHOTS == {}


def test_poll_opens_position_via_volume_spike_when_breakout_does_not_fire(
    bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    # All instruments flat in price (no breakout); JTO has a fat volume spike.
    jto = bot.INSTRUMENTS[0]
    jup = bot.INSTRUMENTS[1]
    pyth = bot.INSTRUMENTS[2]
    token_c = {
        jto["mint"]: _spike_candles(100.0, 1000.0, price=1.0),
        jup["mint"]: _flat_candles(2.0, 100.0),
        pyth["mint"]: _flat_candles(0.5, 100.0),
    }
    prices = {jto["mint"]: 1.0, jup["mint"]: 2.0, pyth["mint"]: 0.5}
    _install_oc_for_btc(
        bot,
        monkeypatch,
        btc_candles=_btc_candles_above_ma(),
        token_candles=token_c,
        prices=prices,
    )

    bot.poll_instruments()

    open_pos = [p for p in bot.positions if p["status"] == "open"]
    assert len(open_pos) == 1
    pos = open_pos[0]
    assert pos["symbol"] == "JTO-USDC"
    assert pos["signal_data"]["primitive"] == "volume_spike"
    assert pos["signal_data"]["signal"] == "volume_spike"
    # Last-signal-check surfaces both flags for JTO this tick.
    assert bot._LAST_SIGNAL_CHECK["JTO"] == {"breakout": False, "volume_spike": True}
