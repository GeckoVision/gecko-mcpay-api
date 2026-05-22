"""Tests for the three local-lab voices + coordinator + bootstrap.

Light fakes only — no real OpenRouter, no live LLM calls. Every HTTP
call goes through ``httpx.MockTransport`` injected into the
:class:`OpenRouterClient` via constructor. The load-bearing test (per
spec §8.2) is :func:`test_chart_analyst_thin_liquidity_synthetic_zero_vol`
which feeds a 30-bar window with bars 1-24 zero-vol and asserts the
voice returns ``abstain`` — the thin-liquidity penalty clause is the
defense against the S24 confabulation failure mode.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

# contest_bot is not a uv-workspace member; make it importable.
_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from llm_client import OpenRouterClient  # noqa: E402
from local_memory import LocalMemory  # noqa: E402
from local_panel import LocalPanel  # noqa: E402
from voices.base import VoiceOpinion  # noqa: E402
from voices.chart_analyst import ChartAnalystVoice  # noqa: E402
from voices.coordinator_rules import coordinator  # noqa: E402
from voices.regime_analyst import RegimeAnalystVoice  # noqa: E402
from voices.memory_voice import MemoryVoice  # noqa: E402
from voices.risk_voice import (  # noqa: E402
    RiskVoice,
    _compute_risk_band_deterministic,
)


# ── Helpers ───────────────────────────────────────────────────────────
def _make_or_client(handler: Any) -> OpenRouterClient:
    """Build an OpenRouterClient backed by a MockTransport."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return OpenRouterClient(api_key="sk-test", http_client=http_client)


def _make_response(
    content: str,
    *,
    model: str = "openai/gpt-4o-mini",
    cost: float = 0.00012,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 250,
                "completion_tokens": 80,
                "cost": cost,
            },
        },
    )


def _healthy_market_state(**overrides: Any) -> dict[str, Any]:
    """A market_state snapshot with a clean risk floor and 30 healthy bars."""
    state: dict[str, Any] = {
        "instrument": "JTO",
        "symbol": "JTO-USDC",
        "spot_price": 2.50,
        "change_1h_pct": 0.5,
        "change_24h_pct": 3.2,
        "range_24h_pct": 4.5,
        "volume_24h": 5_000_000.0,
        "ohlcv_5m": [
            {
                "ts": f"2026-05-20T12:{i:02d}:00Z",
                "open": 2.40 + i * 0.001,
                "high": 2.42 + i * 0.001,
                "low": 2.39 + i * 0.001,
                "close": 2.41 + i * 0.001,
                "volume": 12_000.0 + i * 100,
            }
            for i in range(30)
        ],
        # risk floor — all clean
        "daily_trades": 0,
        "max_daily_trades": 3,
        "consec_losses": 0,
        "session_loss_pause_threshold": 2,
        "hourly_pnl_delta": 0.5,
        "breaker_threshold_usd": -3.0,
        "total_spent_usd": 0.0,
        "max_budget_usd": 100.0,
        "open_position_count": 0,
        "max_concurrent": 1,
    }
    state.update(overrides)
    return state


def _opinion(
    voice_name: str,
    verdict: str,
    confidence: float,
) -> VoiceOpinion:
    return VoiceOpinion(
        voice_name=voice_name,
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        reasoning="test",
        raw_response="{}",
        elapsed_ms=10,
        cost_usd=0.0,
    )


# ── chart_analyst ─────────────────────────────────────────────────────
def test_chart_analyst_parses_bullish_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(
            json.dumps(
                {
                    "verdict": "bullish",
                    "confidence": 0.72,
                    "reasoning": "trend up on 5m + breakout w/ volume",
                    "observations": ["6-bar trend up", "vol > 6-bar median"],
                }
            )
        )

    client = _make_or_client(handler)
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=Path("/tmp") / "test_chart_parses.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.voice_name == "chart_analyst"
    assert op.verdict == "bullish"
    assert op.confidence == pytest.approx(0.72)
    assert op.cost_usd == pytest.approx(0.00012)
    assert "trend up" in op.reasoning
    assert len(op.observations) == 2
    client.aclose()


