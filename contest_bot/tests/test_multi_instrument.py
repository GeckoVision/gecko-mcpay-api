"""Multi-instrument poll loop tests (s40-lab-#4).

Light fakes only. The bot module is imported with ``OPENROUTER_API_KEY``
left unset so the local panel disables itself cleanly; Gecko gate is
stubbed at the instance level so no HTTP is involved.
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
    """Return the bot module with fresh state + stubbed gate/safety."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    if "jto_breakout_gecko_gated_contest_bot" in sys.modules:
        del sys.modules["jto_breakout_gecko_gated_contest_bot"]
    import jto_breakout_gecko_gated_contest_bot as m

    # Reset module state between tests.
    m.positions.clear()
    m.signal_feed.clear()
    m._LAST_SNAPSHOTS.clear()
    m.daily_trades = 0
    m.consec_losses = 0
    m.total_spent_usd = 0.0
    # Local panel disabled (no key); ensure it's None.
    m._LOCAL_PANEL = None

    # Stub the Gecko gate to always allow, no shadow flag.
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

    # Breaker never trips.
    m._BREAKER.check = lambda: (False, "")  # type: ignore[assignment]
    m._BREAKER.record_pnl_delta = lambda x: None  # type: ignore[assignment]

    # Safety: always pass.
    monkeypatch.setattr(m, "passes_safety", lambda token: (True, []))
    return m


def _candles_breakout(latest_close: float, prior_high: float) -> list[dict]:
    """24 candles with prior highs at `prior_high` and a final breakout close."""
    base = [
        {
            "ts": i,
            "open": prior_high - 1,
            "high": prior_high,
            "low": prior_high - 2,
            "close": prior_high - 1,
            "volume": 100.0,
        }
        for i in range(23)
    ]
    base.append(
        {
            "ts": 23,
            "open": prior_high,
            "high": latest_close,
            "low": prior_high - 0.5,
            "close": latest_close,
            "volume": 200.0,
        }
    )
    return base


def _candles_flat(price: float) -> list[dict]:
    return [
        {"ts": i, "open": price, "high": price, "low": price, "close": price, "volume": 100.0}
        for i in range(24)
    ]


def _install_oc(
    bot_module,
    monkeypatch: pytest.MonkeyPatch,
    *,
    by_mint: dict[str, list[dict]],
    price_by_mint: dict[str, float],
) -> MagicMock:
    """Mock the bot's `oc` client with per-mint kline + price."""
    fake = MagicMock()
    fake.get_candles = MagicMock(side_effect=lambda mint, bar, limit: by_mint.get(mint, []))
    fake.get_price_info = MagicMock(
        side_effect=lambda mint: {"data": {"price": price_by_mint.get(mint, 0.0)}}
    )
    monkeypatch.setattr(bot_module, "oc", fake)
    return fake


