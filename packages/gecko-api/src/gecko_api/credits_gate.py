"""Credits gate — the ASGI layer that sits *in front of* the x402 gate (P2a).

Replaces the bypass with first-class accounting. For a request from a session
user who has credits, the gate **debits a credit and serves via the un-gated
app** (skipping x402 entirely); otherwise it passes the request through to the
**x402-wrapped app**, which charges per-call as today. So:

    credited user   → debit 1 call's price → serve (no payment challenge)
    no credits      → fall through to x402 (pay-per-call) — unchanged behaviour
    disabled / anon → always the x402 path — unchanged behaviour

This component is **decoupled and standalone**: it takes the two apps + a
ledger + a token→user_id verifier + a price resolver by injection, so it unit
-tests in isolation and the live wiring (P2b, in ``main.py``) is a small, separate
step. Default ``enabled=False`` → a transparent no-op (current behaviour).

v1 simplification: debit happens *before* serving (a rare 5xx burns a credit);
a debit-on-2xx refinement is a documented follow-up. Comp testers are just an
account with a large credit grant — no allowlist branch here.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, Protocol

from gecko_core.credits import InsufficientCredits

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class _DebitLedger(Protocol):
    async def debit(
        self, user_id: str, amount: Decimal, *, ref: str | None = ..., tab_floor: Decimal = ...
    ) -> Decimal: ...


def _bearer_token(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            raw = bytes(value).decode("latin-1")
            if raw.lower().startswith("bearer "):
                return raw[7:].strip()
    return None


class CreditsGateMiddleware:
    """Route credited requests around the x402 gate; debit a credit per call."""

    def __init__(
        self,
        paid_app: ASGIApp,
        free_app: ASGIApp,
        *,
        ledger: _DebitLedger,
        verify_token: Callable[[str], str | None],
        price_credits: Callable[[str, str], Decimal | None],
        enabled: bool = False,
        tab_floor: Decimal = Decimal(0),
    ) -> None:
        self._paid_app = paid_app  # x402-wrapped
        self._free_app = free_app  # raw, un-gated
        self._ledger = ledger
        self._verify_token = verify_token
        self._price_credits = price_credits
        self._enabled = enabled
        self._tab_floor = tab_floor

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._enabled or scope.get("type") != "http":
            await self._paid_app(scope, receive, send)
            return

        price = self._price_credits(scope.get("path", ""), scope.get("method", "GET"))
        if price is None:  # not a paid route → x402 passes it through free anyway
            await self._paid_app(scope, receive, send)
            return

        token = _bearer_token(scope)
        user_id = self._verify_token(token) if token else None
        if user_id is None:  # anonymous → can't credit; let x402 handle
            await self._paid_app(scope, receive, send)
            return

        try:
            await self._ledger.debit(
                user_id, price, ref=scope.get("path"), tab_floor=self._tab_floor
            )
        except InsufficientCredits:
            await self._paid_app(scope, receive, send)  # out of credits → pay via x402
            return

        await self._free_app(scope, receive, send)  # credited → bypass the x402 challenge


__all__ = ["CreditsGateMiddleware"]
