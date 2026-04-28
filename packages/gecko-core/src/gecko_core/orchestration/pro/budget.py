"""BudgetGuard — enforces caps on debate turns, wall time, and token usage.

The guard is intentionally dumb: callers must call `record_turn` after each
turn and `check_wall` whenever they have a chance to bail (e.g. between
speakers). Raising `BudgetExceeded` is the only signaling channel — orchestration
catches it and records `budget_halt_reason` on the transcript.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

HaltReason = Literal["max_turns", "max_wall", "max_tokens"]


class BudgetExceeded(Exception):
    def __init__(self, reason: HaltReason) -> None:
        super().__init__(reason)
        self.reason: HaltReason = reason


@dataclass
class BudgetGuard:
    max_turns: int = 12
    max_wall_seconds: float = 120.0
    max_tokens: int = 80_000
    _started_at: float | None = None
    _turns: int = 0
    _tokens: int = 0

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._turns = 0
        self._tokens = 0

    def record_turn(self, tokens_in: int, tokens_out: int) -> None:
        self._turns += 1
        self._tokens += tokens_in + tokens_out
        if self._turns >= self.max_turns:
            raise BudgetExceeded("max_turns")
        if self._tokens >= self.max_tokens:
            raise BudgetExceeded("max_tokens")
        self.check_wall()

    def check_wall(self) -> None:
        if self._started_at is None:
            return
        if (time.monotonic() - self._started_at) > self.max_wall_seconds:
            raise BudgetExceeded("max_wall")

    @property
    def status(self) -> dict[str, float | int]:
        elapsed = (time.monotonic() - self._started_at) if self._started_at is not None else 0.0
        return {
            "turns": self._turns,
            "tokens": self._tokens,
            "elapsed_seconds": elapsed,
        }
