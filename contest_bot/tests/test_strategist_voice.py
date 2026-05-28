"""Tests for the strategist_voice — Sprint 20 #1.

Light fakes only per ``feedback_lighter_tests``; no real OpenRouter, no
live LLM calls. Every HTTP call goes through ``httpx.MockTransport``
injected into the :class:`OpenRouterClient` via constructor — mirroring
the test_local_voices.py pattern.

The load-bearing tests are:

* :func:`test_strategist_downgrades_bullish_to_neutral` — the strategist
  prompt FORBIDS verdict='bullish' (it's the devil's advocate, not a
  confirming voice). gpt-4o-mini occasionally returns 'bullish' anyway
  on cleanly-bullish setups; the response-parser MUST downgrade to
  'neutral'. Without this, the strategist would silently behave like a
  second chart_analyst.
* :func:`test_strategist_thin_liquidity_forces_abstain` — mirrors the
  chart_analyst symmetric defense. Without this, a 'bearish' verdict
  on a thin-feed setup would create a spurious panel veto.
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
from voices.strategist_voice import StrategistVoice  # noqa: E402


# ── Helpers (mirror test_local_voices.py shape) ──────────────────────────
def _make_or_client(handler: Any) -> OpenRouterClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return OpenRouterClient(api_key="sk-test", http_client=http_client)


def _make_response(content: str, *, cost: float = 0.00010) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "openai/gpt-4o-mini",
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 280,
                "completion_tokens": 70,
                "cost": cost,
            },
        },
    )


def _healthy_market_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "instrument": "JTO",
        "symbol": "JTO-USDC",
        "spot_price": 2.50,
        "change_1h_pct": 0.5,
        "change_24h_pct": 3.2,
        "range_24h_pct": 4.5,
        "regime_1h": "TREND-UP",
        "ohlcv_5m": [
            {
                "ts": f"2026-05-28T12:{i:02d}:00Z",
                "open": 2.40 + i * 0.001,
                "high": 2.42 + i * 0.001,
                "low": 2.39 + i * 0.001,
                "close": 2.41 + i * 0.001,
                "volume": 12_000.0 + i * 100,
            }
            for i in range(30)
        ],
    }
    state.update(overrides)
    return state


# ── strategist_voice tests ──────────────────────────────────────────────


def test_strategist_returns_bearish_with_named_falsifier(tmp_path: Path) -> None:
    """Model returns a specific falsifier → voice carries 'bearish' through."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(
            json.dumps(
                {
                    "verdict": "bearish",
                    "confidence": 0.72,
                    "reasoning": "ADX 14 (chop) + breakout candle = likely fakeout",
                    "observations": [
                        "ADX=14 below trend threshold 25",
                        "breakout on chop is -EV per backtest history",
                    ],
                }
            )
        )

    client = _make_or_client(handler)
    voice = StrategistVoice(client=client)
    mem = LocalMemory(path=tmp_path / "strategist_bearish.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.voice_name == "strategist_voice"
    assert op.verdict == "bearish"
    assert op.confidence == pytest.approx(0.72)
    assert "chop" in op.reasoning.lower() or "fakeout" in op.reasoning.lower()
    assert len(op.observations) == 2
    client.aclose()


def test_strategist_returns_neutral_when_no_falsifier_found(tmp_path: Path) -> None:
    """When the model can't break the bullish thesis, it returns neutral with
    HIGH confidence — 'I tried hard and could not find a defensible bear case.'"""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(
            json.dumps(
                {
                    "verdict": "neutral",
                    "confidence": 0.78,
                    "reasoning": "no defensible falsifier — trend + volume + EMA all confirm",
                    "observations": ["ADX=32 (trend)", "EMA stacked-up", "MFI=62"],
                }
            )
        )

    client = _make_or_client(handler)
    voice = StrategistVoice(client=client)
    mem = LocalMemory(path=tmp_path / "strategist_neutral.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "neutral"
    assert op.confidence == pytest.approx(0.78)
    # High-confidence neutral = "I could not break this" — a CONSTRUCTIVE signal
    # for the panel, distinct from low-confidence neutral.
    assert op.confidence >= 0.7
    client.aclose()


def test_strategist_downgrades_bullish_to_neutral(tmp_path: Path) -> None:
    """LOAD-BEARING: gpt-4o-mini occasionally returns 'bullish' despite the
    prompt forbidding it. The voice MUST downgrade to 'neutral' — anything
    else and the strategist silently becomes a second chart_analyst, which
    breaks the adversarial-layer contract."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(
            json.dumps(
                {
                    "verdict": "bullish",  # forbidden but model returns it
                    "confidence": 0.68,
                    "reasoning": "setup looks clean",
                    "observations": ["volume up"],
                }
            )
        )

    client = _make_or_client(handler)
    voice = StrategistVoice(client=client)
    mem = LocalMemory(path=tmp_path / "strategist_bullish_downgrade.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "neutral", (
        "strategist must NEVER emit 'bullish' — that breaks the devil's-advocate contract"
    )
    # Confidence preserved — the model's confidence in its (mis-labeled)
    # read still carries through; we only re-label the verdict.
    assert op.confidence == pytest.approx(0.68)
    client.aclose()


def test_strategist_thin_liquidity_forces_abstain(tmp_path: Path) -> None:
    """LOAD-BEARING (symmetric with chart_analyst §8.2 defense).

    Feed 30 bars where bars 0-23 have ``volume=0``. Even if the model
    returns 'bearish' (which would create a spurious panel veto on a
    thin-feed setup), the response-parser MUST flip to abstain."""
    bars: list[dict[str, Any]] = []
    for i in range(30):
        bars.append(
            {
                "ts": f"2026-05-28T12:{i:02d}:00Z",
                "open": 0.001 + i * 0.0001,
                "high": 0.0011 + i * 0.0001,
                "low": 0.001 + i * 0.0001,
                "close": 0.0011 + i * 0.0001,
                "volume": 0.0 if i < 24 else 5_000.0,
            }
        )
    state = _healthy_market_state(ohlcv_5m=bars, range_24h_pct=15.0)

    # Adversarial probe: model returns bearish despite thin feed.
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(
            json.dumps(
                {
                    "verdict": "bearish",
                    "confidence": 0.60,
                    "reasoning": "looks like a pump-and-dump pattern",
                    "observations": ["recent vol bars suspicious"],
                }
            )
        )

    client = _make_or_client(handler)
    voice = StrategistVoice(client=client)
    mem = LocalMemory(path=tmp_path / "strategist_thin_liq.jsonl")
    op = asyncio.run(voice.grade(state, mem))

    assert op.verdict == "abstain", (
        "thin-liquidity penalty must force abstain — a spurious bearish on a "
        "thin feed would gate the panel against legitimate setups"
    )
    assert "thin_liquidity_override" in op.reasoning
    assert op.confidence == 0.0
    client.aclose()


def test_strategist_handles_openrouter_error(tmp_path: Path) -> None:
    """Upstream LLM error → abstain (not crash, not silent default)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream timeout"})

    client = _make_or_client(handler)
    voice = StrategistVoice(client=client)
    mem = LocalMemory(path=tmp_path / "strategist_or_err.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "abstain"
    assert "openrouter_error" in op.reasoning or "error" in op.reasoning.lower()
    client.aclose()


def test_strategist_parse_fail_returns_abstain(tmp_path: Path) -> None:
    """Unparseable response → abstain. Never invent a verdict."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response("not even close to JSON")

    client = _make_or_client(handler)
    voice = StrategistVoice(client=client)
    mem = LocalMemory(path=tmp_path / "strategist_parse_fail.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "abstain"
    assert op.reasoning == "parse_error"
    client.aclose()


def test_strategist_observations_capped_at_ten(tmp_path: Path) -> None:
    """VoiceOpinion model caps observations at 10 — voice must respect."""
    obs = [f"observation_{i}" for i in range(25)]

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(
            json.dumps(
                {
                    "verdict": "bearish",
                    "confidence": 0.55,
                    "reasoning": "test cap",
                    "observations": obs,
                }
            )
        )

    client = _make_or_client(handler)
    voice = StrategistVoice(client=client)
    mem = LocalMemory(path=tmp_path / "strategist_obs_cap.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert len(op.observations) <= 10, "VoiceOpinion model caps observations at 10"
    client.aclose()


def test_strategist_clamps_out_of_range_confidence(tmp_path: Path) -> None:
    """Confidence outside [0, 1] must be clamped — VoiceOpinion model enforces."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(
            json.dumps(
                {
                    "verdict": "bearish",
                    "confidence": 1.5,  # out of range
                    "reasoning": "test clamp",
                    "observations": [],
                }
            )
        )

    client = _make_or_client(handler)
    voice = StrategistVoice(client=client)
    mem = LocalMemory(path=tmp_path / "strategist_conf_clamp.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert 0.0 <= op.confidence <= 1.0
    client.aclose()


def test_strategist_handles_unknown_verdict_token_as_abstain(tmp_path: Path) -> None:
    """A garbage verdict token → abstain. Never silently pick a default."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(
            json.dumps(
                {
                    "verdict": "maybe-ish",  # nonsense
                    "confidence": 0.50,
                    "reasoning": "test unknown",
                    "observations": [],
                }
            )
        )

    client = _make_or_client(handler)
    voice = StrategistVoice(client=client)
    mem = LocalMemory(path=tmp_path / "strategist_unknown_verdict.jsonl")
    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "abstain"
    client.aclose()
