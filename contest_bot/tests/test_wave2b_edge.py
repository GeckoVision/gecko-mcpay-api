"""Wave-2b EDGE tests: net-flow CVD gate + 1h regime modulator + coordinator.

Light fakes only — no real onchainos, no live LLM, no network.
Covers the spec requirements:
  - net_flow: CVD reconstruction, verdict classification, TTL cache, fail-open
  - regime_1h: compute_regime_1h on synthetic candle series
  - coordinator: regime_1h modulator raises chart floor for TREND-DOWN / CHOP
  - distribution_flow gate blocks candidates in poll_instruments
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))


# ── net_flow tests ────────────────────────────────────────────────────

import net_flow as nf
from net_flow import NetFlowSignal, compute_net_flow, cache_clear


def _make_oc(trades: list[dict], signals: list[dict] | Exception | None = None) -> Any:
    """Build a minimal onchainos fake with preset trades + signals."""
    fake = MagicMock()
    fake.get_token_trades.return_value = trades
    if isinstance(signals, Exception):
        fake.get_signals.side_effect = signals
    else:
        fake.get_signals.return_value = signals or []
    return fake


# Sample buy and sell trade dicts matching the field names onchainos returns.
_BUY_1000 = {"side": "buy", "usd_amount": 1000.0}
_SELL_200  = {"side": "sell", "usd_amount": 200.0}
_BUY_300   = {"side": "buy", "usd_amount": 300.0}
_SELL_2000 = {"side": "sell", "usd_amount": 2000.0}


@pytest.fixture(autouse=True)
def clear_cache():
    """Reset the net-flow cache before every test."""
    cache_clear()
    yield
    cache_clear()


class TestNetFlowCVD:
    def test_accumulation_verdict(self) -> None:
        """Net buy > net_band → accumulation."""
        oc = _make_oc([_BUY_1000, _BUY_300, _SELL_200])
        result = compute_net_flow("TOKEN_A", "JTO", oc)
        assert result is not None
        assert result.buy_usd == pytest.approx(1300.0)
        assert result.sell_usd == pytest.approx(200.0)
        assert result.net_flow_usd == pytest.approx(1100.0)
        assert result.verdict == "accumulation"

    def test_distribution_verdict(self) -> None:
        """Net sell > net_band → distribution."""
        oc = _make_oc([_SELL_2000, _BUY_300])
        result = compute_net_flow("TOKEN_B", "WIF", oc)
        assert result is not None
        assert result.verdict == "distribution"
        assert result.net_flow_usd < 0

    def test_neutral_small_imbalance(self) -> None:
        """Tiny imbalance below neutral band → neutral (not accumulation)."""
        # $100 buy vs $90 sell: net $10, 10% — below _NEUTRAL_BAND_USD ($500)
        oc = _make_oc([
            {"side": "buy", "usd_amount": 100.0},
            {"side": "sell", "usd_amount": 90.0},
        ])
        result = compute_net_flow("TOKEN_C", "JUP", oc)
        assert result is not None
        assert result.verdict == "neutral"

    def test_neutral_small_pct_imbalance(self) -> None:
        """Large volumes but <10% net imbalance → neutral."""
        # $10,100 buy vs $9,900 sell: net $200, but <10% (200/20000 = 1%)
        oc = _make_oc([
            {"side": "buy", "usd_amount": 10_100.0},
            {"side": "sell", "usd_amount": 9_900.0},
        ])
        result = compute_net_flow("TOKEN_D", "RAY", oc)
        assert result is not None
        assert result.verdict == "neutral"

    def test_neutral_upgrades_to_accumulation_on_sm_buys(self) -> None:
        """Neutral CVD + ≥2 smart-money buys → upgraded to accumulation."""
        oc = _make_oc(
            [{"side": "buy", "usd_amount": 100.0}, {"side": "sell", "usd_amount": 90.0}],
            signals=[
                {"direction": "buy"},
                {"direction": "buy"},
            ],
        )
        result = compute_net_flow("TOKEN_E", "PYTH", oc)
        assert result is not None
        assert result.smart_money_buys == 2
        assert result.verdict == "accumulation"

    def test_distribution_not_downgraded_by_sm_buys(self) -> None:
        """Distribution verdict is NOT upgraded even with SM buys."""
        oc = _make_oc(
            [_SELL_2000, _BUY_300],
            signals=[{"direction": "buy"}, {"direction": "buy"}],
        )
        result = compute_net_flow("TOKEN_F", "JTO", oc)
        assert result is not None
        assert result.verdict == "distribution"

    def test_fail_open_on_get_trades_exception(self) -> None:
        """Any exception in get_token_trades → returns None (fail-open)."""
        fake = MagicMock()
        fake.get_token_trades.side_effect = RuntimeError("onchainos down")
        result = compute_net_flow("TOKEN_G", "WIF", fake)
        assert result is None

    def test_signals_exception_degrades_gracefully(self) -> None:
        """get_signals raising should not kill the whole compute."""
        oc = _make_oc([_BUY_1000, _SELL_200], signals=RuntimeError("signal error"))
        result = compute_net_flow("TOKEN_H", "JUP", oc)
        assert result is not None
        # sm_buys degrades to 0, CVD still valid
        assert result.smart_money_buys == 0
        assert result.verdict == "accumulation"

    def test_empty_trades_returns_neutral(self) -> None:
        """No trades → neutral (not distribution — can't say sellers)."""
        oc = _make_oc([])
        result = compute_net_flow("TOKEN_I", "RAY", oc)
        assert result is not None
        assert result.verdict == "neutral"
        assert result.net_flow_usd == pytest.approx(0.0)

    def test_cache_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Second call within TTL returns cached result without re-fetching."""
        oc = _make_oc([_BUY_1000])
        result1 = compute_net_flow("TOKEN_J", "JTO", oc)
        assert result1 is not None
        # Second call — should hit cache, NOT call get_token_trades again.
        result2 = compute_net_flow("TOKEN_J", "JTO", oc)
        assert result2 is result1
        assert oc.get_token_trades.call_count == 1  # only called once

    def test_cache_expires_after_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After TTL, a fresh fetch is performed."""
        oc = _make_oc([_BUY_1000])
        # Freeze time at T=0
        t0 = time.time()
        monkeypatch.setattr(nf, "TTL_SECONDS", 0.1)
        compute_net_flow("TOKEN_K", "JTO", oc)
        time.sleep(0.15)  # outlast TTL
        compute_net_flow("TOKEN_K", "JTO", oc)
        assert oc.get_token_trades.call_count == 2

    def test_usd_field_aliases(self) -> None:
        """Parser handles multiple USD field name variants."""
        trades = [
            {"side": "buy", "usdAmount": 600.0},   # camelCase
            {"side": "sell", "amount": 50.0},
        ]
        oc = _make_oc(trades)
        result = compute_net_flow("TOKEN_L", "PYTH", oc)
        assert result is not None
        assert result.buy_usd == pytest.approx(600.0)
        assert result.sell_usd == pytest.approx(50.0)

    def test_side_tradeType_alias(self) -> None:
        """Side parsed from 'tradeType' field with numeric values."""
        trades = [
            {"tradeType": "1", "usd_amount": 800.0},   # "1" = buy
            {"tradeType": "2", "usd_amount": 100.0},   # "2" = sell
        ]
        oc = _make_oc(trades)
        result = compute_net_flow("TOKEN_M", "WIF", oc)
        assert result is not None
        assert result.verdict == "accumulation"


# ── regime_1h tests ───────────────────────────────────────────────────

from indicators import compute_regime_1h


def _candles_trending_up(n: int = 40) -> list[dict]:
    """Strong uptrend: each close higher, tight ATR."""
    bars = []
    price = 1.0
    for i in range(n):
        price += 0.05  # +5% per bar — consistent uptrend
        bars.append({
            "ts": i,
            "open": price - 0.02,
            "high": price + 0.01,
            "low": price - 0.03,
            "close": price,
            "volume": 10000.0,
        })
    return bars


def _candles_trending_down(n: int = 40) -> list[dict]:
    """Strong downtrend: each close lower."""
    bars = []
    price = 10.0
    for i in range(n):
        price -= 0.05  # -5% per bar
        bars.append({
            "ts": i,
            "open": price + 0.02,
            "high": price + 0.03,
            "low": price - 0.01,
            "close": price,
            "volume": 10000.0,
        })
    return bars


def _candles_choppy(n: int = 40) -> list[dict]:
    """Oscillating price — no directional trend."""
    import math
    bars = []
    for i in range(n):
        price = 2.0 + 0.1 * math.sin(i * 0.8)
        bars.append({
            "ts": i,
            "open": price,
            "high": price + 0.005,
            "low": price - 0.005,
            "close": price + 0.001,
            "volume": 5000.0,
        })
    return bars


class TestRegime1h:
    def test_insufficient_bars_returns_chop(self) -> None:
        """Fewer than 28 bars → CHOP (conservative default)."""
        assert compute_regime_1h([]) == "CHOP"
        short = _candles_trending_up(n=10)
        assert compute_regime_1h(short) == "CHOP"

    def test_uptrend_candles_return_trend_up(self) -> None:
        """Strong consecutive uptrend → TREND-UP."""
        result = compute_regime_1h(_candles_trending_up(n=40))
        assert result == "TREND-UP"

    def test_downtrend_candles_return_trend_down(self) -> None:
        """Strong consecutive downtrend → TREND-DOWN."""
        result = compute_regime_1h(_candles_trending_down(n=40))
        assert result == "TREND-DOWN"

    def test_choppy_candles_return_chop(self) -> None:
        """Oscillating price → CHOP."""
        result = compute_regime_1h(_candles_choppy(n=40))
        assert result == "CHOP"


# ── coordinator regime_1h modulator tests ────────────────────────────

from voices.coordinator_rules import coordinator
from voices.base import VoiceOpinion


def _op(name: str, verdict: str, conf: float) -> VoiceOpinion:
    return VoiceOpinion(
        voice_name=name,
        verdict=verdict,  # type: ignore[arg-type]
        confidence=conf,
        reasoning="test",
        raw_response="{}",
        elapsed_ms=5,
        cost_usd=0.0,
    )


def _passing_opinions(chart_conf: float = 0.90) -> list[VoiceOpinion]:
    """Three voices that would pass without a regime modulator."""
    return [
        _op("chart_analyst", "bullish", chart_conf),
        _op("risk_voice", "neutral", 0.5),
        _op("memory_voice", "neutral", 0.3),
        _op("regime_analyst", "bullish", 0.7),  # 5m uptrend
    ]


class TestCoordinatorRegime1h:
    def test_no_regime_1h_uses_normal_floor(self) -> None:
        """None regime_1h → normal floor (0.85); chart at 0.86 should act."""
        action, rule = coordinator(_passing_opinions(chart_conf=0.86), regime_1h=None)
        assert action == "act"
        assert rule == "all_voices_aligned"

    def test_trend_up_1h_uses_normal_floor(self) -> None:
        """TREND-UP 1h → normal floor; chart at 0.86 should act."""
        action, rule = coordinator(_passing_opinions(chart_conf=0.86), regime_1h="TREND-UP")
        assert action == "act"
        assert rule == "all_voices_aligned"

    def test_chop_1h_raises_floor(self) -> None:
        """CHOP 1h → raised floor (0.92); chart at 0.88 must decline."""
        action, rule = coordinator(_passing_opinions(chart_conf=0.88), regime_1h="CHOP")
        assert action == "decline"
        assert rule == "1h_adverse_below_high_bar"

    def test_trend_down_1h_raises_floor(self) -> None:
        """TREND-DOWN 1h → raised floor (0.92); chart at 0.88 must decline."""
        action, rule = coordinator(_passing_opinions(chart_conf=0.88), regime_1h="TREND-DOWN")
        assert action == "decline"
        assert rule == "1h_adverse_below_high_bar"

    def test_trend_down_1h_high_conviction_acts(self) -> None:
        """TREND-DOWN 1h but chart >= 0.92 → act (modulator, not veto)."""
        action, rule = coordinator(_passing_opinions(chart_conf=0.93), regime_1h="TREND-DOWN")
        assert action == "act"
        assert rule == "1h_adverse_high_conviction"

    def test_chop_1h_high_conviction_acts(self) -> None:
        """CHOP 1h but chart >= 0.92 → act."""
        action, rule = coordinator(_passing_opinions(chart_conf=0.92), regime_1h="CHOP")
        assert action == "act"

    def test_risk_veto_overrides_everything(self) -> None:
        """Risk veto fires before the 1h modulator."""
        opinions = [
            _op("chart_analyst", "bullish", 0.95),
            _op("risk_voice", "bearish", 0.9),
            _op("memory_voice", "neutral", 0.3),
        ]
        action, rule = coordinator(opinions, regime_1h="TREND-UP")
        assert action == "decline"
        assert rule == "risk_veto"

    def test_old_style_coordinator_still_works(self) -> None:
        """Calling coordinator without regime_1h (old style) doesn't crash."""
        action, rule = coordinator(_passing_opinions(chart_conf=0.90))
        assert action == "act"


# ── poll_instruments distribution gate integration test ──────────────

class TestDistributionGateInBot:
    """Smoke test: poll_instruments blocks distribution-flow candidates."""

    @pytest.fixture
    def bot(self, monkeypatch: pytest.MonkeyPatch):
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
        m._1H_REGIME_CACHE.clear()
        m._POLL_COUNT = 0
        m.daily_trades = 0
        m.consec_losses = 0
        m.total_spent_usd = 0.0
        m._LOCAL_PANEL = None

        # Stub breaker + safety
        m._BREAKER.check = lambda: (False, "")
        m._BREAKER.record_pnl_delta = lambda x: None
        monkeypatch.setattr(m, "passes_safety", lambda token: (True, []))

        return m

    def _flat_candles_breakout(self, base: float = 1.0, n: int = 30) -> list[dict]:
        """24 flat bars then one higher close to trigger breakout."""
        bars = [
            {"ts": i, "open": base, "high": base + 0.001, "low": base - 0.001, "close": base, "volume": 1000.0}
            for i in range(n - 1)
        ]
        # Final bar breaks above by 2%
        close = base * 1.02
        bars.append({"ts": n - 1, "open": base, "high": close, "low": base, "close": close, "volume": 1000.0})
        return bars

    def test_distribution_flow_blocks_candidate(self, bot, monkeypatch: pytest.MonkeyPatch) -> None:
        """A volume_spike candidate with distribution flow is blocked."""
        inst = bot.INSTRUMENTS[0]
        mint = inst["mint"]

        # Candles: last bar has 3x volume spike
        bars = self._flat_candles_breakout(base=1.0)
        # Make it also a volume spike
        bars[-1]["volume"] = 3000.0  # 3× median

        fake_oc = MagicMock()
        fake_oc.get_candles.return_value = bars
        fake_oc.get_price_info.return_value = {"data": {"price": 1.02}}
        fake_oc.btc_overlay_passes = MagicMock(return_value=(True, "disabled"))
        # Distribution: heavy sell flow
        fake_oc.get_token_trades.return_value = [
            {"side": "sell", "usd_amount": 5000.0},
            {"side": "buy",  "usd_amount": 100.0},
        ]
        fake_oc.get_signals.return_value = []

        monkeypatch.setattr(bot, "oc", fake_oc)
        # Disable BTC overlay
        monkeypatch.setattr(bot, "BTC_OVERLAY", None)

        initial_pos_count = len([p for p in bot.positions if p["status"] == "open"])
        bot.poll_instruments()

        # Position must NOT have been opened
        new_pos_count = len([p for p in bot.positions if p["status"] == "open"])
        assert new_pos_count == initial_pos_count

        # Check signal_feed contains distribution_flow decline
        distribution_log = [
            e for e in bot.signal_feed
            if "distribution" in e.get("msg", "").lower()
               or "distribution_flow" in e.get("msg", "").lower()
        ]
        assert len(distribution_log) >= 1

    def test_accumulation_flow_does_not_block(self, bot, monkeypatch: pytest.MonkeyPatch) -> None:
        """Accumulation flow does NOT block (position lifecycle proceeds)."""
        inst = bot.INSTRUMENTS[0]
        mint = inst["mint"]

        bars = self._flat_candles_breakout(base=1.0)

        fake_oc = MagicMock()
        fake_oc.get_candles.return_value = bars
        fake_oc.get_price_info.return_value = {"data": {"price": 1.02}}
        # Accumulation: heavy buy flow
        fake_oc.get_token_trades.return_value = [
            {"side": "buy",  "usd_amount": 5000.0},
            {"side": "sell", "usd_amount": 200.0},
        ]
        fake_oc.get_signals.return_value = []
        fake_oc.get_all_balances.return_value = []

        monkeypatch.setattr(bot, "oc", fake_oc)
        monkeypatch.setattr(bot, "BTC_OVERLAY", None)
        monkeypatch.setattr(bot, "PAPER_TRADE", True)

        # We just need to ensure there's no EARLY distribution block.
        # open_position may or may not fire depending on panel, but
        # the distribution filter must not log a decline.
        bot.poll_instruments()

        distribution_blocks = [
            e for e in bot.signal_feed
            if "distribution_flow" in e.get("msg", "").lower()
        ]
        assert len(distribution_blocks) == 0
