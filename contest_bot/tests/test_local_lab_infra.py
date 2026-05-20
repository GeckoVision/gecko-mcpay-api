"""Tests for the local-lab infrastructure (s40-lab #2).

Light fakes only — no real OpenRouter, no live LLM.

Covers:

* :class:`OpenRouterClient` — headers, body shape, 429 retry,
  hard-fail on non-retryable 4xx, env-key requirement.
* :class:`LocalMemory` — append / recent / outcomes_for, newest-first,
  filter semantics, corrupt-line resilience.
* :class:`VoiceOpinion` — schema bounds and length caps.
* :func:`safe_parse_voice_json` — fenced + bare + garbage paths.
* :class:`LocalPanel` — concurrent voices, exception → abstain, the
  coordinator function is called with every opinion, decision logged.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

# contest_bot is not a uv-workspace member; make it importable.
_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from llm_client import (  # noqa: E402
    OPENROUTER_REFERER,
    OPENROUTER_TITLE,
    OPENROUTER_URL,
    LLMResponse,
    OpenRouterCallError,
    OpenRouterClient,
    OpenRouterConfigError,
)
from local_memory import LocalMemory  # noqa: E402
from local_panel import LocalPanel  # noqa: E402
from voices.base import (  # noqa: E402
    VoiceOpinion,
    safe_parse_voice_json,
)


# ── OpenRouterClient ───────────────────────────────────────────────────
def _make_or_client(handler: Any, **kwargs: Any) -> OpenRouterClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return OpenRouterClient(api_key="sk-test", http_client=client, **kwargs)


def test_or_client_requires_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(OpenRouterConfigError, match="OPENROUTER_API_KEY"):
        OpenRouterClient()


def test_or_client_picks_up_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
    # No HTTP client — we never call .chat(), just construct.
    client = OpenRouterClient()
    # Re-attached via attribute name to confirm capture without leaking.
    assert getattr(client, "_api_key") == "sk-from-env"  # noqa: B009


def test_or_client_sends_required_headers_and_body() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "anthropic/claude-3.5-haiku",
                "choices": [{"message": {"content": '{"verdict": "bullish"}'}}],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 7,
                    "cost": 0.00042,
                },
            },
        )

    client = _make_or_client(handler)
    resp = client.chat(
        model="anthropic/claude-3.5-haiku",
        messages=[{"role": "user", "content": "grade"}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    assert seen["url"] == OPENROUTER_URL
    assert seen["headers"]["authorization"] == "Bearer sk-test"
    assert seen["headers"]["http-referer"] == OPENROUTER_REFERER
    assert seen["headers"]["x-title"] == OPENROUTER_TITLE
    assert seen["body"]["model"] == "anthropic/claude-3.5-haiku"
    assert seen["body"]["messages"] == [{"role": "user", "content": "grade"}]
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["temperature"] == 0.0

    assert isinstance(resp, LLMResponse)
    assert resp.content == '{"verdict": "bullish"}'
    assert resp.model_used == "anthropic/claude-3.5-haiku"
    assert resp.cost_usd == pytest.approx(0.00042)
    assert resp.prompt_tokens == 12
    assert resp.completion_tokens == 7
    assert resp.raw["usage"]["cost"] == 0.00042
    client.aclose()


def test_or_client_retries_once_on_429() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0},
            },
        )

    client = _make_or_client(handler, retry_backoff_s=0.0)
    resp = client.chat(model="m", messages=[{"role": "user", "content": "x"}])
    assert calls["n"] == 2
    assert resp.content == "ok"
    client.aclose()


def test_or_client_retries_once_on_5xx() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0},
            },
        )

    client = _make_or_client(handler, retry_backoff_s=0.0)
    resp = client.chat(model="m", messages=[{"role": "user", "content": "x"}])
    assert calls["n"] == 2
    assert resp.content == "ok"
    client.aclose()


def test_or_client_raises_on_4xx_non_429() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="unauthorized")

    client = _make_or_client(handler, retry_backoff_s=0.0)
    with pytest.raises(OpenRouterCallError, match="401"):
        client.chat(model="m", messages=[{"role": "user", "content": "x"}])
    # Hard-fail: NO retry on 401.
    assert calls["n"] == 1
    client.aclose()


def test_or_client_raises_after_second_5xx() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="oops")

    client = _make_or_client(handler, retry_backoff_s=0.0)
    with pytest.raises(OpenRouterCallError, match="500"):
        client.chat(model="m", messages=[{"role": "user", "content": "x"}])
    assert calls["n"] == 2  # 1 attempt + 1 retry
    client.aclose()


def test_or_client_response_missing_usage_cost_degrades_to_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": "x"}}],
                # No usage block at all — should default to zeros.
            },
        )

    client = _make_or_client(handler)
    resp = client.chat(model="m", messages=[{"role": "user", "content": "x"}])
    assert resp.cost_usd == 0.0
    assert resp.prompt_tokens == 0
    assert resp.completion_tokens == 0
    client.aclose()


# ── LocalMemory ────────────────────────────────────────────────────────
def test_memory_append_then_recent_newest_first(tmp_path: Path) -> None:
    mem = LocalMemory(path=tmp_path / "mem.jsonl")
    mem.append("opinion", {"voice": "chart", "verdict": "bullish"})
    mem.append("opinion", {"voice": "memory", "verdict": "bearish"})
    mem.append("local_decision", {"action": "act"})

    rows = mem.recent(limit=10)
    assert len(rows) == 3
    # Newest-first
    assert rows[0]["event"] == "local_decision"
    assert rows[1]["payload"]["voice"] == "memory"
    assert rows[2]["payload"]["voice"] == "chart"


def test_memory_recent_filter_single_event(tmp_path: Path) -> None:
    mem = LocalMemory(path=tmp_path / "mem.jsonl")
    mem.append("opinion", {"v": 1})
    mem.append("local_decision", {"v": 2})
    mem.append("opinion", {"v": 3})

    rows = mem.recent(event_filter="opinion")
    assert [r["payload"]["v"] for r in rows] == [3, 1]


def test_memory_recent_filter_tuple_events(tmp_path: Path) -> None:
    mem = LocalMemory(path=tmp_path / "mem.jsonl")
    mem.append("a", {})
    mem.append("b", {})
    mem.append("c", {})
    rows = mem.recent(event_filter=("a", "c"))
    assert [r["event"] for r in rows] == ["c", "a"]


def test_memory_recent_honors_limit(tmp_path: Path) -> None:
    mem = LocalMemory(path=tmp_path / "mem.jsonl")
    for i in range(5):
        mem.append("opinion", {"i": i})
    rows = mem.recent(limit=2)
    assert len(rows) == 2
    assert [r["payload"]["i"] for r in rows] == [4, 3]


def test_memory_outcomes_for_decision_id(tmp_path: Path) -> None:
    mem = LocalMemory(path=tmp_path / "mem.jsonl")
    mem.append("local_decision", {"action": "act"}, decision_id="abc")
    mem.append("outcome", {"pnl_usd": 1.2}, decision_id="abc")
    mem.append("outcome", {"pnl_usd": -0.3}, decision_id="other")
    mem.append("outcome", {"pnl_usd": 0.5}, decision_id="abc")

    rows = mem.outcomes_for("abc")
    assert len(rows) == 3
    # Returned chronologically (oldest-first).
    assert rows[0]["event"] == "local_decision"
    assert rows[1]["payload"]["pnl_usd"] == 1.2
    assert rows[2]["payload"]["pnl_usd"] == 0.5


def test_memory_skips_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "mem.jsonl"
    path.write_text(
        '{"ts_iso":"2026-05-20T00:00:00+00:00","event":"good","decision_id":null,"payload":{"x":1}}\n'
        "this is not json at all\n"
        '{"ts_iso":"2026-05-20T00:00:01+00:00","event":"good2","decision_id":null,"payload":{"x":2}}\n'
        "[1,2,3]\n",  # JSON but not an object — should also be skipped
        encoding="utf-8",
    )
    mem = LocalMemory(path=path)
    rows = mem.recent()
    # Two good rows survive; corrupt line + non-object row are skipped.
    assert len(rows) == 2
    assert {r["event"] for r in rows} == {"good", "good2"}


def test_memory_append_is_atomic_across_writes(tmp_path: Path) -> None:
    path = tmp_path / "mem.jsonl"
    mem = LocalMemory(path=path)
    for i in range(20):
        mem.append("opinion", {"i": i})
    # Every line parses as a complete object.
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 20
    for ln in lines:
        json.loads(ln)  # raises if any line was truncated


# ── VoiceOpinion ───────────────────────────────────────────────────────
def test_voice_opinion_valid_minimal() -> None:
    op = VoiceOpinion(
        voice_name="chart_analyst",
        verdict="bullish",
        confidence=0.7,
        reasoning="trend up",
        raw_response="{}",
        elapsed_ms=120,
    )
    assert op.confidence == 0.7
    assert op.observations == []
    assert op.cost_usd is None


def test_voice_opinion_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        VoiceOpinion(
            voice_name="x",
            verdict="bullish",
            confidence=1.5,
            reasoning="",
            raw_response="",
            elapsed_ms=0,
        )
    with pytest.raises(ValidationError):
        VoiceOpinion(
            voice_name="x",
            verdict="bullish",
            confidence=-0.1,
            reasoning="",
            raw_response="",
            elapsed_ms=0,
        )


def test_voice_opinion_rejects_long_reasoning() -> None:
    with pytest.raises(ValidationError):
        VoiceOpinion(
            voice_name="x",
            verdict="neutral",
            confidence=0.5,
            reasoning="r" * 401,  # max_length=400
            raw_response="",
            elapsed_ms=0,
        )


def test_voice_opinion_rejects_too_many_observations() -> None:
    with pytest.raises(ValidationError):
        VoiceOpinion(
            voice_name="x",
            verdict="neutral",
            confidence=0.5,
            reasoning="",
            observations=[f"obs_{i}" for i in range(11)],  # max_length=10
            raw_response="",
            elapsed_ms=0,
        )


def test_voice_opinion_rejects_unknown_verdict() -> None:
    with pytest.raises(ValidationError):
        VoiceOpinion(
            voice_name="x",
            verdict="moonshot",  # type: ignore[arg-type]
            confidence=0.5,
            reasoning="",
            raw_response="",
            elapsed_ms=0,
        )


# ── safe_parse_voice_json ─────────────────────────────────────────────
def test_safe_parse_voice_json_bare_object() -> None:
    out = safe_parse_voice_json('{"verdict": "bullish", "confidence": 0.7}', "v")
    assert out == {"verdict": "bullish", "confidence": 0.7}


def test_safe_parse_voice_json_json_fence() -> None:
    raw = """Here is my call:
