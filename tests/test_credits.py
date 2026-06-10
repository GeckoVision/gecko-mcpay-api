"""Tests for the credits ledger (pre-prod credits system, P1)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from gecko_core.credits import (
    CreditsLedger,
    InMemoryCreditsStore,
    InsufficientCredits,
    LedgerEntry,
    balance_of,
)


def _ledger() -> CreditsLedger:
    return CreditsLedger(InMemoryCreditsStore())


def test_grant_then_debit_tracks_balance() -> None:
    led = _ledger()
    assert led.grant("u1", Decimal(50)) == Decimal(50)
    assert led.debit("u1", Decimal(10), ref="sess-1") == Decimal(40)
    assert led.debit("u1", Decimal(10)) == Decimal(30)
    assert led.balance("u1") == Decimal(30)


def test_debit_blocked_below_floor() -> None:
    led = _ledger()
    led.grant("u2", Decimal(5))
    with pytest.raises(InsufficientCredits):
        led.debit("u2", Decimal(10))  # 5 - 10 < 0 (default floor 0)
    assert led.balance("u2") == Decimal(5)  # ledger unchanged on a blocked debit


def test_tab_floor_allows_bounded_negative() -> None:
    """A trusted/comp account may run a tab down to its floor."""
    led = _ledger()
    led.grant("u3", Decimal(5))
    assert led.debit("u3", Decimal(15), tab_floor=Decimal(-20)) == Decimal(-10)
    with pytest.raises(InsufficientCredits):
        led.debit("u3", Decimal(15), tab_floor=Decimal(-20))  # -10 - 15 < -20


def test_settle_clears_a_tab_first() -> None:
    """Funding settles the owed (negative) balance, remainder becomes credits."""
    led = _ledger()
    led.grant("u4", Decimal(5))
    led.debit("u4", Decimal(15), tab_floor=Decimal(-50))  # balance -10 (a tab)
    assert led.settle("u4", Decimal(25), ref="solpay-tx") == Decimal(15)


def test_comp_replaces_the_allowlist() -> None:
    led = _ledger()
    assert led.comp("tester-7", Decimal(1000), ref="comp:overnight") == Decimal(1000)
    assert led.debit("tester-7", Decimal(10)) == Decimal(990)


def test_balance_of_is_signed_sum() -> None:
    entries = [
        LedgerEntry("u", "grant", Decimal(50)),
        LedgerEntry("u", "debit", Decimal(-10)),
        LedgerEntry("u", "topup", Decimal(20)),
    ]
    assert balance_of(entries) == Decimal(60)


def test_negative_amount_rejected() -> None:
    led = _ledger()
    with pytest.raises(ValueError):
        led.grant("u", Decimal(-5))
