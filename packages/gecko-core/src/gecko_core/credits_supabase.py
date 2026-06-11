"""Supabase-backed credits ledger (credits system P1.5).

The pure ``gecko_core.credits`` ledger (P1) is sync — ideal for the
business-logic + tests. Prod needs an **async** ledger over Supabase: the
``credit_ledger`` table is the append-only source of truth, the balance is the
signed sum. This class mirrors the ``TelemetryStore`` pattern (sync supabase-py
client dispatched via ``asyncio.to_thread`` so it never blocks the event loop)
and reuses the P1 primitives (``LedgerEntry``, ``balance_of``, the sign rule,
``InsufficientCredits``) so the two stay in lockstep.

Tables: ``infra/supabase/migrations/20260610120000_credits_ledger.sql``.
Service-role only — never call ``from_env`` from gecko-mcpay-app.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from supabase import Client

from gecko_core.credits import (
    CreditKind,
    InsufficientCredits,
    LedgerEntry,
    balance_of,
)
from gecko_core.db import create_supabase_client

logger = logging.getLogger(__name__)

LEDGER_TABLE = "credit_ledger"


def _signed(kind: CreditKind, amount: Decimal) -> Decimal:
    """Debits subtract; every other kind adds. (Same rule as the sync ledger.)"""
    return -amount if kind == "debit" else amount


class SupabaseCreditsLedger:
    """Async append-only credits ledger over the Supabase ``credit_ledger`` table."""

    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> SupabaseCreditsLedger:
        """Build from SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY. Server-side only."""
        return cls(create_supabase_client())

    async def _entries(self, user_id: str) -> list[LedgerEntry]:
        def _q() -> Any:
            return (
                self._client.table(LEDGER_TABLE)
                .select("user_id,kind,amount,ref")
                .eq("user_id", user_id)
                .execute()
            )

        resp = await asyncio.to_thread(_q)
        return [
            LedgerEntry(
                user_id=row["user_id"],
                kind=row["kind"],
                amount=Decimal(str(row["amount"])),
                ref=row.get("ref"),
            )
            for row in (resp.data or [])
        ]

    async def balance(self, user_id: str) -> Decimal:
        return balance_of(await self._entries(user_id))

    async def _add(
        self, user_id: str, kind: CreditKind, amount: Decimal, ref: str | None
    ) -> Decimal:
        if amount < 0:
            raise ValueError("amount must be non-negative; sign is derived from kind")
        signed = _signed(kind, amount)

        def _ins() -> Any:
            return (
                self._client.table(LEDGER_TABLE)
                .insert({"user_id": user_id, "kind": kind, "amount": str(signed), "ref": ref})
                .execute()
            )

        await asyncio.to_thread(_ins)
        return await self.balance(user_id)

    async def grant(self, user_id: str, amount: Decimal, *, ref: str | None = None) -> Decimal:
        return await self._add(user_id, "grant", amount, ref)

    async def comp(self, user_id: str, amount: Decimal, *, ref: str | None = None) -> Decimal:
        return await self._add(user_id, "comp", amount, ref)

    async def topup(self, user_id: str, amount: Decimal, *, ref: str | None = None) -> Decimal:
        return await self._add(user_id, "topup", amount, ref)

    async def settle(self, user_id: str, amount: Decimal, *, ref: str | None = None) -> Decimal:
        return await self._add(user_id, "settle", amount, ref)

    async def debit(
        self,
        user_id: str,
        amount: Decimal,
        *,
        ref: str | None = None,
        tab_floor: Decimal = Decimal(0),
    ) -> Decimal:
        if amount < 0:
            raise ValueError("debit amount must be non-negative")
        if await self.balance(user_id) - amount < tab_floor:
            raise InsufficientCredits(
                f"debit {amount} would breach tab_floor {tab_floor} for {user_id}"
            )
        return await self._add(user_id, "debit", amount, ref)


__all__ = ["LEDGER_TABLE", "SupabaseCreditsLedger"]