```json
{"verdict": "bearish", "confidence": 0.4}
```
That's all."""
    out = safe_parse_voice_json(raw, "v")
    assert out == {"verdict": "bearish", "confidence": 0.4}


def test_safe_parse_voice_json_bare_fence() -> None:
    raw = '```\n{"verdict": "neutral"}\n```'
    out = safe_parse_voice_json(raw, "v")
    assert out == {"verdict": "neutral"}


def test_safe_parse_voice_json_embedded_in_prose() -> None:
    raw = 'Some prose before {"verdict": "bullish", "n": 1} and some after.'
    out = safe_parse_voice_json(raw, "v")
    assert out == {"verdict": "bullish", "n": 1}


def test_safe_parse_voice_json_returns_none_on_garbage() -> None:
    assert safe_parse_voice_json("no json here at all", "v") is None
    assert safe_parse_voice_json("", "v") is None
    assert safe_parse_voice_json("[1,2,3]", "v") is None  # array, not object


# ── LocalPanel ────────────────────────────────────────────────────────
class _StubVoice:
    """A minimal voice that returns a pre-canned opinion."""

    def __init__(self, voice_name: str, verdict: str, confidence: float) -> None:
        self.voice_name = voice_name
        self._verdict = verdict
        self._confidence = confidence

    async def grade(self, market_state: dict[str, Any], memory: LocalMemory) -> VoiceOpinion:
        # Yield once so the panel actually has to await us.
        await asyncio.sleep(0)
        return VoiceOpinion(
            voice_name=self.voice_name,
            verdict=self._verdict,  # type: ignore[arg-type]
            confidence=self._confidence,
            reasoning=f"stub:{self._verdict}",
            raw_response=f'{{"verdict": "{self._verdict}"}}',
            elapsed_ms=10,
            cost_usd=0.0001,
        )


