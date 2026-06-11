"""Tests for the credits gate ASGI middleware (P2a) — pure, no live wiring."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from gecko_api.credits_gate import CreditsGateMiddleware
from gecko_core.credits import InsufficientCredits


class _Recorder:
    """Two fake ASGI apps that record which one got the request."""

    def __init__(self) -> None:
        self.called: str | None = None

    def app(self, label: str) -> Any:
        async def _app(scope: Any, receive: Any, send: Any) -> None:
            self.called = label

        return _app


class _FakeLedger:
    def __init__(self, balance: Decimal) -> None:
        self.balance = balance
        self.debited: list[tuple[str, Decimal]] = []

    async def debit(
        self,
        user_id: str,
        amount: Decimal,
        *,
        ref: str | None = None,
        tab_floor: Decimal = Decimal(0),
    ) -> Decimal:
        if self.balance - amount < tab_floor:
            raise InsufficientCredits("no credits")
        self.balance -= amount
        self.debited.append((user_id, amount))
        return self.balance


def _scope(
    path: str = "/v1/research", method: str = "POST", token: str | None = None
) -> dict[str, Any]:
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return {"type": "http", "path": path, "method": method, "headers": headers}


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request"}


async def _noop_send(_msg: dict[str, Any]) -> None:
    return None


def _mw(rec: _Recorder, ledger: _FakeLedger, *, enabled: bool) -> CreditsGateMiddleware:
    return CreditsGateMiddleware(
        rec.app("paid"),
        rec.app("free"),
        ledger=ledger,
        verify_token=lambda t: "u1" if t == "good" else None,
        price_credits=lambda path, method: Decimal(10) if path == "/v1/research" else None,
        enabled=enabled,
    )


def _run(mw: CreditsGateMiddleware, scope: dict[str, Any]) -> None:
    asyncio.run(mw(scope, _noop_receive, _noop_send))


def test_disabled_is_a_no_op_to_paid() -> None:
    rec, led = _Recorder(), _FakeLedger(Decimal(50))
    _run(_mw(rec, led, enabled=False), _scope(token="good"))
    assert rec.called == "paid"
    assert led.debited == []


def test_credited_user_bypasses_to_free_and_debits() -> None:
    rec, led = _Recorder(), _FakeLedger(Decimal(50))
    _run(_mw(rec, led, enabled=True), _scope(token="good"))
    assert rec.called == "free"
    assert led.debited == [("u1", Decimal(10))]


def test_no_credits_falls_through_to_paid() -> None:
    rec, led = _Recorder(), _FakeLedger(Decimal(5))  # < price 10
    _run(_mw(rec, led, enabled=True), _scope(token="good"))
    assert rec.called == "paid"
    assert led.debited == []  # the blocked debit left no trace


def test_anonymous_uses_paid() -> None:
    rec, led = _Recorder(), _FakeLedger(Decimal(50))
    _run(_mw(rec, led, enabled=True), _scope(token=None))
    assert rec.called == "paid"


def test_unpriced_route_uses_paid() -> None:
    rec, led = _Recorder(), _FakeLedger(Decimal(50))
    _run(_mw(rec, led, enabled=True), _scope(path="/healthz", method="GET", token="good"))
    assert rec.called == "paid"
    assert led.debited == []
