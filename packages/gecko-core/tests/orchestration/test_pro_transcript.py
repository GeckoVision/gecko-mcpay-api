"""transcript_from_events — filtering, ordering, token sums, validation."""

from __future__ import annotations

import pytest
from gecko_core.orchestration.pro import AgentEvent, transcript_from_events


def _ev(
    *,
    seq: int,
    type: str = "turn_end",
    agent: str | None = "analyst",
    tokens_in: int = 0,
    tokens_out: int = 0,
    content: str = "",
    ts: float = 0.0,
) -> AgentEvent:
    return AgentEvent(
        type=type,  # type: ignore[arg-type]
        agent=agent,
        content=content,
        ts=ts,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        seq=seq,
    )


def test_filters_non_turn_end_events() -> None:
    events = [
        _ev(seq=1, type="turn_start", agent="analyst"),
        _ev(seq=2, type="turn_end", agent="analyst", tokens_in=5, tokens_out=7),
        _ev(seq=3, type="final", agent=None, content="done"),
        _ev(seq=4, type="error", agent=None, content="boom"),
    ]
    t = transcript_from_events(events)
    assert len(t.turns) == 1
    assert t.turns[0].seq == 2
    assert t.total_tokens_in == 5
    assert t.total_tokens_out == 7


def test_skips_events_with_agent_none() -> None:
    events = [
        _ev(seq=1, agent=None),
        _ev(seq=2, agent="critic", tokens_in=3, tokens_out=4),
    ]
    t = transcript_from_events(events)
    assert len(t.turns) == 1
    assert t.turns[0].agent == "critic"


def test_preserves_order_and_sums_tokens() -> None:
    events = [
        _ev(seq=1, agent="analyst", tokens_in=10, tokens_out=20, ts=1.0),
        _ev(seq=2, agent="critic", tokens_in=30, tokens_out=40, ts=2.0),
        _ev(seq=3, agent="judge", tokens_in=5, tokens_out=5, ts=3.0),
    ]
    t = transcript_from_events(events)
    assert [turn.seq for turn in t.turns] == [1, 2, 3]
    assert [turn.agent for turn in t.turns] == ["analyst", "critic", "judge"]
    assert t.total_tokens_in == 45
    assert t.total_tokens_out == 65


def test_unknown_agent_raises() -> None:
    events = [_ev(seq=1, agent="ceo")]
    with pytest.raises(ValueError, match="unknown agent name"):
        transcript_from_events(events)
