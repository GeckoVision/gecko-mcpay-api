"""Tests for the Supabase-backed credits ledger (P1.5).

Uses a fake duck-typed supabase-py client (no network). A live contract test
against the real ``credit_ledger`` table is the Pattern-C follow-up before any
prod use.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from gecko_core.credits import InsufficientCredits
from gecko_core.credits_supabase import SupabaseCreditsLedger


class _FakeTable:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._filter: tuple[str, Any] | None = None
        self._pending: dict[str, Any] | None = None

    def select(self, _cols: str) -> _FakeTable:
        return self

    def eq(self, col: str, val: Any) -> _FakeTable:
        self._filter = (col, val)
        return self

    def insert(self, payload: dict[str, Any]) -> _FakeTable:
        self._pending = payload
        return self

    def execute(self) -> SimpleNamespace:
        if self._pending is not None:
            self._rows.append(dict(self._pending))
            return SimpleNamespace(data=[self._pending])
        rows = self._rows
        if self._filter is not None:
            col, val = self._filter
            rows = [r for r in rows if r.get(col) == val]
        return SimpleNamespace(data=list(rows))


class _FakeSupabase:
    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def table(self, _name: str) -> _FakeTable:
        return _FakeTable(self._rows)


def test_grant_debit_roundtrip_through_supabase_shape() -> None:
    led = SupabaseCreditsLedger(_FakeSupabase())  # type: ignore[arg-type]
    assert asyncio.run(led.grant("u1", Decimal(50))) == Decimal(50)
    assert asyncio.run(led.debit("u1", Decimal(10), ref="sess-1")) == Decimal(40)
    assert asyncio.run(led.balance("u1")) == Decimal(40)


def test_debit_blocked_below_floor() -> None:
    led = SupabaseCreditsLedger(_FakeSupabase())  # type: ignore[arg-type]
    asyncio.run(led.grant("u2", Decimal(5)))
    with pytest.raises(InsufficientCredits):
        asyncio.run(led.debit("u2", Decimal(10)))
    assert asyncio.run(led.balance("u2")) == Decimal(5)


def test_settle_clears_a_tab() -> None:
    led = SupabaseCreditsLedger(_FakeSupabase())  # type: ignore[arg-type]
    asyncio.run(led.grant("u3", Decimal(5)))
    asyncio.run(led.debit("u3", Decimal(15), tab_floor=Decimal(-50)))
    assert asyncio.run(led.settle("u3", Decimal(25))) == Decimal(15)


def test_per_user_isolation() -> None:
    fake = _FakeSupabase()
    led = SupabaseCreditsLedger(fake)  # type: ignore[arg-type]
    asyncio.run(led.grant("a", Decimal(30)))
    asyncio.run(led.grant("b", Decimal(70)))
    assert asyncio.run(led.balance("a")) == Decimal(30)
    assert asyncio.run(led.balance("b")) == Decimal(70)
