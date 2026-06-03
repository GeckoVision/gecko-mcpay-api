"""Phase-4 pre-trade safety gate + execution-adapter seam — the wedge in code."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from trade_safety import (  # noqa: E402
    DelegatedExecutionAdapter,
    Order,
    PaperExecutionAdapter,
    SafetyContext,
    TradeSafetyPolicy,
    check_order,
    dispatch,
)


def _ok_ctx():
    return SafetyContext(strategy_verdict="DEPLOY", realized_loss_today_usd=0.0)


def _order(notional=50.0, venue="okx", symbol="BTC/USDT"):
    return Order(symbol=symbol, venue=venue, notional_usd=notional)


# ── the gate ─────────────────────────────────────────────────────────
def test_allows_clean_verified_order():
    v = check_order(_order(), TradeSafetyPolicy(), _ok_ctx())
    assert v.allow and v.reasons == []


def test_denies_kill_switch():
    v = check_order(_order(), TradeSafetyPolicy(kill_switch=True), _ok_ctx())
    assert not v.allow and any("kill_switch" in r for r in v.reasons)


def test_denies_over_notional():
    v = check_order(_order(notional=500), TradeSafetyPolicy(max_notional_usd=100), _ok_ctx())
    assert not v.allow and any("notional" in r for r in v.reasons)


def test_denies_disallowed_venue():
    v = check_order(_order(venue="sketchy_dex"), TradeSafetyPolicy(), _ok_ctx())
    assert not v.allow and any("venue" in r for r in v.reasons)


def test_denies_disallowed_symbol_when_allowlist_set():
    pol = TradeSafetyPolicy(allowed_symbols=("ETH/USDT",))
    v = check_order(_order(symbol="BTC/USDT"), pol, _ok_ctx())
    assert not v.allow and any("symbol" in r for r in v.reasons)


def test_denies_when_daily_loss_cap_breached():
    ctx = SafetyContext(strategy_verdict="DEPLOY", realized_loss_today_usd=30.0)
    v = check_order(_order(), TradeSafetyPolicy(max_daily_loss_usd=25.0), ctx)
    assert not v.allow and any("daily loss" in r for r in v.reasons)


def test_denies_unverified_strategy_for_real_money():
    for verdict in ("PAPER ONLY", "REJECT", None):
        ctx = SafetyContext(strategy_verdict=verdict)
        v = check_order(_order(), TradeSafetyPolicy(require_verified_strategy=True), ctx)
        assert not v.allow and any("not DEPLOY" in r for r in v.reasons)


def test_allows_unverified_when_verification_not_required():
    ctx = SafetyContext(strategy_verdict="PAPER ONLY")
    v = check_order(_order(), TradeSafetyPolicy(require_verified_strategy=False), ctx)
    assert v.allow


def test_collects_multiple_reasons():
    pol = TradeSafetyPolicy(max_notional_usd=10, kill_switch=True)
    ctx = SafetyContext(strategy_verdict="REJECT")
    v = check_order(_order(notional=50), pol, ctx)
    assert not v.allow and len(v.reasons) >= 3  # kill switch + notional + unverified


# ── execution adapters ───────────────────────────────────────────────
def test_paper_adapter_fills():
    r = PaperExecutionAdapter().place_order(_order(), ref_price=100.0)
    assert r.ok and r.paper and r.fill_price == 100.0


def test_delegated_adapter_refuses_real_money():
    r = DelegatedExecutionAdapter(venue="okx").place_order(_order(), ref_price=100.0)
    assert not r.ok and not r.paper  # founder-gated stub — never places a live order


# ── dispatch: gate runs BEFORE the adapter ───────────────────────────
def test_dispatch_denied_order_never_reaches_adapter():
    calls = []

    class _SpyAdapter:
        venue = "okx"

        def place_order(self, order, ref_price):
            calls.append(order)
            raise AssertionError("adapter must not be called on a denied order")

    pol = TradeSafetyPolicy(kill_switch=True)
    r = dispatch(_order(), pol, _ok_ctx(), _SpyAdapter(), ref_price=100.0)
    assert not r.ok and "safety-gate denied" in r.detail and calls == []


def test_dispatch_clean_order_reaches_adapter():
    r = dispatch(_order(), TradeSafetyPolicy(), _ok_ctx(), PaperExecutionAdapter(), ref_price=100.0)
    assert r.ok and r.fill_price == 100.0
