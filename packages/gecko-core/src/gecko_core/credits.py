"""Credits ledger — the accounting core of the credits system.

Replaces the free-user *bypass* (a payment-gate workaround) with first-class
accounting that sits in front of the x402 gate. Per the design plan
(``docs/superpowers/plans/2026-06-10-credits-system-and-solana-pay.md``):

  - **grant / comp** : free or comp credits added to an account (+).
  - **debit**        : a paid call draws down the balance (−), bounded by a
                       per-account ``tab_floor`` (how negative the account may
                       go before settlement — comp accounts get a high floor).
  - **topup**        : a Solana Pay funding lands → credits added (+).
  - **settle**       : an x402 settlement reconciles into the same balance (+).

The **append-only ledger is the single source of truth**; the balance is the
sum of entries. This module is pure (no DB import) — a ``CreditsStore`` Protocol
abstracts persistence so the same logic runs over an in-memory store in tests
and a Supabase-backed store in prod.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

# Canonical credit-entry kinds (Pattern A — the SQL CHECK constraint mirrors
# this set; adding a kind = touch this Literal + one migration).
CreditKind = Literal["grant", "comp", "debit", "topup", "settle"]

# Kinds that add to the balance (debit is the only subtractive kind).
_CREDIT_KINDS: frozenset[str] = frozenset({"grant", "comp", "topup", "settle"})


class InsufficientCredits(Exception):
    """Raised when a debit would push the balance below the account's tab floor."""


@dataclass(frozen=True)
class LedgerEntry:
    """One append-only credit-ledger row. ``amount`` is signed (debits negative)."""

    user_id: str
    kind: CreditKind
    amount: Decimal
    ref: str | None = None


@runtime_checkable
class CreditsStore(Protocol):
    """Persistence seam for the ledger (in-memory in tests, Supabase in prod)."""

    def append(self, entry: LedgerEntry) -> None: ...

    def entries_for(self, user_id: str) -> list[LedgerEntry]: ...


@dataclass
class InMemoryCreditsStore:
    """Process-local store — for tests and a dev fallback."""

    _rows: dict[str, list[LedgerEntry]] = field(default_factory=dict)

    def append(self, entry: LedgerEntry) -> None:
        self._rows.setdefault(entry.user_id, []).append(entry)

    def entries_for(self, user_id: str) -> list[LedgerEntry]:
        return list(self._rows.get(user_id, []))


def balance_of(entries: list[LedgerEntry]) -> Decimal:
    """Balance is the signed sum of all ledger entries."""
    return sum((e.amount for e in entries), Decimal(0))


class CreditsLedger:
    """Grant / debit / top-up / settle over a :class:`CreditsStore`."""

    def __init__(self, store: CreditsStore) -> None:
        self._store = store

    def balance(self, user_id: str) -> Decimal:
        return balance_of(self._store.entries_for(user_id))

    def _add(self, user_id: str, kind: CreditKind, amount: Decimal, ref: str | None) -> Decimal:
        if amount < 0:
            raise ValueError("amount must be non-negative; sign is derived from kind")
        signed = -amount if kind == "debit" else amount
        self._store.append(LedgerEntry(user_id=user_id, kind=kind, amount=signed, ref=ref))
        return self.balance(user_id)

    def grant(self, user_id: str, amount: Decimal, *, ref: str | None = None) -> Decimal:
        """Add free starter credits (onboarding)."""
        return self._add(user_id, "grant", amount, ref)

    def comp(self, user_id: str, amount: Decimal, *, ref: str | None = None) -> Decimal:
        """Add comp credits (the replacement for the tester allowlist)."""
        return self._add(user_id, "comp", amount, ref)

    def topup(self, user_id: str, amount: Decimal, *, ref: str | None = None) -> Decimal:
        """Credit a Solana Pay funding."""
        return self._add(user_id, "topup", amount, ref)

    def settle(self, user_id: str, amount: Decimal, *, ref: str | None = None) -> Decimal:
        """Reconcile an x402 settlement into the balance (clears a tab first)."""
        return self._add(user_id, "settle", amount, ref)

    def debit(
        self,
        user_id: str,
        amount: Decimal,
        *,
        ref: str | None = None,
        tab_floor: Decimal = Decimal(0),
    ) -> Decimal:
        """Draw down for a paid call. Raises :class:`InsufficientCredits` if the
        resulting balance would fall below ``tab_floor``."""
        if amount < 0:
            raise ValueError("debit amount must be non-negative")
        if self.balance(user_id) - amount < tab_floor:
            raise InsufficientCredits(
                f"debit {amount} would breach tab_floor {tab_floor} for {user_id}"
            )
        return self._add(user_id, "debit", amount, ref)


__all__ = [
    "CreditKind",
    "CreditsLedger",
    "CreditsStore",
    "InMemoryCreditsStore",
    "InsufficientCredits",
    "LedgerEntry",
    "balance_of",
]
