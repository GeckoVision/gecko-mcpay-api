"""S12-LATENCY-01 — concurrent dispatch of analyst + critic.

Today the 5-voice debate ran serially (analyst → critic → architect →
scoper → judge). The MCP advisor panel + product-designer S12 memo +
Sprint 11 dogfood all flagged 20-30s latency as the binding constraint
for agent-side ICP. The refactor parallelizes the analyst/critic step
(both read the same RAG context, neither sees the other's reply); the
rest of the chain stays serial because each step depends on the prior.

These tests verify:
  - analyst + critic actually run concurrently (wall < sum)
  - architect waits for BOTH analyst + critic before starting
  - a slow voice times out without blocking the chain
  - transcript order is canonical (analyst → critic → ...) regardless
    of completion order in the parallel stage
"""

from __future__ import annotations

import asyncio
import time

import pytest
from gecko_core.orchestration import pro as pro_mod
from gecko_core.orchestration.pro import AgentEvent, generate


def _make_fake_groupchat(replies: dict[str, object]) -> object:
    """Build a fake AG2 manager whose agents return the given replies.

    `replies` values may be either:
      - str: instant reply
      - tuple[str, float]: (reply, delay seconds)
      - Exception: raised when the agent is invoked
    """

    class _FakeAgent:
        def __init__(self, name: str) -> None:
            self.name = name
            self._reply = replies[name]

        async def a_generate_reply(self, messages: object = None) -> object:
            r = self._reply
            if isinstance(r, tuple):
                text, delay = r
                await asyncio.sleep(delay)
                return text
            if isinstance(r, BaseException):
                raise r
            if callable(r):
                return await r(messages)  # type: ignore[misc]
            return r

    class _FakeChat:
        def __init__(self) -> None:
            self.agents = [_FakeAgent(n) for n in replies]
            self.messages: list[dict[str, object]] = []

    class _FakeManager:
        def __init__(self) -> None:
            self.groupchat = _FakeChat()

    return _FakeManager()


_LLM_CFG = {"config_list": [{"model": "x", "api_key": "y", "base_url": "z"}]}


@pytest.mark.asyncio
async def test_analyst_and_critic_run_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    """analyst + critic dispatch in parallel — total wall < sum of individual delays."""
    delay = 0.4
    replies: dict[str, object] = {
        "analyst": ("A", delay),
        "critic": ("C", delay),
        "architect": "AR",
        "scoper": "S",
        "judge": "J",
    }
    monkeypatch.setattr(
        pro_mod, "build_groupchat", lambda _cfg, **_kw: _make_fake_groupchat(replies)
    )

    t0 = time.perf_counter()
    transcript = await generate(idea="x", rag_context="y", llm_config=_LLM_CFG)
    elapsed = time.perf_counter() - t0

    # Strictly less than 2x delay would imply concurrency. Allow some slack
    # (event-loop + emit overhead) but still well below the serial budget.
    assert elapsed < 2 * delay, f"expected <{2 * delay}s (concurrent), got {elapsed:.3f}s"
    # And it must clear the slowest voice in the parallel stage.
    assert elapsed >= delay * 0.9
    assert [t.agent for t in transcript.turns] == [
        "analyst",
        "critic",
        "architect",
        "scoper",
        "judge",
    ]


@pytest.mark.asyncio
async def test_architect_waits_for_both_parallel_voices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """architect must NOT begin until BOTH analyst and critic finish."""
    start_ts: dict[str, float] = {}
    end_ts: dict[str, float] = {}

    async def _record_call(name: str, delay: float, payload: str) -> str:
        start_ts[name] = time.perf_counter()
        await asyncio.sleep(delay)
        end_ts[name] = time.perf_counter()
        return payload

    class _Agent:
        def __init__(self, name: str, delay: float, payload: str) -> None:
            self.name = name
            self._delay = delay
            self._payload = payload

        async def a_generate_reply(self, messages: object = None) -> str:
            return await _record_call(self.name, self._delay, self._payload)

    class _Chat:
        def __init__(self) -> None:
            self.agents = [
                _Agent("analyst", 0.30, "A"),
                _Agent("critic", 0.05, "C"),  # finishes early
                _Agent("architect", 0.0, "AR"),
                _Agent("scoper", 0.0, "S"),
                _Agent("judge", 0.0, "J"),
            ]
            self.messages: list[dict[str, object]] = []

    class _Mgr:
        def __init__(self) -> None:
            self.groupchat = _Chat()

    monkeypatch.setattr(pro_mod, "build_groupchat", lambda _cfg, **_kw: _Mgr())

    await generate(idea="x", rag_context="y", llm_config=_LLM_CFG)

    # critic finished WAY before analyst, but architect must wait until BOTH end.
    assert end_ts["critic"] < end_ts["analyst"]
    assert start_ts["architect"] >= end_ts["analyst"]
    assert start_ts["architect"] >= end_ts["critic"]
    # serial chain enforced too:
    assert start_ts["scoper"] >= end_ts["architect"]
    assert start_ts["judge"] >= end_ts["scoper"]


