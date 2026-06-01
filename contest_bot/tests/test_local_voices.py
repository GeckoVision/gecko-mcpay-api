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
from voices.strategist_voice import _has_gradeable_indicators  # noqa: E402
from voices import coordinator_rules as _cr  # noqa: E402
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


def test_memory_voice_filters_cross_instrument(tmp_path: Path) -> None:
    """S24-S fix 2b: memory_voice must filter ledger rows to the current
    instrument before computing cold-start floor. Without the filter, a
    losing WIF trade poisoned a PYTH grade — the universe-summed bearish
    bias was being attributed to whichever symbol was currently graded.

    Setup: ledger has 3 WIF closes (all losses) but caller is grading
    PYTH. Voice MUST abstain (cold start for PYTH), NOT call the LLM
    with poisoned cross-instrument bearish history.
    """
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _make_response('{"verdict": "bearish", "confidence": 0.6}')

    client = _make_or_client(handler)
    voice = MemoryVoice(client=client)
    mem = LocalMemory(path=tmp_path / "memory_xinstr.jsonl")
    # 3 WIF losses — pre-fix, this would clear the 3-row cold-start
    # floor for ANY grade (cross-instrument bleed). Post-fix, PYTH still
    # sees zero rows and abstains.
    for pnl_pct in (-0.5, -0.4, -0.6):
        mem.append(
            "position_close",
            {"symbol": "WIF-USDC", "pnl_pct": pnl_pct, "exit_reason": "stop_loss"},
        )

    pyth_state = _healthy_market_state(instrument="PYTH", symbol="PYTH-USDC")
    op = asyncio.run(voice.grade(pyth_state, mem))
    assert op.verdict == "abstain", (
        f"PYTH should cold-start despite WIF history; got {op.verdict}"
    )
    assert op.reasoning == "cold_start_insufficient_history"
    assert calls["n"] == 0, "instrument-filter must short-circuit the LLM call"
    client.aclose()


def test_memory_voice_same_instrument_still_fires(tmp_path: Path) -> None:
    """Companion to _filters_cross_instrument: when the ledger DOES
    contain enough same-symbol history, the voice should warm-start and
    call the LLM. Guards against the filter becoming a permanent gag.
    """
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _make_response(
            json.dumps({"verdict": "bullish", "confidence": 0.65})
        )

    client = _make_or_client(handler)
    voice = MemoryVoice(client=client)
    mem = LocalMemory(path=tmp_path / "memory_same.jsonl")
    # 2 noise rows on other symbols (should be filtered out) + 4 PYTH
    # rows (warm-start fuel after filter).
    mem.append("position_close", {"symbol": "WIF-USDC", "pnl_pct": -0.5})
    mem.append("position_close", {"symbol": "SOL-USDC", "pnl_pct": +0.8})
    for _ in range(4):
        mem.append(
            "position_close",
            {"symbol": "PYTH-USDC", "pnl_pct": 1.2, "exit_reason": "take_profit"},
        )

    pyth_state = _healthy_market_state(instrument="PYTH", symbol="PYTH-USDC")
    op = asyncio.run(voice.grade(pyth_state, mem))
    assert op.verdict == "bullish"
    assert calls["n"] == 1
    client.aclose()


def test_strategist_gateable_with_adx_only(tmp_path: Path) -> None:
    """S24-S fix 2c: _has_gradeable_indicators should return True when
    ADX is present, even if other indicators (RSI/EMA/MFI) computed
    None on a noisy bar. Prior gate required ADX AND RSI; the AND
    pushed the strategist to 41% abstain in production. This test
    pins the relaxed contract: ADX-only.
    """
    # Healthy 30 bars → indicators module will compute ADX cleanly.
    state = _healthy_market_state()
    assert _has_gradeable_indicators(state), (
        "Healthy 30-bar state with ADX should be gradeable"
    )


def test_strategist_abstains_with_too_few_bars(tmp_path: Path) -> None:
    """Companion: fewer than 24 bars → not gradeable (ADX needs ~28
    smoothing bars). Guards against the gate becoming permissive enough
    to grade synthetic / partial bar sets."""
    state = _healthy_market_state()
    # Truncate to 10 bars
    state["ohlcv_5m"] = state["ohlcv_5m"][:10]
    assert not _has_gradeable_indicators(state)


def test_memory_voice_parse_fail_returns_abstain(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response("not json")

    client = _make_or_client(handler)
    voice = MemoryVoice(client=client)
    mem = LocalMemory(path=tmp_path / "memory_parse.jsonl")
    # B4 fix: must use position_close rows to reach the LLM/parse path.
    # local_decision rows are ignored and would trigger cold-start instead.
    for _ in range(5):
        mem.append(
            "position_close", {"symbol": "JTO", "pnl_pct": 1.0, "exit_reason": "take_profit"}
        )

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
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason == "risk_veto"


def test_coordinator_risk_bearish_below_threshold_does_not_veto() -> None:
    """Rule 1: risk bearish at conf < 0.8 does NOT veto."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),  # clears the 0.85 normal floor
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bearish", 0.5),  # below veto threshold
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
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
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
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
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason == "chart_below_threshold"


def test_coordinator_memory_contradicts_declines() -> None:
    """Rule 4: memory bearish at >= 0.6 declines (chart must first clear floor)."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "bearish", 0.7),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason == "memory_contradicts"


def test_coordinator_memory_bearish_below_threshold_passes() -> None:
    """Rule 4: memory bearish at conf < 0.6 does NOT decline."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "bearish", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_memory_abstain_passes() -> None:
    """Memory abstain (cold start) should NOT block."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "abstain", 0.0),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_all_aligned_acts() -> None:
    """Else branch: all gates pass (chart above 0.85 floor) → act."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "neutral", 0.6),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_missing_chart_voice_declines() -> None:
    """Defensive default: no chart_analyst opinion -> immediate decline."""
    opinions = [
        _opinion("memory_voice", "bullish", 0.9),
        _opinion("risk_voice", "bullish", 0.9),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason == "chart_voice_missing"


def test_coordinator_missing_memory_voice_falls_through() -> None:
    """Missing memory voice should be treated as abstain — rule 4 does not fire."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_coordinator_missing_risk_voice_does_not_veto() -> None:
    """Missing risk voice should be treated as abstain — rule 1 cannot veto."""
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "neutral", 0.5),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"
    assert reason == "all_voices_aligned"


