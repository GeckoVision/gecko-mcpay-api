"""Final transcript shape returned from `pro.generate`.

`transcript_from_events` is the canonical way to derive a transcript from a
recorded event stream — the reducer is centralized here so SSE replay and
DB-row reconstruction stay in lockstep.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from gecko_core.orchestration.pro.events import AgentEvent

AgentName = Literal["analyst", "critic", "architect", "scoper", "judge"]
_VALID_AGENTS: frozenset[str] = frozenset(("analyst", "critic", "architect", "scoper", "judge"))


class AgentTurn(BaseModel):
    seq: int
    agent: AgentName
    content: str
    ts: float
    tokens_in: int
    tokens_out: int


class DebateTranscript(BaseModel):
    turns: list[AgentTurn]
    total_tokens_in: int
    total_tokens_out: int
    budget_halt_reason: Literal["max_turns", "max_wall", "max_tokens"] | None = None


def transcript_from_events(events: list[AgentEvent]) -> DebateTranscript:
    """Fold an event stream into a `DebateTranscript`.

    Filters to `turn_end` events with a non-null `agent`. Raises ValueError on
    any unknown agent name so a malformed producer surfaces loudly rather than
    silently dropping turns.
    """
    turns: list[AgentTurn] = []
    total_in = 0
    total_out = 0
    for ev in events:
        if ev.type != "turn_end":
            continue
        if ev.agent is None:
            continue
        if ev.agent not in _VALID_AGENTS:
            raise ValueError(f"unknown agent name: {ev.agent!r}")
        turns.append(
            AgentTurn(
                seq=ev.seq,
                agent=ev.agent,  # type: ignore[arg-type]
                content=ev.content,
                ts=ev.ts,
                tokens_in=ev.tokens_in,
                tokens_out=ev.tokens_out,
            )
        )
        total_in += ev.tokens_in
        total_out += ev.tokens_out
    return DebateTranscript(
        turns=turns,
        total_tokens_in=total_in,
        total_tokens_out=total_out,
        budget_halt_reason=None,
    )
