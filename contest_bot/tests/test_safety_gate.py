"""Tier-1 fast `/safety` veto — module + poll_instruments wiring.

Light fakes only — no live gecko-api, no network, no LLM. Covers:
  - safety_gate.check_safety: gate mapping (block/caution/ok/unknown)
  - fail-OPEN on network error / disabled / bad response
  - poll_instruments: a tier-1 `gate=block` skips the entry + logs it,
    and the local `passes_safety` check is never reached
  - poll_instruments: `gate=ok` proceeds past tier 1 (no tier-1 block log)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

import safety_gate as sg  # noqa: E402 — after sys.path insert (contest_bot test convention)

_MINT = "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3"


# ── safety_gate.check_safety unit tests ───────────────────────────────


class TestCheckSafety:
    def _fake_post(self, body: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = body
        monkeypatch.setattr(sg.httpx, "post", lambda *a, **k: resp)

    def test_block_gate_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GECKO_SAFETY_GATE", "1")
        self._fake_post(
            {"gate": "block", "honeypot": True, "rug_flags": ["fake_market_cap"]}, monkeypatch
        )
        res = sg.check_safety(_MINT)
        assert res.gate == "block"
        assert res.should_skip is True
        assert res.raw["honeypot"] is True

    def test_caution_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GECKO_SAFETY_GATE", "1")
        self._fake_post({"gate": "caution", "rug_flags": ["thin_liquidity_vs_mcap"]}, monkeypatch)
        res = sg.check_safety(_MINT)
        assert res.gate == "caution"
        assert res.should_skip is False

    def test_ok_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GECKO_SAFETY_GATE", "1")
        self._fake_post({"gate": "ok"}, monkeypatch)
        res = sg.check_safety(_MINT)
        assert res.gate == "ok"
        assert res.should_skip is False

    def test_unknown_fail_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GECKO_SAFETY_GATE", "1")
        self._fake_post({"gate": "unknown", "checked": False}, monkeypatch)
        res = sg.check_safety(_MINT)
        assert res.gate == "unknown"
        assert res.should_skip is False

    def test_network_error_fail_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GECKO_SAFETY_GATE", "1")

        def _boom(*_a: object, **_k: object) -> None:
            raise sg.httpx.ConnectError("refused")

        monkeypatch.setattr(sg.httpx, "post", _boom)
        res = sg.check_safety(_MINT)
        assert res.gate == "unknown"
        assert res.should_skip is False
        assert "safety_call_error" in res.reason

    def test_disabled_bypasses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GECKO_SAFETY_GATE", "0")
        # If httpx.post were called we'd raise — proving the bypass short-circuits.
        monkeypatch.setattr(
            sg.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called"))
        )
        res = sg.check_safety(_MINT)
        assert res.gate == "unknown"
        assert res.should_skip is False
        assert res.reason == "safety_gate_disabled"

    def test_unexpected_gate_value_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GECKO_SAFETY_GATE", "1")
        self._fake_post({"gate": "weird_new_value"}, monkeypatch)
        res = sg.check_safety(_MINT)
        # Unknown-to-us value must fail-open, never block.
        assert res.should_skip is False
        assert res.gate == "unknown"


# ── poll_instruments tier-1 wiring integration ────────────────────────


class TestSafetyTier1InBot:
    @pytest.fixture
    def bot(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("GECKO_ENTRY_REQUIRE_BREAKOUT", "0")
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

        m._BREAKER.check = lambda: (False, "")
        m._BREAKER.record_pnl_delta = lambda x: None
        # The LOCAL passes_safety must be a tripwire: if tier-1 blocks first,
        # this should never be reached on the block path.
        return m

    def _flat_candles_breakout(self, base: float = 1.0, n: int = 30) -> list[dict]:
        bars = [
            {
                "ts": i,
                "open": base,
                "high": base + 0.001,
                "low": base - 0.001,
                "close": base,
                "volume": 1000.0,
            }
            for i in range(n - 1)
        ]
        close = base * 1.02
        bars.append(
            {
                "ts": n - 1,
                "open": base,
                "high": close,
                "low": base,
                "close": close,
                "volume": 1000.0,
            }
        )
        return bars

    def _wire_feed(self, bot, monkeypatch: pytest.MonkeyPatch, mint: str) -> None:
        bars = self._flat_candles_breakout(base=1.0)
        fake_oc = MagicMock()
        fake_oc.get_candles.return_value = bars
        fake_oc.get_price_info.return_value = {"data": {"price": 1.02}}
        # Accumulation flow so the net-flow gate doesn't block.
        fake_oc.get_token_trades.return_value = []
        fake_oc.get_signals.return_value = []
        fake_oc.get_all_balances.return_value = []
        monkeypatch.setattr(bot, "oc", fake_oc)
        monkeypatch.setattr(bot, "BTC_OVERLAY", None)

    def test_safety_block_skips_entry_before_local_safety(
        self, bot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inst = bot.INSTRUMENTS[0]
        self._wire_feed(bot, monkeypatch, inst["mint"])

        # Tripwire: local passes_safety must NOT be reached when tier-1 blocks.
        local_calls = {"n": 0}

        def _tripwire(_token: str):
            local_calls["n"] += 1
            return (True, [])

        monkeypatch.setattr(bot, "passes_safety", _tripwire)

        # Tier-1 returns block.
        monkeypatch.setattr(bot, "check_safety", lambda token: _block_result())

        initial = len([p for p in bot.positions if p["status"] == "open"])
        bot.poll_instruments()

        assert len([p for p in bot.positions if p["status"] == "open"]) == initial
        assert local_calls["n"] == 0  # tier-1 short-circuited before local safety
        tier1_logs = [e for e in bot.signal_feed if "/safety tier-1" in e.get("msg", "").lower()]
        assert any("skipping entry" in e["msg"].lower() for e in tier1_logs)

    def test_safety_ok_proceeds_past_tier1(self, bot, monkeypatch: pytest.MonkeyPatch) -> None:
        inst = bot.INSTRUMENTS[0]
        self._wire_feed(bot, monkeypatch, inst["mint"])
        monkeypatch.setattr(bot, "passes_safety", lambda token: (True, []))
        monkeypatch.setattr(bot, "PAPER_TRADE", True)

        called = {"n": 0}

        def _ok(token: str):
            called["n"] += 1
            return _ok_result()

        monkeypatch.setattr(bot, "check_safety", _ok)

        bot.poll_instruments()

        assert called["n"] >= 1  # tier-1 invoked
        # A tier-1 pass should be logged (proves the gate ran + recorded).
        ok_logs = [e for e in bot.signal_feed if "/safety tier-1: ok" in e.get("msg", "").lower()]
        assert len(ok_logs) >= 1
        # No tier-1 block decline should be logged.
        block_logs = [e for e in bot.signal_feed if "skipping entry" in e.get("msg", "").lower()]
        assert len(block_logs) == 0

    def test_entry_fires_with_tier1_ok_and_gate_recorded_on_position(
        self, bot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A paper entry FIRES on the memecoin universe when tier-1=ok, and the
        opened position carries the tier-1 /safety gate result in signal_data.

        This is the P1+P2 smoke in unit form: entries fire AND the gate is
        invoked + logged on the entry record.
        """
        inst = bot.INSTRUMENTS[0]
        self._wire_feed(bot, monkeypatch, inst["mint"])
        monkeypatch.setattr(bot, "passes_safety", lambda token: (True, []))
        monkeypatch.setattr(bot, "PAPER_TRADE", True)
        monkeypatch.setattr(bot, "check_safety", lambda token: _ok_result())
        # Local panel off → deterministic coordinator. Force it to act so the
        # entry deterministically fires (we are testing tier-1 wiring + the
        # entry record, not the coordinator's own gating logic).
        monkeypatch.setattr(
            bot, "_deterministic_coordinator_gate", lambda sym, regime_1h: ("act", None)
        )
        # Oracle cache empty → no tier-2 veto (memecoins have no canon).
        monkeypatch.setattr(bot._FUNDAMENTALS, "get_for_instrument", lambda inst: None)

        bot.poll_instruments()

        open_pos = [p for p in bot.positions if p["status"] == "open"]
        assert len(open_pos) >= 1, "expected a paper entry to fire on the memecoin universe"
        # The tier-1 gate result must be recorded on the position's signal_data.
        sg_rec = (open_pos[0].get("signal_data") or {}).get("safety_gate")
        assert sg_rec is not None
        assert sg_rec["gate"] == "ok"


def _block_result():
    return sg.SafetyGateResult(
        gate="block", should_skip=True, reason="safety_block", raw={"honeypot": True}
    )


def _ok_result():
    return sg.SafetyGateResult(gate="ok", should_skip=False, reason="safety_ok", raw={"gate": "ok"})
