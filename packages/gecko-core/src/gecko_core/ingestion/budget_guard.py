"""Hard USD spend cap for paid x402 ingest runs.

Pure, sync, no I/O. The caller is expected to:
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    if not g.can_afford(price):
        skip
    ...issue the paid call...
    g.charge(actual_price, label="paysh:fqn")
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal


class BudgetExceededError(RuntimeError):
    """Raised when a charge would push spent above cap."""


@dataclass(frozen=True)
class LedgerEntry:
    amount_usd: Decimal
    label: str


@dataclass
class BudgetGuard:
    cap_usd: Decimal
    _ledger: list[LedgerEntry] = field(default_factory=list)

    def spent(self) -> Decimal:
        return sum((e.amount_usd for e in self._ledger), Decimal("0"))

    def remaining(self) -> Decimal:
        return self.cap_usd - self.spent()

    def can_afford(self, price_usd: Decimal) -> bool:
        return price_usd <= self.remaining()

    def charge(self, amount_usd: Decimal, *, label: str) -> None:
        if amount_usd > self.remaining():
            raise BudgetExceededError(
                f"charge ${amount_usd} would exceed cap (remaining ${self.remaining()})"
            )
        self._ledger.append(LedgerEntry(amount_usd=amount_usd, label=label))

    def ledger(self) -> Sequence[LedgerEntry]:
        return tuple(self._ledger)