class _RaisingVoice:
    """A voice that raises mid-grade — panel must convert to abstain."""

    voice_name = "raiser"

    async def grade(self, market_state: dict[str, Any], memory: LocalMemory) -> VoiceOpinion:
        await asyncio.sleep(0)
        raise RuntimeError("boom")


class _SlowVoice:
    """Sleeps briefly so we can assert concurrent execution."""

    def __init__(self, voice_name: str, sleep_s: float) -> None:
        self.voice_name = voice_name
        self._sleep_s = sleep_s

    async def grade(self, market_state: dict[str, Any], memory: LocalMemory) -> VoiceOpinion:
        await asyncio.sleep(self._sleep_s)
        return VoiceOpinion(
            voice_name=self.voice_name,
            verdict="neutral",
            confidence=0.5,
            reasoning="slept",
            raw_response="{}",
            elapsed_ms=int(self._sleep_s * 1000),
            cost_usd=0.0,
        )


def _coordinator_pass_through(
    opinions: list[VoiceOpinion],
) -> tuple[str, str | None]:
    """Dummy coordinator: act if any opinion is bullish, else decline."""
    if any(o.verdict == "bullish" for o in opinions):
        return ("act", "any_bullish")
    return ("decline", "no_bullish")


def test_panel_runs_all_voices_concurrently_and_aggregates(tmp_path: Path) -> None:
    mem = LocalMemory(path=tmp_path / "mem.jsonl")
    seen_coord_inputs: list[list[VoiceOpinion]] = []

    def coord(ops: list[VoiceOpinion]) -> tuple[str, str | None]:
        seen_coord_inputs.append(list(ops))
        return _coordinator_pass_through(ops)

    voices = [
        _StubVoice("chart", "bullish", 0.8),
        _StubVoice("memory", "neutral", 0.6),
        _RaisingVoice(),
    ]
    panel = LocalPanel(voices=voices, memory=mem, coordinator=coord)
    decision = asyncio.run(panel.run({"spot_price": 1.0}))

    # The coordinator MUST have been called with all three opinions —
    # even the one whose voice raised — converted to an abstain.
    assert len(seen_coord_inputs) == 1
    inputs = seen_coord_inputs[0]
    assert len(inputs) == 3
    by_name = {o.voice_name: o for o in inputs}
    assert by_name["chart"].verdict == "bullish"
    assert by_name["chart"].confidence == 0.8
    assert by_name["memory"].verdict == "neutral"
    assert by_name["raiser"].verdict == "abstain"
    assert by_name["raiser"].confidence == 0.0
    assert "RuntimeError" in by_name["raiser"].reasoning

    # Decision passed through the coordinator output.
    assert decision.action == "act"
    assert decision.coordinator_rule_fired == "any_bullish"
    assert len(decision.voice_opinions) == 3
    # Total cost is the sum of the surviving voices' costs.
    assert decision.total_cost_usd == pytest.approx(0.0002)
    assert decision.total_elapsed_ms >= 0

    # The decision was logged to memory exactly once.
    rows = mem.recent(event_filter="local_decision")
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert payload["action"] == "act"
    assert payload["coordinator_rule_fired"] == "any_bullish"
    assert (
        payload["voice_count"] == 3 if "voice_count" in payload else len(payload["voice_opinions"])
    )
    assert rows[0]["decision_id"] == decision.decision_id


