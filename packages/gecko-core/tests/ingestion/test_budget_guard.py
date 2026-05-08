from decimal import Decimal

import pytest
from gecko_core.ingestion.budget_guard import BudgetExceededError, BudgetGuard


def test_initial_state():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    assert g.remaining() == Decimal("20.00")
    assert g.spent() == Decimal("0")


def test_can_afford_within_cap():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    assert g.can_afford(Decimal("5.00")) is True


def test_cannot_afford_over_cap():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    g.charge(Decimal("18.00"), label="paysh:foo")
    assert g.can_afford(Decimal("5.00")) is False


def test_charge_updates_remaining():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    g.charge(Decimal("3.50"), label="bazaar:bar")
    assert g.remaining() == Decimal("16.50")
    assert g.spent() == Decimal("3.50")


def test_charge_over_cap_raises():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    g.charge(Decimal("18.00"), label="paysh:foo")
    with pytest.raises(BudgetExceededError):
        g.charge(Decimal("5.00"), label="bazaar:big")


def test_ledger_records_each_charge():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    g.charge(Decimal("1.00"), label="a")
    g.charge(Decimal("2.00"), label="b")
    assert [(e.amount_usd, e.label) for e in g.ledger()] == [
        (Decimal("1.00"), "a"),
        (Decimal("2.00"), "b"),
    ]