def test_poll_iterates_all_three_instruments(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    flat = _candles_flat(1.0)
    mints = {i["mint"]: flat for i in bot.INSTRUMENTS}
    prices = {i["mint"]: 1.0 for i in bot.INSTRUMENTS}
    fake = _install_oc(bot, monkeypatch, by_mint=mints, price_by_mint=prices)

    bot.poll_instruments()

    # One candle fetch per instrument per poll.
    called_mints = [c.args[0] for c in fake.get_candles.call_args_list]
    assert called_mints == [i["mint"] for i in bot.INSTRUMENTS]
    # Snapshot recorded for each.
    for inst in bot.INSTRUMENTS:
        assert inst["symbol"] in bot._LAST_SNAPSHOTS


def test_max_concurrent_blocks_across_instruments(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    # JTO breaks out big; JUP also would break out big; PYTH flat.
    jto_mint = bot.INSTRUMENTS[0]["mint"]
    jup_mint = bot.INSTRUMENTS[1]["mint"]
    pyth_mint = bot.INSTRUMENTS[2]["mint"]
    by_mint = {
        jto_mint: _candles_breakout(1.05, 1.00),  # +5%
        jup_mint: _candles_breakout(2.10, 2.00),  # +5%
        pyth_mint: _candles_flat(0.50),
    }
    prices = {jto_mint: 1.05, jup_mint: 2.10, pyth_mint: 0.50}
    _install_oc(bot, monkeypatch, by_mint=by_mint, price_by_mint=prices)

    bot.poll_instruments()

    open_positions = [p for p in bot.positions if p["status"] == "open"]
    assert len(open_positions) == 1, "MAX_CONCURRENT=1 must hold across instruments"
    assert open_positions[0]["symbol"] == "JTO-USDC"
    assert bot.daily_trades == 1


def test_daily_trades_is_global(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    jto_mint = bot.INSTRUMENTS[0]["mint"]
    jup_mint = bot.INSTRUMENTS[1]["mint"]
    pyth_mint = bot.INSTRUMENTS[2]["mint"]
    by_mint = {
        jto_mint: _candles_breakout(1.05, 1.00),
        jup_mint: _candles_breakout(2.10, 2.00),
        pyth_mint: _candles_breakout(0.55, 0.50),
    }
    prices = {jto_mint: 1.05, jup_mint: 2.10, pyth_mint: 0.55}
    _install_oc(bot, monkeypatch, by_mint=by_mint, price_by_mint=prices)

    # Allow more concurrent so we can prove daily_trades aggregates.
    monkeypatch.setattr(bot, "MAX_CONCURRENT", 5)

    bot.poll_instruments()
    assert bot.daily_trades == min(bot.MAX_DAILY_TRADES, 3)
    # Reflect global cap if MAX_DAILY_TRADES < 3
    if bot.MAX_DAILY_TRADES < 3:
        assert bot.daily_trades == bot.MAX_DAILY_TRADES


def test_signal_feed_has_instrument_tags(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    jto_mint = bot.INSTRUMENTS[0]["mint"]
    by_mint = {
        jto_mint: _candles_breakout(1.05, 1.00),
        bot.INSTRUMENTS[1]["mint"]: _candles_flat(2.0),
        bot.INSTRUMENTS[2]["mint"]: _candles_flat(0.5),
    }
    prices = {
        jto_mint: 1.05,
        bot.INSTRUMENTS[1]["mint"]: 2.0,
        bot.INSTRUMENTS[2]["mint"]: 0.5,
    }
    _install_oc(bot, monkeypatch, by_mint=by_mint, price_by_mint=prices)

    bot.poll_instruments()

    tagged = [e for e in bot.signal_feed if e["msg"].startswith("[JTO]")]
    assert tagged, f"expected at least one [JTO]-tagged feed entry, got {bot.signal_feed}"


def test_evaluate_breakout_below_confirm_returns_none(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    inst = bot.INSTRUMENTS[0]
    # Breakout of only 0.05% — below confirm_pct=0.2.
    by_mint = {inst["mint"]: _candles_breakout(1.0005, 1.0)}
    prices = {inst["mint"]: 1.0005}
    _install_oc(bot, monkeypatch, by_mint=by_mint, price_by_mint=prices)

    assert bot.evaluate_breakout(inst) is None
    snap = bot._LAST_SNAPSHOTS[inst["symbol"]]
    assert snap["spot"] == pytest.approx(1.0005)


def test_global_budget_cap_blocks_live_entries(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force live mode and put cumulative spend at the cap.
    monkeypatch.setattr(bot, "PAPER_TRADE", False)
    bot.total_spent_usd = bot.MAX_BUDGET_USD  # at cap

    jto_mint = bot.INSTRUMENTS[0]["mint"]
    by_mint = {
        jto_mint: _candles_breakout(1.05, 1.00),
        bot.INSTRUMENTS[1]["mint"]: _candles_flat(2.0),
        bot.INSTRUMENTS[2]["mint"]: _candles_flat(0.5),
    }
    prices = {
        jto_mint: 1.05,
        bot.INSTRUMENTS[1]["mint"]: 2.0,
        bot.INSTRUMENTS[2]["mint"]: 0.5,
    }
    _install_oc(bot, monkeypatch, by_mint=by_mint, price_by_mint=prices)

    bot.poll_instruments()
    assert [p for p in bot.positions if p["status"] == "open"] == []
