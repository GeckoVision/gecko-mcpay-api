"""Streaming event model for the Pro tier 5-agent debate.

Producers (the AG2 GroupChat wrapper) emit `AgentEvent`s. Consumers (the API
SSE layer, the persistence sink) subscribe via the `on_event` callback. Keeping
the event flat keeps it cheap to serialize over SSE.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AgentEvent(BaseModel):
    type: Literal["turn_start", "turn_end", "final", "error"]
    agent: str | None  # None for 'final' / 'error'
    content: str
    ts: float  # unix seconds with frac
    tokens_in: int = 0
    tokens_out: int = 0
    seq: int  # monotonic per session