def test_chart_analyst_thin_liquidity_synthetic_zero_vol(tmp_path: Path) -> None:
    """The load-bearing probe (spec §8.2).

    Feed 30 bars where bars 0-23 have ``volume=0`` and bars 24-29 are real.
    Even if gpt-4o-mini returns ``bullish``, the response-parser MUST
    override to ``abstain`` because >4 zero-vol bars triggers the
    thin-liquidity penalty.
    """
    bars: list[dict[str, Any]] = []
    for i in range(30):
        bars.append(
            {
                "ts": f"2026-05-20T12:{i:02d}:00Z",
                "open": 0.001 + i * 0.0001,
                "high": 0.0011 + i * 0.0001,
                "low": 0.001 + i * 0.0001,
                "close": 0.0011 + i * 0.0001,
                "volume": 0.0 if i < 24 else 5_000.0,
            }
        )

    state = _healthy_market_state(ohlcv_5m=bars, range_24h_pct=15.0)

    # Adversarial probe: have the model RETURN bullish anyway. The
    # response-parser override should still flip to abstain.
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(
            json.dumps(
                {
                    "verdict": "bullish",
                    "confidence": 0.55,
                    "reasoning": "looks like a fresh listing pop",
                    "observations": ["close > open on most recent"],
                }
            )
        )

    client = _make_or_client(handler)
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "chart_zero_vol.jsonl")
    op = asyncio.run(voice.grade(state, mem))

    assert op.verdict == "abstain", "thin-liquidity penalty must force abstain"
    assert "thin_liquidity_override" in op.reasoning
    assert op.confidence == 0.0
    client.aclose()