@pytest.mark.asyncio
async def test_transcript_order_canonical_regardless_of_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if critic finishes before analyst, transcript order is analyst-first.

    Replay determinism: downstream consumers (SSE replay, DB row reconstruction,
    eval rubric) depend on the canonical analyst → critic → architect → scoper
    → judge ordering. Completion order in the parallel stage must NOT leak.
    """
    replies: dict[str, object] = {
        "analyst": ("A-slow", 0.20),  # finishes second
        "critic": ("C-fast", 0.01),  # finishes first
        "architect": "AR",
        "scoper": "S",
        "judge": "J",
    }
    monkeypatch.setattr(
        pro_mod, "build_groupchat", lambda _cfg, **_kw: _make_fake_groupchat(replies)
    )

    events: list[AgentEvent] = []

    async def _on_event(ev: AgentEvent) -> None:
        events.append(ev)

    transcript = await generate(
        idea="x",
        rag_context="y",
        llm_config=_LLM_CFG,
        on_event=_on_event,
    )

    # Transcript turns must be in canonical order regardless of completion.
    assert [t.agent for t in transcript.turns] == [
        "analyst",
        "critic",
        "architect",
        "scoper",
        "judge",
    ]
    assert [t.content for t in transcript.turns] == ["A-slow", "C-fast", "AR", "S", "J"]

    # The event stream must also keep canonical (analyst before critic) ordering
    # for turn_start / turn_end pairs, even though critic actually completed first.
    turn_end_agents = [e.agent for e in events if e.type == "turn_end"]
    assert turn_end_agents == ["analyst", "critic", "architect", "scoper", "judge"]

    # seq is monotonically increasing across the whole stream.
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))


@pytest.mark.asyncio
async def test_slow_voice_times_out_does_not_block_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single hung voice surfaces as a placeholder turn; the rest of the chain runs."""
    # Patch the timeout to something fast so the test stays snappy.
    monkeypatch.setattr(pro_mod, "_VOICE_TIMEOUT_SECONDS", 0.10)

    replies: dict[str, object] = {
        "analyst": ("A-ok", 0.01),
        # critic exceeds the 0.10s cap → should time out.
        "critic": ("C-never", 5.0),
        "architect": "AR",
        "scoper": "S",
        "judge": "J",
    }
    monkeypatch.setattr(
        pro_mod, "build_groupchat", lambda _cfg, **_kw: _make_fake_groupchat(replies)
    )

    events: list[AgentEvent] = []

    async def _on_event(ev: AgentEvent) -> None:
        events.append(ev)

    t0 = time.perf_counter()
    transcript = await generate(
        idea="x",
        rag_context="y",
        llm_config=_LLM_CFG,
        on_event=_on_event,
    )
    elapsed = time.perf_counter() - t0

    # Total wall is bounded by the timeout (0.10s) + downstream work, NOT 5s.
    assert elapsed < 1.0, f"timeout did not unblock chain — took {elapsed:.3f}s"

    # Transcript still has all five turns in canonical order.
    assert [t.agent for t in transcript.turns] == [
        "analyst",
        "critic",
        "architect",
        "scoper",
        "judge",
    ]

    # Critic's turn carries the placeholder content per the S9-ADVISOR-01 pattern.
    critic_turn = next(t for t in transcript.turns if t.agent == "critic")
    assert "voice failed" in critic_turn.content
    assert "timeout" in critic_turn.content

    # An `error` event was emitted for observability before the placeholder turn.
    error_events = [e for e in events if e.type == "error" and e.agent == "critic"]
    assert len(error_events) == 1
    assert "Timeout" in error_events[0].content or "timeout" in error_events[0].content

    # Downstream voices ran normally.
    assert next(t for t in transcript.turns if t.agent == "architect").content == "AR"
    assert next(t for t in transcript.turns if t.agent == "judge").content == "J"
