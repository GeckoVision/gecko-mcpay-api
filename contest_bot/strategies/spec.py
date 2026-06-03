"""StrategySpec — the JSON-serializable strategy config.

Built now so the future "create → backtest → package → deploy" app is nearly
free later: a deployed agent IS `(spec + universe + runner)`. The backtest
harness and the live runner both load a StrategySpec and call the matching
`strategies/` rules. Adding a strategy = a new spec + a new rules class; the
transport (CLI/launcher/backtest) doesn't change.

Mirrors the spec doc §3 fields exactly. `entry_gates` / `exit` are free-form
dicts so a strategy owns its own knobs (and the backtest can sweep them) without
schema churn here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StrategySpec:
    strategy_id: str
    version: str = "v0"
    universe: list[str] = field(default_factory=list)
    timeframe: str = "5m"
    venue: str = "okx_spot"
    entry_gates: dict[str, Any] = field(default_factory=dict)
    exit: dict[str, Any] = field(default_factory=dict)
    sizing: dict[str, Any] = field(
        default_factory=lambda: {"fraction": 0.10, "size_jitter_pct": 15}
    )
    # fleet-safety hooks (spec §6) — plumbing exists from day one, trivially high for 2 bots
    fleet: dict[str, Any] = field(
        default_factory=lambda: {"entry_jitter_sec": [0, 30], "max_aggregate_exposure": None}
    )
    capacity_estimate: float | None = None  # populated from book depth later

    def to_json(self, **kw: Any) -> str:
        return json.dumps(asdict(self), **kw)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategySpec:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_json(cls, s: str) -> StrategySpec:
        return cls.from_dict(json.loads(s))
