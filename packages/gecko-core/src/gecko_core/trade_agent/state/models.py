"""Pydantic records for the ``gecko_trade_agent`` Mongo collections.

Schema mirrors ``scripts/mongo/bootstrap_trade_agent.py`` validator
blocks. Per Pattern A, keep this file as the single Python-side source of
truth for status / mode / event enums — the bootstrap script and any
future consumer must import these aliases (or replicate them and add a
drift test).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Single source of truth for the status / mode enums. Bootstrap script
# validators list these as plain string `enum`s — a drift test would
# `typing.get_args(AgentStatus)` against the bootstrap module's literals.
AgentMode = Literal["advisor", "trader"]
AgentStatus = Literal["starting", "running", "paused", "stopped", "halted", "resuming"]
PositionStatus = Literal["open", "closed", "liquidated"]
JournalEvent = Literal[
    "agent_started",
    "agent_stopped",
    "agent_paused",
    "agent_resumed",
    "opportunity",
    "entry",
    "exit",
    "verdict_called",
    "verdict_cache_hit",
    "circuit_breaker_trip",
    "spec_swap",
    "heartbeat_stale",
    "exec_error",
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AgentState(BaseModel):
    """One doc per agent in ``agent_state``."""

    model_config = ConfigDict(extra="allow")

    agent_id: str
    spec_id: str
    spec_version: str
    spec_fingerprint: str
    mode: AgentMode
    status: AgentStatus
    user_wallet: str | None = None
    execution_rail: str | None = None
    # Snapshot of the spec body so a cold restart doesn't need the
    # original file on disk.
    spec_snapshot: dict[str, Any] = Field(default_factory=dict)
    last_verdict_id: str | None = None
    startup_verdict_id: str | None = None
    daily_loss_pct: float = 0.0
    circuit_breaker_tripped: bool = False
    last_heartbeat_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime = Field(default_factory=_utcnow)
    stopped_at: datetime | None = None


class AgentPosition(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_id: str
    position_id: str
    status: PositionStatus
    mint: str | None = None
    side: Literal["long", "short"] | None = "long"
    size_usd: float | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    opened_at: datetime = Field(default_factory=_utcnow)
    closed_at: datetime | None = None
    pnl_usd: float | None = None
    verdict_id: str | None = None


class AgentJournalEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_id: str
    ts: datetime = Field(default_factory=_utcnow)
    event: JournalEvent | str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentVerdictCacheEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_id: str
    idea_hash: str
    cached_at: datetime = Field(default_factory=_utcnow)
    tier: Literal["basic", "pro"] = "basic"
    verdict: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


__all__ = [
    "AgentJournalEntry",
    "AgentMode",
    "AgentPosition",
    "AgentState",
    "AgentStatus",
    "AgentVerdictCacheEntry",
    "JournalEvent",
    "PositionStatus",
]