# ── coordinator: weighted_quorum mode (Variant G, S24-O) ──────────────
#
# Six tests covering the major branches of the Variant G dispatch path.
# Each test sets GECKO_COORDINATOR_MODE=weighted_quorum via monkeypatch
# and restores legacy default on teardown (pytest monkeypatch handles
# this automatically per-test).
#
# Empirical tuple validation per S24-O design doc:
#   1B/2S/2N/0A: score = 2-2+2 = 2  → ACT (clears threshold 2)
#   2B/2S/1N/0A: score = 4-2+1 = 3  → ACT
#   2B/1S/2N/0A: score = 4-1+2 = 5  → ACT (strong)
#   3B/1S/1N/0A: score = 6-1+1 = 6  → ACT (obvious)
#   1B/3S/0N/1A: score = 2-3+0 = -1 → DECLINE (and 3 bearish triggers veto)
#   1B/2S/0N/2A: score = 2-2+0 = 0  → DECLINE
def test_coordinator_weighted_quorum_acts_on_mixed_bullish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1B/2S/2N/0A tuple (score 2) clears the default threshold under Variant G.

    This is the structurally-2-voice case the legacy chain declines because
    chart_analyst (the sole positive signal) is neutral. Variant G unblocks
    it by counting neutral as +1 and clearing on aggregate.
    """
    monkeypatch.setenv("GECKO_COORDINATOR_MODE", "weighted_quorum")
    monkeypatch.setenv("GECKO_TREAT_UNKNOWN_1H_AS_ADVERSE", "0")
    opinions = [
        _opinion("chart_analyst", "neutral", 0.5),  # +1
        _opinion("strategist_voice", "bearish", 0.7),  # -1
        _opinion("regime_analyst", "bearish", 0.6),  # -1
        _opinion("risk_voice", "bullish", 0.7),  # +2
        _opinion("memory_voice", "neutral", 0.4),  # +1
    ]
    # score = 1 - 1 - 1 + 2 + 1 = 2, threshold = 2 → act
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"
    assert reason == "weighted_quorum"


def test_coordinator_weighted_quorum_declines_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1B/2S/0N/2A tuple (score 0) declines — net signal not positive.

    1 bullish + 2 bearish + 2 abstain = 2 - 2 + 0 = 0 < threshold 2.
    """
    monkeypatch.setenv("GECKO_COORDINATOR_MODE", "weighted_quorum")
    monkeypatch.setenv("GECKO_TREAT_UNKNOWN_1H_AS_ADVERSE", "0")
    opinions = [
        _opinion("chart_analyst", "abstain", 0.0),  # 0
        _opinion("strategist_voice", "bearish", 0.7),  # -1
        _opinion("regime_analyst", "bearish", 0.6),  # -1
        _opinion("risk_voice", "bullish", 0.7),  # +2
        _opinion("memory_voice", "abstain", 0.0),  # 0
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason == "weighted_quorum_below_threshold"


def test_coordinator_weighted_quorum_risk_veto_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Risk hard-veto must fire even when score is high under Variant G.

    Safety always wins. A strongly-positive aggregate score (3 bullish
    voices, score +6) must still decline when risk is bearish at ≥0.8.
    """
    monkeypatch.setenv("GECKO_COORDINATOR_MODE", "weighted_quorum")
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("strategist_voice", "bullish", 0.8),
        _opinion("regime_analyst", "bullish", 0.7),
        _opinion("risk_voice", "bearish", 0.9),  # risk veto
        _opinion("memory_voice", "neutral", 0.5),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason == "risk_veto"


def test_coordinator_weighted_quorum_missing_chart_declines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive: missing chart_analyst declines (parity with legacy)."""
    monkeypatch.setenv("GECKO_COORDINATOR_MODE", "weighted_quorum")
    opinions = [
        _opinion("strategist_voice", "bullish", 0.9),
        _opinion("regime_analyst", "bullish", 0.9),
        _opinion("risk_voice", "bullish", 0.7),
        _opinion("memory_voice", "bullish", 0.9),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason == "chart_voice_missing"


def test_coordinator_weighted_quorum_three_bearish_veto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bearish-count veto fires when ≥3 voices are bearish, regardless of score.

    Even if risk_voice is strongly bullish (+2) and chart is bullish (+2),
    three bearish votes (score = 4 - 3 = 1) means the panel is structurally
    dissenting. Decline.
    """
    monkeypatch.setenv("GECKO_COORDINATOR_MODE", "weighted_quorum")
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),  # +2
        _opinion("strategist_voice", "bearish", 0.8),  # -1
        _opinion("regime_analyst", "bearish", 0.7),  # -1
        _opinion("memory_voice", "bearish", 0.7),  # -1
        _opinion("risk_voice", "bullish", 0.7),  # +2
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason == "bearish_quorum_veto"


def test_coordinator_weighted_quorum_1h_adverse_bonus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1h-adverse raises the act threshold by +1 instead of imposing a hard floor.

    A 1B/2S/2N tuple scores 2. Under TREND-UP that clears threshold 2 (act).
    Under 1h CHOP threshold becomes 3 → same tuple declines. A clean
    2B/1S/2N tuple (score 5) acts even under 1h CHOP (clears 3) and surfaces
    the adverse rule label.
    """
    monkeypatch.setenv("GECKO_COORDINATOR_MODE", "weighted_quorum")
    # Borderline tuple: score 2, declines under CHOP because threshold is 3.
    borderline = [
        _opinion("chart_analyst", "neutral", 0.5),  # +1
        _opinion("strategist_voice", "bearish", 0.7),  # -1
        _opinion("regime_analyst", "bearish", 0.6),  # -1
        _opinion("risk_voice", "bullish", 0.7),  # +2
        _opinion("memory_voice", "neutral", 0.4),  # +1
    ]
    action, reason = coordinator(borderline, regime_1h="CHOP")
    assert action == "decline"
    assert reason == "weighted_quorum_below_threshold"

    # Strong tuple: 2B/1S/2N → score 5, clears threshold 3 even in CHOP.
    strong = [
        _opinion("chart_analyst", "bullish", 0.9),  # +2
        _opinion("strategist_voice", "bullish", 0.8),  # +2
        _opinion("regime_analyst", "bearish", 0.7),  # -1
        _opinion("risk_voice", "neutral", 0.6),  # +1
        _opinion("memory_voice", "neutral", 0.5),  # +1
    ]
    action, reason = coordinator(strong, regime_1h="CHOP")
    assert action == "act"
    assert reason == "weighted_quorum_adverse"


def test_coordinator_legacy_remains_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset GECKO_COORDINATOR_MODE → legacy path runs.

    Belt-and-suspenders: production must not flip to Variant G implicitly.
    A 2N/2N/2N panel with bullish chart at 0.9 acts under legacy
    (all_voices_aligned); under Variant G it would also act but with a
    DIFFERENT reason ("weighted_quorum"). The reason string is the
    discriminator.
    """
    monkeypatch.delenv("GECKO_COORDINATOR_MODE", raising=False)
    opinions = [
        _opinion("chart_analyst", "bullish", 0.9),
        _opinion("memory_voice", "neutral", 0.6),
        _opinion("risk_voice", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"
    assert reason == "all_voices_aligned"  # legacy label, NOT "weighted_quorum"


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
        low = price - step * 0.2  # shallow pullbacks — +DI dominates
        close = price + step * 1.2
        candles.append(
            {"open": open_, "high": high, "low": low, "close": close, "volume": 10_000.0}
        )
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
        high = price + step * 0.2  # shallow bounces — -DI dominates
        low = price - step * 1.5
        close = price - step * 1.2
        candles.append(
            {"open": open_, "high": high, "low": low, "close": close, "volume": 10_000.0}
        )
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
        candles.append(
            {"open": open_, "high": high, "low": low, "close": close, "volume": 10_000.0}
        )
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
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
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
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
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
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
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
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
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
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"
    assert reason == "all_voices_aligned"


def test_strict_multi_tf_blocks_dual_adverse(monkeypatch: pytest.MonkeyPatch) -> None:
    opinions = [
        _opinion("chart_analyst", "bullish", 0.95),
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
        _opinion("regime_analyst", "bearish", 0.7),
    ]
    action, reason = coordinator(opinions, regime_1h="CHOP")
    assert action == "decline"
    assert reason == "strict_multi_tf_adverse"

    monkeypatch.setenv("GECKO_STRICT_MULTI_TF", "0")
    action2, reason2 = coordinator(opinions, regime_1h="CHOP")
    assert action2 == "act"
    assert reason2 in ("chop_high_conviction", "1h_adverse_high_conviction")


def test_unknown_1h_treated_adverse_by_default() -> None:
    opinions = [
        _opinion("chart_analyst", "bullish", 0.88),
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
        _opinion("regime_analyst", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions, regime_1h=None)
    assert action == "decline"
    assert reason == "1h_adverse_below_high_bar"


def test_unknown_1h_legacy_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GECKO_TREAT_UNKNOWN_1H_AS_ADVERSE", "0")
    opinions = [
        _opinion("chart_analyst", "bullish", 0.88),
        _opinion("memory_voice", "neutral", 0.5),
        _opinion("risk_voice", "bullish", 0.7),
        _opinion("regime_analyst", "bullish", 0.7),
    ]
    action, reason = coordinator(opinions, regime_1h=None)
    assert action == "act"
    assert reason == "all_voices_aligned"


# ── CHOP indicator unit tests ─────────────────────────────────────────

import indicators as _ind  # noqa: E402  (already importable from the sys.path insert above)


def _make_candles(closes: list[float]) -> list[dict]:
    """Minimal candle list from a close series (high/low ±0.1% of close)."""
    return [
        {
            "open": c,
            "high": c * 1.001,
            "low": c * 0.999,
            "close": c,
            "volume": 10_000.0,
        }
        for c in closes
    ]


def test_chop_trending_is_low() -> None:
    """Monotonically rising prices produce a CHOP value < 61.8 (trending)."""
    closes = [1.0 + i * 0.02 for i in range(50)]
    candles = _make_candles(closes)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    series = _ind.chop(highs, lows, closes, n=14)
    # Last value must be computed (not None)
    last = next((v for v in reversed(series) if v is not None), None)
    assert last is not None, "chop series returned all None for trending data"
    assert last < 61.8, f"expected chop < 61.8 for trend, got {last:.2f}"


def test_chop_sideways_is_high() -> None:
    """Oscillating prices that stay within a tight range produce CHOP > 38.2.

    True chop: many bars each covering nearly the full session range (high TR
    per bar, but range_max - range_min stays roughly constant). Use
    _chop_candles which alternates direction within a fixed band — this
    maximises sumTR / (H_max - L_min) ratio → high CHOP.
    """
    candles = _chop_candles(50)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    series = _ind.chop(highs, lows, closes, n=14)
    last = next((v for v in reversed(series) if v is not None), None)
    assert last is not None, "chop series returned all None for sideways data"
    assert last > 38.2, f"expected chop > 38.2 for sideways, got {last:.2f}"


def test_chop_warmup_returns_none() -> None:
    """Fewer than n+1 candles returns all None (warmup window)."""
    closes = [1.0] * 14  # exactly n candles — series[n] doesn't exist
    candles = _make_candles(closes)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    series = _ind.chop(highs, lows, closes, n=14)
    assert all(v is None for v in series), "expected all None during warmup"


def test_compute_latest_includes_chop() -> None:
    """compute_latest returns a 'chop' key for a sufficiently long candle list."""
    closes = [1.0 + i * 0.01 for i in range(50)]
    candles = [
        {"open": c, "high": c * 1.001, "low": c * 0.999, "close": c, "volume": 1000.0}
        for c in closes
    ]
    snap = _ind.compute_latest(candles)
    assert "chop" in snap, "compute_latest must include 'chop' key"
    # With 50 bars and n=14 the value should be computed (not None)
    assert snap["chop"] is not None, "chop should be non-None for 50-bar series"


def test_regime_analyst_reasoning_includes_bb_and_chop(tmp_path: Path) -> None:
    """RegimeAnalystVoice reasoning string must mention bb_width and chop labels."""
    voice = RegimeAnalystVoice()
    mem = LocalMemory(path=tmp_path / "regime_bb_chop.jsonl")
    candles = _uptrend_candles(60)
    state = _healthy_market_state(ohlcv_5m=candles)
    state["candles"] = candles

    op = asyncio.run(voice.grade(state, mem))

    # Both bb_width and chop labels must appear in the reasoning string.
    assert "bb_width" in op.reasoning, f"bb_width missing from reasoning: {op.reasoning}"
    assert "chop=" in op.reasoning, f"chop= missing from reasoning: {op.reasoning}"


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
    # Five voices (S20-1 added strategist_voice): chart_analyst, memory_voice,
    # risk_voice, regime_analyst, strategist_voice.
    names = [v.voice_name for v in panel._voices]
    assert names == [
        "chart_analyst",
        "memory_voice",
        "risk_voice",
        "regime_analyst",
        "strategist_voice",
    ]
    # Coordinator is the imported function.
    assert panel._coordinator is coordinator


# ───────────────────────────────────────────────────────────────────────
# S24-V — Quant tightening gates (env-gated, default OFF)
# ───────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
def _wq_env(monkeypatch: pytest.MonkeyPatch):
    """Activate weighted_quorum coordinator for the S24-V tests. The S24-V
    gates only live in the weighted_quorum branch; legacy coordinator is
    intentionally untouched."""
    monkeypatch.setenv("GECKO_COORDINATOR_MODE", "weighted_quorum")
    yield


def _wq_aligned_opinions(non_risk_bullish: int) -> list[VoiceOpinion]:
    """Build a 5-voice opinion set with exactly `non_risk_bullish` bullish
    voices among the non-risk voices. risk_voice is always bullish (the
    constant-bull yes-man the S24-V Gate 1 is meant to discount)."""
    # Pool of non-risk voices: chart_analyst, memory_voice,
    # regime_analyst, strategist_voice. Fill `non_risk_bullish` with
    # bullish, rest with neutral (so the bearish-count veto doesn't fire).
    non_risk = ["chart_analyst", "memory_voice", "regime_analyst", "strategist_voice"]
    ops = [_opinion("risk_voice", "bullish", 0.7)]
    for i, name in enumerate(non_risk):
        verdict = "bullish" if i < non_risk_bullish else "neutral"
        ops.append(_opinion(name, verdict, 0.65))
    return ops


def test_s24v_non_risk_bullish_gate_off_by_default(
    _wq_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default behavior: 1 non-risk bullish + risk bullish → score 2+2+3=7
    → act. Gate is OFF unless GECKO_QUORUM_REQUIRE_NON_RISK_BULLISH=1."""
    monkeypatch.delenv("GECKO_QUORUM_REQUIRE_NON_RISK_BULLISH", raising=False)
    # 1 non-risk bullish, others neutral, no bearish — should act.
    opinions = _wq_aligned_opinions(non_risk_bullish=1)
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"


def test_s24v_non_risk_bullish_gate_blocks_when_below_min(
    _wq_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With gate ON: 1 non-risk bullish < min 2 → decline with the
    discriminating reason label, even though weighted score would act."""
    monkeypatch.setenv("GECKO_QUORUM_REQUIRE_NON_RISK_BULLISH", "1")
    monkeypatch.setenv("GECKO_QUORUM_NON_RISK_BULLISH_MIN", "2")
    opinions = _wq_aligned_opinions(non_risk_bullish=1)
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason is not None
    assert reason.startswith("non_risk_bullish_below_min:")
    assert "_lt_2" in reason


def test_s24v_non_risk_bullish_gate_allows_when_met(
    _wq_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With gate ON: 2 non-risk bullish ≥ min 2 → gate passes; the rest
    of the quorum logic continues and lets it act."""
    monkeypatch.setenv("GECKO_QUORUM_REQUIRE_NON_RISK_BULLISH", "1")
    monkeypatch.setenv("GECKO_QUORUM_NON_RISK_BULLISH_MIN", "2")
    opinions = _wq_aligned_opinions(non_risk_bullish=2)
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "act"


def test_s24v_circuit_breaker_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reporting closes is always safe (deque keeps warm) but the
    breaker itself doesn't fire without GECKO_CIRCUIT_BREAKER=1."""
    _cr.reset_circuit_breaker_state()
    monkeypatch.delenv("GECKO_CIRCUIT_BREAKER", raising=False)
    for _ in range(5):
        _cr.report_close(0.05, "flat_stall_exit")
    broken, reason = _cr._circuit_broken_now()
    assert broken is False
    assert reason is None


def test_s24v_circuit_breaker_trips_on_5x_flat_stall_near_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5 flat_stall closes with mean |pnl_pct| < threshold trips the
    breaker. Subsequent _circuit_broken_now calls report `active`."""
    _cr.reset_circuit_breaker_state()
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER", "1")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_LOOKBACK", "5")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_PNL_THRESHOLD", "0.10")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_SUSPEND_MIN", "240")
    for pnl in (0.05, -0.07, 0.02, -0.04, 0.03):  # mean ~ -0.002, |mean| < 0.10
        _cr.report_close(pnl, "flat_stall_exit")
    broken, reason = _cr._circuit_broken_now()
    assert broken is True
    assert reason is not None
    assert reason.startswith("circuit_breaker_tripped:")
    # Second call: still suspended, different reason format.
    broken2, reason2 = _cr._circuit_broken_now()
    assert broken2 is True
    assert reason2 is not None
    assert reason2.startswith("circuit_breaker_active:")


def test_s24v_circuit_breaker_skips_when_mean_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5 flat_stall closes but mean |pnl_pct| ≥ threshold → NOT tripped.
    These are stall exits but the bot is actually losing money — that's
    a different problem; the breaker only catches dead-zone grind."""
    _cr.reset_circuit_breaker_state()
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER", "1")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_LOOKBACK", "5")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_PNL_THRESHOLD", "0.10")
    for pnl in (-0.3, -0.4, -0.2, -0.3, -0.5):  # mean ~ -0.34, |mean| >> 0.10
        _cr.report_close(pnl, "flat_stall_exit")
    broken, _ = _cr._circuit_broken_now()
    assert broken is False


def test_s24v_circuit_breaker_skips_when_non_stall_in_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with the breaker enabled, a single non-flat-stall exit
    (take_profit, stop_loss) in the lookback window breaks the all-stall
    precondition → breaker does not trip."""
    _cr.reset_circuit_breaker_state()
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER", "1")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_LOOKBACK", "5")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_PNL_THRESHOLD", "0.10")
    _cr.report_close(0.05, "flat_stall_exit")
    _cr.report_close(-0.04, "flat_stall_exit")
    _cr.report_close(2.0, "take_profit")  # breaks the all-stall window
    _cr.report_close(0.03, "flat_stall_exit")
    _cr.report_close(-0.06, "flat_stall_exit")
    broken, _ = _cr._circuit_broken_now()
    assert broken is False


def test_s24v_circuit_breaker_short_window_doesnt_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fewer than lookback closes → breaker doesn't have enough data."""
    _cr.reset_circuit_breaker_state()
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER", "1")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_LOOKBACK", "5")
    for _ in range(3):  # < 5 lookback
        _cr.report_close(0.02, "flat_stall_exit")
    broken, _ = _cr._circuit_broken_now()
    assert broken is False


def test_s24v_circuit_breaker_blocks_coordinator_when_tripped(
    _wq_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When breaker is tripped, weighted_quorum coordinator declines
    even on a clean act-quorum. This is the load-bearing wire — the
    coordinator must short-circuit on the breaker."""
    _cr.reset_circuit_breaker_state()
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER", "1")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_LOOKBACK", "5")
    monkeypatch.setenv("GECKO_CIRCUIT_BREAKER_PNL_THRESHOLD", "0.10")
    for pnl in (0.05, -0.07, 0.02, -0.04, 0.03):
        _cr.report_close(pnl, "flat_stall_exit")
    # Otherwise-act-eligible quorum.
    opinions = _wq_aligned_opinions(non_risk_bullish=3)
    action, reason = coordinator(opinions, regime_1h="TREND-UP")
    assert action == "decline"
    assert reason is not None
    assert reason.startswith("circuit_breaker_")  # tripped or active
    _cr.reset_circuit_breaker_state()


def test_s24v_report_close_never_raises_on_garbage() -> None:
    """report_close MUST swallow type errors / nonsense inputs — the
    bot's close path can't tolerate a coordinator helper raising."""
    _cr.reset_circuit_breaker_state()
    # All of these should silently no-op rather than raise.
    _cr.report_close("not a float", "flat_stall_exit")  # type: ignore[arg-type]
    _cr.report_close(None, "flat_stall_exit")  # type: ignore[arg-type]
    _cr.report_close(0.05, None)  # type: ignore[arg-type]
    # Sanity: deque still works for valid input afterward.
    _cr.report_close(0.05, "flat_stall_exit")
    assert len(_cr._RECENT_CLOSES) >= 1


# ───────────────────────────────────────────────────────────────────────
# S24-X — Per-voice model env-resolution
# ───────────────────────────────────────────────────────────────────────


from voices.model_env import DEFAULT_MODEL, resolve_voice_model  # noqa: E402


def test_s24x_resolve_falls_back_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env set → fallback wins (historical DEFAULT_MODEL preserved)."""
    monkeypatch.delenv("GECKO_CHART_ANALYST_MODEL", raising=False)
    monkeypatch.delenv("GECKO_VOICE_MODEL", raising=False)
    assert resolve_voice_model("chart_analyst") == DEFAULT_MODEL
    assert DEFAULT_MODEL == "openai/gpt-4o-mini"


def test_s24x_per_voice_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-voice env beats panel-wide and beats fallback."""
    monkeypatch.setenv("GECKO_CHART_ANALYST_MODEL", "anthropic/claude-haiku-4-5")
    monkeypatch.setenv("GECKO_VOICE_MODEL", "deepseek/deepseek-chat")
    assert resolve_voice_model("chart_analyst") == "anthropic/claude-haiku-4-5"


def test_s24x_panel_wide_env_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """When only the panel-wide env is set, every voice inherits it."""
    monkeypatch.delenv("GECKO_CHART_ANALYST_MODEL", raising=False)
    monkeypatch.delenv("GECKO_MEMORY_VOICE_MODEL", raising=False)
    monkeypatch.setenv("GECKO_VOICE_MODEL", "deepseek/deepseek-chat")
    assert resolve_voice_model("chart_analyst") == "deepseek/deepseek-chat"
    assert resolve_voice_model("memory_voice") == "deepseek/deepseek-chat"


def test_s24x_empty_env_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty-string env must NOT override (otherwise an unset var that
    accidentally serialized as '' would silently clear the model)."""
    monkeypatch.setenv("GECKO_CHART_ANALYST_MODEL", "   ")  # whitespace
    monkeypatch.delenv("GECKO_VOICE_MODEL", raising=False)
    assert resolve_voice_model("chart_analyst") == DEFAULT_MODEL


def test_s24x_chart_analyst_constructor_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ChartAnalystVoice constructor with model=None resolves via env."""
    monkeypatch.setenv("GECKO_CHART_ANALYST_MODEL", "anthropic/claude-haiku-4-5")
    from voices.chart_analyst import ChartAnalystVoice

    voice = ChartAnalystVoice(client=_make_or_client(lambda r: _make_response("{}")))
    assert voice._model == "anthropic/claude-haiku-4-5"


def test_s24x_explicit_model_kwarg_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit model= kwarg beats env (test fixtures + advanced callers
    must retain full control)."""
    monkeypatch.setenv("GECKO_CHART_ANALYST_MODEL", "anthropic/claude-haiku-4-5")
    from voices.chart_analyst import ChartAnalystVoice

    voice = ChartAnalystVoice(
        client=_make_or_client(lambda r: _make_response("{}")),
        model="openai/gpt-4o-mini",  # explicit — env ignored
    )
    assert voice._model == "openai/gpt-4o-mini"


def test_s24x_memory_voice_constructor_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """memory_voice picks up GECKO_MEMORY_VOICE_MODEL."""
    monkeypatch.setenv("GECKO_MEMORY_VOICE_MODEL", "deepseek/deepseek-chat")
    voice = MemoryVoice(client=_make_or_client(lambda r: _make_response("{}")))
    assert voice._model == "deepseek/deepseek-chat"


# ───────────────────────────────────────────────────────────────────────
# Sprint 28 — market_researcher voice tests
# ───────────────────────────────────────────────────────────────────────


from datetime import datetime, timedelta, timezone  # noqa: E402

from voices.market_researcher import MarketResearcherVoice  # noqa: E402


def _now() -> datetime:
    """Fixed timestamp anchor — tests build news rows relative to this."""
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _row(
    *,
    symbol: str = "PYTH",
    bias: float | None = 0.0,
    age_hours: float = 1.0,
    classified: bool = True,
) -> dict:
    """Synthesize a market_news row."""
    published = (_now() - timedelta(hours=age_hours)).isoformat().replace("+00:00", "Z")
    doc: dict = {
        "tickers": [symbol.upper()],
        "headline": f"{symbol} test headline",
        "body": "test body",
        "published_at": published,
        "source": "test",
    }
    if classified:
        doc["classification"] = {"bias_score": bias, "regime_impact": "neutral"}
    return doc


def _make_voice(rows_by_symbol: dict[str, list[dict]] | None = None,
                window_hours: float = 6.0) -> MarketResearcherVoice:
    """Inject a deterministic news_lookup callable."""
    rows_by_symbol = rows_by_symbol or {}

    def _lookup(symbol: str, *, since=None, limit: int = 200) -> list[dict]:
        out = rows_by_symbol.get(symbol.upper(), [])
        if since is None:
            return out
        # Filter on the since cutoff; tests rely on this for window tests.
        return [
            r for r in out
            if datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")) >= since
        ]

    return MarketResearcherVoice(
        news_lookup=_lookup,
        window_hours=window_hours,
        half_life_hours=6.0,
        now_fn=_now,
    )


def test_market_researcher_cold_start_zero_rows_abstains() -> None:
    voice = _make_voice({"PYTH": []})
    op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
    assert op.verdict == "abstain"
    assert op.confidence == 0.0
    assert op.reasoning == "no_news_in_window"


def test_market_researcher_cold_start_under_floor_abstains() -> None:
    voice = _make_voice({"PYTH": [_row(bias=0.4), _row(bias=0.3)]})
    op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
    assert op.verdict == "abstain"
    assert "cold_start_insufficient_news" in op.reasoning


def test_market_researcher_bullish_majority_returns_bullish() -> None:
    rows = [_row(bias=0.5, age_hours=0.5) for _ in range(4)]
    voice = _make_voice({"PYTH": rows})
    op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
    assert op.verdict == "bullish"
    assert 0.6 < op.confidence < 0.9


def test_market_researcher_bearish_majority_returns_bearish() -> None:
    rows = [_row(bias=-0.6, age_hours=0.5) for _ in range(4)]
    voice = _make_voice({"PYTH": rows})
    op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
    assert op.verdict == "bearish"
    assert 0.6 < op.confidence < 0.9


def test_market_researcher_mixed_returns_neutral() -> None:
    # Symmetric mix → agg_bias close to 0 → neutral
    rows = [
        _row(bias=0.3, age_hours=1.0),
        _row(bias=-0.3, age_hours=1.0),
        _row(bias=0.1, age_hours=1.0),
    ]
    voice = _make_voice({"PYTH": rows})
    op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
    assert op.verdict == "neutral"


def test_market_researcher_filters_to_symbol_no_bleed() -> None:
    """JTO-tagged row must NEVER contribute to a PYTH grade. The
    cross-instrument bleed bug that bit memory_voice (S24-S fix 2b)
    cannot reappear here."""
    voice = _make_voice({
        "PYTH": [],  # PYTH has nothing
        "JTO": [_row(symbol="JTO", bias=-0.9) for _ in range(5)],  # JTO is loud
    })
    op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
    # PYTH should abstain — JTO rows MUST NOT bleed in.
    assert op.verdict == "abstain"
    assert op.reasoning == "no_news_in_window"


def test_market_researcher_recency_weighting() -> None:
    """Two rows same bias, different ages: fresher row dominates the
    weighted aggregate. Confidence should reflect the agg_bias."""
    fresh_bullish_rows = [_row(bias=0.8, age_hours=0.5) for _ in range(3)]
    stale_bullish_rows = [_row(bias=0.8, age_hours=5.5) for _ in range(3)]
    voice_fresh = _make_voice({"PYTH": fresh_bullish_rows})
    voice_stale = _make_voice({"PYTH": stale_bullish_rows})
    op_fresh = asyncio.run(voice_fresh.grade({"instrument": "PYTH"}, memory=None))
    op_stale = asyncio.run(voice_stale.grade({"instrument": "PYTH"}, memory=None))
    # Both should be bullish; both should have the same agg_bias since
    # all rows have the same bias_score. Tests that recency weighting
    # doesn't crash, not that it changes the verdict.
    assert op_fresh.verdict == "bullish"
    assert op_stale.verdict == "bullish"


def test_market_researcher_skips_unclassified_rows() -> None:
    """Rows missing `classification` field don't count toward floor."""
    rows = [
        _row(bias=0.5, classified=False),
        _row(bias=0.5, classified=False),
        _row(bias=0.5, classified=False),
    ]
    voice = _make_voice({"PYTH": rows})
    op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
    # All 3 are unclassified → 0 classified → abstain via cold-start.
    assert op.verdict == "abstain"
    assert "cold_start_insufficient_news" in op.reasoning


def test_market_researcher_mongo_unavailable_abstains() -> None:
    """When news_lookup raises, voice abstains cleanly."""
    def _broken_lookup(*_args, **_kwargs):
        raise RuntimeError("mongo down")

    voice = MarketResearcherVoice(
        news_lookup=_broken_lookup,
        window_hours=6.0,
        half_life_hours=6.0,
        now_fn=_now,
    )
    op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
    assert op.verdict == "abstain"
    assert "news_lookup_error" in op.reasoning


def test_market_researcher_window_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """GECKO_MARKET_RESEARCHER_WINDOW_HOURS shrinks the lookback bound."""
    monkeypatch.setenv("GECKO_MARKET_RESEARCHER_WINDOW_HOURS", "1.0")
    # Rows 2h old — outside the 1h window
    rows = [_row(bias=0.5, age_hours=2.0) for _ in range(5)]
    # Lookup honors the since cutoff; voice should see 0 rows
    voice = MarketResearcherVoice(
        news_lookup=lambda s, since=None, limit=200: [
            r for r in rows
            if since is None or datetime.fromisoformat(
                r["published_at"].replace("Z", "+00:00")
            ) >= since
        ],
        # Force re-read from env by NOT passing window_hours
        half_life_hours=6.0,
        now_fn=_now,
    )
    op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
    assert op.verdict == "abstain"
    assert op.reasoning == "no_news_in_window"


def test_market_researcher_confidence_has_variance() -> None:
    """≥5 unique confidence values across 10 synthetic snapshots —
    anti-anchor-snap regression (S24-S template)."""
    conf_values: set[float] = set()
    # Vary n_rows (3-7) and bias (-0.8 to +0.8) to span the space
    for n_rows in range(3, 8):
        for bias in [-0.8, -0.4, 0.0, 0.3, 0.6]:
            rows = [_row(bias=bias, age_hours=1.0) for _ in range(n_rows)]
            voice = _make_voice({"PYTH": rows})
            op = asyncio.run(voice.grade({"instrument": "PYTH"}, memory=None))
            conf_values.add(round(op.confidence, 4))
    # Hard requirement: ≥5 unique values
    assert len(conf_values) >= 5, (
        f"Confidence has only {len(conf_values)} unique values; "
        f"anchor-snap regression risk."
    )


def test_market_researcher_unresolved_symbol_abstains() -> None:
    """Empty instrument + missing symbol → abstain immediately, do NOT
    fall back to universe-wide query."""
    voice = _make_voice({"PYTH": [_row(bias=0.5) for _ in range(5)]})
    # market_state has neither instrument nor symbol
    op = asyncio.run(voice.grade({}, memory=None))
    assert op.verdict == "abstain"
    assert op.reasoning == "symbol_unresolved"


# ───────────────────────────────────────────────────────────────────────
# Sprint 29 — oracle_voice tests
# ───────────────────────────────────────────────────────────────────────


from voices.oracle_voice import OracleVoice  # noqa: E402


def _snap(price: float, source: str = "pyth", spread_pct: float = 0.03) -> dict:
    return {"source": source, "price": price, "spread_pct": spread_pct, "ts": "2026-06-01T05:00:00Z"}


def _make_oracle_voice(snapshots_by_symbol: dict[str, dict[str, dict]] | None = None) -> OracleVoice:
    """Inject deterministic snapshot lookup."""
    snapshots_by_symbol = snapshots_by_symbol or {}

    def _lookup(symbol: str) -> dict[str, dict]:
        return snapshots_by_symbol.get(symbol.upper(), {})

    return OracleVoice(
        snapshot_lookup=_lookup,
        bullish_threshold_bps=30.0,
        decline_threshold_bps=50.0,
        trend_threshold_bps=5.0,
    )


def test_oracle_voice_abstains_when_no_other_sources() -> None:
    voice = _make_oracle_voice({"SOL": {}})
    op = asyncio.run(voice.grade({"instrument": "SOL", "spot_price": 148.32}, memory=None))
    assert op.verdict == "abstain"
    assert "no_second_sources_online" in op.reasoning


def test_oracle_voice_abstains_when_no_okx_price() -> None:
    voice = _make_oracle_voice({"SOL": {"pyth": _snap(148.32)}})
    op = asyncio.run(voice.grade({"instrument": "SOL"}, memory=None))
    assert op.verdict == "abstain"
    assert "okx_price_unavailable" in op.reasoning


def test_oracle_voice_abstains_on_disagreement() -> None:
    """OKX vs Pyth gap > 50bps → abstain (data quality compromised)."""
    voice = _make_oracle_voice({
        "SOL": {
            "pyth": _snap(150.0),       # +1.13% vs OKX → 113 bps
            "jupiter": _snap(148.45),
        }
    })
    op = asyncio.run(voice.grade({"instrument": "SOL", "spot_price": 148.32}, memory=None))
    assert op.verdict == "abstain"
    assert "cross_source_disagreement" in op.reasoning


def test_oracle_voice_neutral_on_tight_flat() -> None:
    """All three within 30bps + no meaningful trend → neutral."""
    voice = _make_oracle_voice({
        "SOL": {
            "pyth": _snap(148.32),    # exact match → 0 bps move
            "jupiter": _snap(148.32),
        }
    })
    op = asyncio.run(voice.grade({"instrument": "SOL", "spot_price": 148.32}, memory=None))
    assert op.verdict == "neutral"
    assert op.confidence > 0.45


def test_oracle_voice_bullish_when_okx_above_pyth() -> None:
    """OKX above Pyth by > trend_threshold + sources agree → bullish."""
    voice = _make_oracle_voice({
        "SOL": {
            "pyth": _snap(148.30),     # OKX is 148.45, +10 bps move
            "jupiter": _snap(148.42),
        }
    })
    op = asyncio.run(voice.grade({"instrument": "SOL", "spot_price": 148.45}, memory=None))
    assert op.verdict == "bullish"


def test_oracle_voice_bearish_when_okx_below_pyth() -> None:
    voice = _make_oracle_voice({
        "SOL": {
            "pyth": _snap(148.50),     # OKX is 148.30, -13 bps move
            "jupiter": _snap(148.40),
        }
    })
    op = asyncio.run(voice.grade({"instrument": "SOL", "spot_price": 148.30}, memory=None))
    assert op.verdict == "bearish"


def test_oracle_voice_unresolved_symbol_abstains() -> None:
    voice = _make_oracle_voice({})
    op = asyncio.run(voice.grade({}, memory=None))
    assert op.verdict == "abstain"
    assert op.reasoning == "symbol_unresolved"


def test_oracle_voice_swallows_lookup_exceptions() -> None:
    def _broken_lookup(*_a, **_kw):
        raise RuntimeError("mongo down")

    voice = OracleVoice(snapshot_lookup=_broken_lookup)
    op = asyncio.run(voice.grade({"instrument": "SOL", "spot_price": 148.32}, memory=None))
    assert op.verdict == "abstain"
    assert "snapshot_lookup_error" in op.reasoning


def test_oracle_voice_confidence_has_variance() -> None:
    """≥5 unique confidence values across realistic input variation —
    anti-anchor-snap regression (S24-S template applied to deterministic
    voice; should be trivially satisfied)."""
    conf_values: set[float] = set()
    # Vary spread (0 to 25 bps) and source count
    for pyth_price in [148.30, 148.35, 148.40, 148.45, 148.50]:
        for jup_present in (True, False):
            snaps: dict = {"pyth": _snap(pyth_price)}
            if jup_present:
                snaps["jupiter"] = _snap(pyth_price + 0.01)
            voice = _make_oracle_voice({"SOL": snaps})
            op = asyncio.run(voice.grade({"instrument": "SOL", "spot_price": 148.45}, memory=None))
            conf_values.add(round(op.confidence, 4))
    assert len(conf_values) >= 5, (
        f"Confidence has only {len(conf_values)} unique values; "
        f"anchor-snap regression risk."
    )
