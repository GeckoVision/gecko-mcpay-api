from __future__ import annotations

import dataclasses
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class SimulationDoc:
    run_id: str
    strategy_id: str
    agent_group: str
    symbol_universe: list[str]
    universe_label: str
    config: dict
    mode: str  # "paper" | "live"
    code_commit: str
    started_at: str = field(default_factory=_now)
    ended_at: str | None = None
    host: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SimulationDoc:
        return cls(**{k: d.get(k) for k in (f.name for f in dataclasses.fields(cls))})


@dataclass
class Outcome:
    pnl_pct: float
    pnl_usd: float | None = None
    exit_reason: str | None = None
    duration_min: float | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    peak_pct: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DecisionDoc:
    run_id: str
    symbol: str
    symbol_group: str
    signal: dict
    indicators: dict
    voices: list[dict]
    oracle: dict | None
    coordinator: dict
    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: str = field(default_factory=_now)
    market_context: dict | None = None  # future slot (#2)
    candles_ref: dict | None = None  # {window_hash, last_ts, n_bars}
    outcome: dict | None = None  # patched on close

    def to_dict(self) -> dict:
        return asdict(self)
