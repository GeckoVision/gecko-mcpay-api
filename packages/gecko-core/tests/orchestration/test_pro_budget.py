"""BudgetGuard tests — turn cap, token cap, wall cap, status shape."""

from __future__ import annotations

import time

import pytest
from gecko_core.orchestration.pro import BudgetExceeded, BudgetGuard


def test_max_turns_halts_after_two_calls() -> None:
    guard = BudgetGuard(max_turns=2, max_wall_seconds=60.0, max_tokens=10_000)
    guard.start()
    guard.record_turn(1, 1)  # turn 1 — ok
    with pytest.raises(BudgetExceeded) as exc:
        guard.record_turn(1, 1)  # turn 2 — hits cap
    assert exc.value.reason == "max_turns"


def test_max_tokens_halts_after_overflow() -> None:
    guard = BudgetGuard(max_turns=10, max_wall_seconds=60.0, max_tokens=100)
    guard.start()
    with pytest.raises(BudgetExceeded) as exc:
        guard.record_turn(60, 60)
    assert exc.value.reason == "max_tokens"


def test_max_wall_halts_after_sleep() -> None:
    guard = BudgetGuard(max_turns=10, max_wall_seconds=0.05, max_tokens=10_000)
    guard.start()
    time.sleep(0.08)
    with pytest.raises(BudgetExceeded) as exc:
        guard.check_wall()
    assert exc.value.reason == "max_wall"


def test_status_shape() -> None:
    guard = BudgetGuard()
    guard.start()
    status = guard.status
    assert set(status.keys()) == {"turns", "tokens", "elapsed_seconds"}
    assert all(isinstance(v, (int, float)) for v in status.values())