def test_chart_analyst_handles_fenced_json(tmp_path: Path) -> None:
    fenced = (
        "Here is my call:\n"
        "```json\n"
        '{"verdict": "neutral", "confidence": 0.55, "reasoning": "mid"}\n'
        "```"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(fenced)

    client = _make_or_client(handler)
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "chart_fenced.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "neutral"
    assert op.confidence == pytest.approx(0.55)
    client.aclose()


def test_chart_analyst_parse_fail_returns_abstain(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response("this is not json at all")

    client = _make_or_client(handler)
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "chart_parse_fail.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "abstain"
    assert op.confidence == 0.0
    assert op.reasoning == "parse_error"
    assert op.cost_usd == pytest.approx(0.00012)
    client.aclose()


def test_chart_analyst_handles_openrouter_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = _make_or_client(handler)
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "chart_or_err.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "abstain"
    assert "openrouter_error" in op.reasoning
    client.aclose()


# ── memory_voice ──────────────────────────────────────────────────────
def test_memory_voice_cold_start_returns_abstain_without_llm(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _make_response('{"verdict": "bullish", "confidence": 0.7}')

    client = _make_or_client(handler)
    voice = MemoryVoice(client=client)
    mem = LocalMemory(path=tmp_path / "memory_cold.jsonl")
    # Only 2 rows — below the 3-row threshold.
    mem.append("local_decision", {"action": "act"})
    mem.append("local_decision", {"action": "decline"})

    op = asyncio.run(voice.grade(_healthy_market_state(), mem))
    assert op.verdict == "abstain"
    assert op.reasoning == "cold_start_insufficient_history"
    # Cold-start must NOT have called the LLM.
    assert calls["n"] == 0, "cold-start path should bypass OpenRouter"
    client.aclose()


def test_memory_voice_warm_start_calls_llm(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _make_response(
            json.dumps(
                {
                    "verdict": "bullish",
                    "confidence": 0.65,
                    "reasoning": "5 matching rows, 4 act",
                    "observations": ["1/5 declines, 4/5 acts"],
                }
            )
        )

    client = _make_or_client(handler)
    voice = MemoryVoice(client=client)
    mem = LocalMemory(path=tmp_path / "memory_warm.jsonl")
    # B4 fix: memory_voice reads position_close rows (realized outcomes), NOT
    # local_decision rows. Writing local_decision rows would hit cold-start.
    for i in range(5):
        mem.append(
            "position_close",
            {
                "symbol": "JTO",
                "pnl_pct": 1.5 if i < 4 else -0.5,
                "exit_reason": "take_profit" if i < 4 else "stop_loss",
            },
        )

    op = asyncio.run(voice.grade(_healthy_market_state(), mem))
    assert op.verdict == "bullish"
    assert op.confidence == pytest.approx(0.65)
    assert calls["n"] == 1
    client.aclose()


def test_memory_voice_parse_fail_returns_abstain(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response("not json")

    client = _make_or_client(handler)
    voice = MemoryVoice(client=client)
    mem = LocalMemory(path=tmp_path / "memory_parse.jsonl")
    # B4 fix: must use position_close rows to reach the LLM/parse path.
    # local_decision rows are ignored and would trigger cold-start instead.
    for _ in range(5):
        mem.append("position_close", {"symbol": "JTO", "pnl_pct": 1.0, "exit_reason": "take_profit"})

    op = asyncio.run(voice.grade(_healthy_market_state(), mem))
    assert op.verdict == "abstain"
    assert op.reasoning == "parse_error"
    client.aclose()


# ── risk_voice ────────────────────────────────────────────────────────
def test_risk_voice_daily_trades_veto_skips_llm(tmp_path: Path) -> None:
    """Hard veto rule (a): daily_trades >= MAX_DAILY_TRADES.

    Must NOT call the LLM — deterministic computation only.
    """
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _make_response('{"verdict": "bullish", "confidence": 0.5}')

    client = _make_or_client(handler)
    voice = RiskVoice(client=client)
    mem = LocalMemory(path=tmp_path / "risk_dt.jsonl")
    state = _healthy_market_state(daily_trades=3, max_daily_trades=3)

    op = asyncio.run(voice.grade(state, mem))
    assert op.verdict == "bearish"
    assert op.confidence >= 0.85
    assert "daily_trades_cap_hit" in op.reasoning
    assert calls["n"] == 0, "hard veto must skip OpenRouter call"
    client.aclose()


def test_risk_voice_budget_headroom_veto_skips_llm(tmp_path: Path) -> None:
    """Hard veto rule (b): total_spent_usd within $25 of max_budget_usd."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _make_response('{"verdict": "bullish", "confidence": 0.5}')

    client = _make_or_client(handler)
    voice = RiskVoice(client=client)
    mem = LocalMemory(path=tmp_path / "risk_budget.jsonl")
    state = _healthy_market_state(total_spent_usd=90.0, max_budget_usd=100.0)

    op = asyncio.run(voice.grade(state, mem))
    assert op.verdict == "bearish"
    assert op.confidence >= 0.85
    assert "budget_headroom_low" in op.reasoning
    assert calls["n"] == 0
    client.aclose()


def test_risk_voice_hourly_pnl_veto_skips_llm(tmp_path: Path) -> None:
    """Hard veto rule (c): hourly_pnl_delta <= breaker threshold."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _make_response('{"verdict": "bullish", "confidence": 0.5}')

    client = _make_or_client(handler)
    voice = RiskVoice(client=client)
    mem = LocalMemory(path=tmp_path / "risk_pnl.jsonl")
    state = _healthy_market_state(hourly_pnl_delta=-3.5)

    op = asyncio.run(voice.grade(state, mem))
    assert op.verdict == "bearish"
    assert op.confidence >= 0.85
    assert "hourly_breaker_tripped" in op.reasoning
    assert calls["n"] == 0
    client.aclose()


def test_risk_voice_healthy_floor_returns_bullish_deterministic(tmp_path: Path) -> None:
    """Healthy floor: deterministic band returns bullish/0.7 without any LLM call.

    2026-05-20 founder patch: risk_voice is now fully deterministic (no LLM
    ratify). The LLM was over-vetoing on market sentiment. Deterministic veto
    checks are the correct behavior — market mood reading is chart_analyst's job.
    """
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _make_response(
            json.dumps(
                {
                    "verdict": "bullish",
                    "confidence": 0.72,
                    "reasoning": "floor clean",
                    "observations": ["no veto"],
                }
            )
        )

    client = _make_or_client(handler)
    voice = RiskVoice(client=client)
    mem = LocalMemory(path=tmp_path / "risk_healthy.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "bullish"
    assert op.confidence == pytest.approx(0.70)  # deterministic healthy floor
    assert calls["n"] == 0, "deterministic path must NOT call the LLM"
    client.aclose()


def test_risk_voice_llm_cannot_downgrade_veto(tmp_path: Path) -> None:
    """Even if the LLM tries to downgrade a bearish floor, the override pins bearish."""

    def handler(request: httpx.Request) -> httpx.Response:
        # LLM rebels — returns bullish despite the helper saying bearish.
        return _make_response(
            json.dumps({"verdict": "bullish", "confidence": 0.9, "reasoning": "ignore"})
        )

    client = _make_or_client(handler)
    voice = RiskVoice(client=client)
    mem = LocalMemory(path=tmp_path / "risk_downgrade.jsonl")
    # Force a soft-bearish band (consec_losses >= session_pause is 0.9 — high enough to trip)
    state = _healthy_market_state(consec_losses=2, session_loss_pause_threshold=2)

    op = asyncio.run(voice.grade(state, mem))
    # This hits the deterministic skip-the-LLM branch (>=0.85), so the
    # LLM is never asked. Both paths should pin bearish.
    assert op.verdict == "bearish"
    client.aclose()


def test_compute_risk_band_deterministic_healthy() -> None:
    state = _healthy_market_state()
    band, conf, reason = _compute_risk_band_deterministic(state, memory=None)  # type: ignore[arg-type]
    assert band == "bullish"
    assert conf == pytest.approx(0.70)
    assert reason == "operational_floor_clean"


def test_compute_risk_band_deterministic_malformed() -> None:
    band, conf, reason = _compute_risk_band_deterministic("not a dict", memory=None)  # type: ignore[arg-type]
    assert band == "abstain"
    assert conf == 0.0
    assert reason == "malformed_risk_state"


# ── coordinator ───────────────────────────────────────────────────────
def test_coordinator_risk_veto_first() -> None:
    """Rule 1: risk veto fires regardless of chart + memory."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "bullish", 0.8),
        _opinion("risk_voice", "bearish", 0.9),
    ]
    action, reason = coordinator(opinions)
    assert action == "decline"
    assert reason == "risk_veto"


def test_coordinator_risk_bearish_below_threshold_does_not_veto() -> None:
    """Rule 1: risk bearish at conf < 0.8 does NOT veto."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),  # clears the 0.85 normal floor
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bearish", 0.5),  # below veto threshold
    ]
    action, reason = coordinator(opinions)
    # Should fall through Rule 1; chart is bullish above floor so it acts.
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_chart_not_bullish_declines() -> None:
    """Rule 2: chart verdict != bullish declines."""
    opinions = [
        _opinion("chart_analyst", "bearish", 0.9),
        _opinion("memory_voice", "bullish", 0.8),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions)
    assert action == "decline"
    assert reason == "chart_below_threshold"


def test_coordinator_chart_confidence_below_threshold_declines() -> None:
    """Rule 3 (normal floor): chart bullish but confidence < 0.85 declines.

    Locks the v2 floor (raised from 0.6 in B6): a 0.8 chart that would
    have acted under v1 now declines — only the cleanest momentum passes.
    """
    opinions = [
        _opinion("chart_analyst", "bullish", 0.8),  # between old 0.6 and new 0.85
        _opinion("memory_voice", "bullish", 0.8),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions)
    assert action == "decline"
    assert reason == "chart_below_threshold"


def test_coordinator_memory_contradicts_declines() -> None:
    """Rule 4: memory bearish at >= 0.6 declines (chart must first clear floor)."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "bearish", 0.7),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions)
    assert action == "decline"
    assert reason == "memory_contradicts"


def test_coordinator_memory_bearish_below_threshold_passes() -> None:
    """Rule 4: memory bearish at conf < 0.6 does NOT decline."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "bearish", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions)
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_memory_abstain_passes() -> None:
    """Memory abstain (cold start) should NOT block."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "abstain", 0.0),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions)
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_all_aligned_acts() -> None:
    """Else branch: all gates pass (chart above 0.85 floor) → act."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "neutral", 0.6),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions)
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_missing_chart_voice_declines() -> None:
    """Defensive default: no chart_analyst opinion -> immediate decline."""
    opinions = [
        _opinion("memory_voice", "bullish", 0.9),
        _opinion("risk_voice", "bullish", 0.9),
    ]
    action, reason = coordinator(opinions)
    assert action == "decline"
    assert reason == "chart_voice_missing"


def test_coordinator_missing_memory_voice_falls_through() -> None:
    """Missing memory voice should be treated as abstain — rule 4 does not fire."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions)
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_missing_risk_voice_does_not_veto() -> None:
    """Missing risk voice should be treated as abstain — rule 1 cannot veto."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "neutral", 0.5),
    ]
    action, reason = coordinator(opinions)
    assert action == "act"
    assert reason == "all_voices_aligned"


# ── regime_analyst ───────────────────────────────────────────────────


def _uptrend_candles(n: int = 60, start: float = 1.0, step: float = 0.02) -> list[dict]:
    """Ascending price candles: close near high, higher-highs each bar.
    Produces high +DI (buyers consistently winning each bar move).
    """
    candles = []
    price = start
    for i in range(n):
        open_ = price
        high = price + step * 1.5
        low = price - step * 0.2   # shallow pullbacks — +DI dominates
        close = price + step * 1.2
        candles.append({"open": open_, "high": high, "low": low, "close": close, "volume": 10_000.0})
        price = close
    return candles


def _downtrend_candles(n: int = 60, start: float = 3.0, step: float = 0.02) -> list[dict]:
    """Descending price candles: close near low, lower-lows each bar.
    Produces high -DI (sellers consistently winning each bar move).
    """
    candles = []
    price = start
    for i in range(n):
        open_ = price
        high = price + step * 0.2   # shallow bounces — -DI dominates
        low = price - step * 1.5
        close = price - step * 1.2
        candles.append({"open": open_, "high": high, "low": low, "close": close, "volume": 10_000.0})
        price = close
    return candles


def _chop_candles(n: int = 60, center: float = 2.0, half_range: float = 0.05) -> list[dict]:
    """Alternating up/down bars around a fixed centre — low net directional movement.
    Produces low ADX (both +DM and -DM stay small after netting out).
    """
    candles = []
    price = center
    direction = 1
    for i in range(n):
        move = half_range * 0.5 * direction
        open_ = price
        high = price + half_range * 0.3
        low = price - half_range * 0.3
        close = price + move
        candles.append({"open": open_, "high": high, "low": low, "close": close, "volume": 10_000.0})
        price = close
        direction *= -1
    return candles


def test_regime_analyst_uptrend_returns_bullish(tmp_path: Path) -> None:
    """Uptrend candles (high ADX, +DI > -DI) → bullish verdict."""
    voice = RegimeAnalystVoice()
    mem = LocalMemory(path=tmp_path / "regime_up.jsonl")
    candles = _uptrend_candles(60)
    state = _healthy_market_state(ohlcv_5m=candles)
    # Pass candles both ways (regime reads market_state["candles"])
    state["candles"] = candles

    op = asyncio.run(voice.grade(state, mem))

    assert op.verdict == "bullish", f"expected bullish uptrend, got {op.verdict}: {op.reasoning}"
    assert op.confidence > 0.5
    assert "uptrend" in op.reasoning.lower() or "momentum permitted" in op.reasoning.lower()


def test_regime_analyst_downtrend_returns_bearish(tmp_path: Path) -> None:
    """Downtrend candles (high ADX, -DI > +DI) → bearish verdict.

    This is the S41 regression guard: before the direction fix, strong
    downtrends were mis-labelled 'bullish' (momentum permitted). After the
    fix, -DI > +DI must produce 'bearish' (longs blocked).
    """
    voice = RegimeAnalystVoice()
    mem = LocalMemory(path=tmp_path / "regime_down.jsonl")
    candles = _downtrend_candles(60)
    state = _healthy_market_state(ohlcv_5m=candles)
    state["candles"] = candles

    op = asyncio.run(voice.grade(state, mem))

    assert op.verdict == "bearish", (
        f"S41 regression: downtrend must return bearish (longs blocked), "
        f"got {op.verdict}: {op.reasoning}"
    )
    assert op.confidence > 0.5
    assert "downtrend" in op.reasoning.lower() or "longs blocked" in op.reasoning.lower()


def test_regime_analyst_chop_returns_bearish(tmp_path: Path) -> None:
    """Chop candles (low ADX) → bearish verdict (momentum -EV)."""
    voice = RegimeAnalystVoice()
    mem = LocalMemory(path=tmp_path / "regime_chop.jsonl")
    candles = _chop_candles(60)
    state = _healthy_market_state(ohlcv_5m=candles)
    state["candles"] = candles

    op = asyncio.run(voice.grade(state, mem))

    assert op.verdict == "bearish", f"expected bearish chop, got {op.verdict}: {op.reasoning}"
    assert "chop" in op.reasoning.lower() or "momentum" in op.reasoning.lower()


def test_regime_analyst_insufficient_bars_abstains(tmp_path: Path) -> None:
    """< 30 bars → abstain (unchanged from pre-fix behaviour)."""
    voice = RegimeAnalystVoice()
    mem = LocalMemory(path=tmp_path / "regime_short.jsonl")
    candles = _uptrend_candles(20)
    state = _healthy_market_state(ohlcv_5m=candles)
    state["candles"] = candles

    op = asyncio.run(voice.grade(state, mem))

    assert op.verdict == "abstain"
    assert "insufficient_history" in op.reasoning


# ── coordinator: B6 regime gate-modulator ─────────────────────────────
def test_coordinator_chop_raises_floor_declines() -> None:
    """B6: a confirmed-chop regime raises the chart floor to 0.92.

    A 0.88 chart that acts in trend/neutral must DECLINE in chop —
    breakout is -EV in chop, so we demand only the cleanest setups.
    """
    opinions = [
        _opinion("chart_analyst", "bullish", 0.88),
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
        _opinion("regime_analyst", "bearish", 0.7),  # confident chop
    ]
    action, reason = coordinator(opinions)
    assert action == "decline"
    assert reason == "chop_below_high_bar"


def test_coordinator_chop_high_conviction_acts() -> None:
    """B6: a chop regime still ACTS when chart clears the 0.92 chop floor."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.95),
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
        _opinion("regime_analyst", "bearish", 0.7),  # confident chop
    ]
    action, reason = coordinator(opinions)
    assert action == "act"
    assert reason == "chop_high_conviction"


def test_coordinator_trend_uses_normal_floor_acts() -> None:
    """B6: a trend regime uses the normal 0.85 floor — 0.88 acts."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.88),
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
        _opinion("regime_analyst", "bullish", 0.7),  # trend
    ]
    action, reason = coordinator(opinions)
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_downtrend_raises_floor_same_as_chop() -> None:
    """S41 regression guard: a downtrend (regime bearish from -DI>+DI) raises
    the chart floor exactly like chop. Both chop and downtrend emit
    regime.verdict='bearish', so the coordinator path is identical.
    A 0.88 chart must DECLINE even though the regime call came from a
    strong downtrend, not from low-ADX chop.
    """
    opinions = [
        _opinion("chart_analyst", "bullish", 0.88),
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
        _opinion("regime_analyst", "bearish", 0.75),  # could be chop OR downtrend
    ]
    action, reason = coordinator(opinions)
    assert action == "decline"
    assert reason == "chop_below_high_bar"


def test_coordinator_unconfident_chop_uses_normal_floor() -> None:
    """B6: regime must be >= 0.6 confident it's chop to raise the bar.

    A low-confidence chop call (0.4) does NOT raise the floor — 0.88 acts
    on the normal 0.85 floor.
    """
    opinions = [
        _opinion("chart_analyst", "bullish", 0.88),
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
        _opinion("regime_analyst", "bearish", 0.4),  # not confident enough
    ]
    action, reason = coordinator(opinions)
    assert action == "act"
    assert reason == "all_voices_aligned"


# ── bootstrap ─────────────────────────────────────────────────────────
def test_bootstrap_raises_when_env_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """build_local_panel must propagate OpenRouterConfigError so the bot's
    broad-except picks it up and degrades to no-panel mode."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from bootstrap import build_local_panel
    from llm_client import OpenRouterConfigError

    mem = LocalMemory(path=tmp_path / "bs_unset.jsonl")
    with pytest.raises(OpenRouterConfigError, match="OPENROUTER_API_KEY"):
        build_local_panel(memory=mem)


def test_bootstrap_returns_panel_when_env_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With OPENROUTER_API_KEY set, bootstrap returns a fully-wired panel."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-bootstrap")
    from bootstrap import build_local_panel

    mem = LocalMemory(path=tmp_path / "bs_set.jsonl")
    panel = build_local_panel(memory=mem)
    assert isinstance(panel, LocalPanel)
    # Four voices (B3 added regime_analyst): chart_analyst, memory_voice,
    # risk_voice, regime_analyst.
    names = [v.voice_name for v in panel._voices]
    assert names == ["chart_analyst", "memory_voice", "risk_voice", "regime_analyst"]
    # Coordinator is the imported function.
    assert panel._coordinator is coordinator