def test_panel_runs_concurrently_not_sequentially(tmp_path: Path) -> None:
    """Three voices, each sleeping 0.1s, should complete in ~0.1s not 0.3s."""
    mem = LocalMemory(path=tmp_path / "mem.jsonl")
    voices = [_SlowVoice(f"slow_{i}", 0.1) for i in range(3)]

    panel = LocalPanel(voices=voices, memory=mem, coordinator=_coordinator_pass_through)
    started = time.monotonic()
    asyncio.run(panel.run({}))
    elapsed = time.monotonic() - started

    # Sequential would be ~0.3s. We assert a generous bound to avoid
    # flakes on busy CI: concurrent must finish < 0.25s.
    assert elapsed < 0.25, f"voices ran sequentially: {elapsed:.3f}s"


def test_panel_declines_when_coordinator_says_decline(tmp_path: Path) -> None:
    mem = LocalMemory(path=tmp_path / "mem.jsonl")
    voices = [_StubVoice("chart", "bearish", 0.7), _StubVoice("memory", "neutral", 0.5)]
    panel = LocalPanel(voices=voices, memory=mem, coordinator=_coordinator_pass_through)
    decision = asyncio.run(panel.run({"spot_price": 1.0}))

    assert decision.action == "decline"
    assert decision.coordinator_rule_fired == "no_bullish"
    # decision still logged.
    assert len(mem.recent(event_filter="local_decision")) == 1


def test_panel_requires_at_least_one_voice(tmp_path: Path) -> None:
    mem = LocalMemory(path=tmp_path / "mem.jsonl")
    with pytest.raises(ValueError, match="at least one voice"):
        LocalPanel(voices=[], memory=mem, coordinator=_coordinator_pass_through)
