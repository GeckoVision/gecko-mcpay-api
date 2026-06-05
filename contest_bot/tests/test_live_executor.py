"""A6 — Kamino live executor double-gate. Mocked: NEVER submits a real tx."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import pytest  # noqa: E402
import trade_safety as ts  # noqa: E402
from kamino import live_executor as le  # noqa: E402

_FAKE_BUILD = {"ok": True, "unsignedTxBase64": "AAAA", "numInstructions": 6}

# A policy+ctx that PASS the safety gate (verified DEPLOY strategy, generous caps,
# kill off) so the double-gate / submit paths can be exercised in isolation.
_OK_CTX = ts.SafetyContext(strategy_verdict="DEPLOY")


def _ok_policy(**kw):
    return ts.kamino_policy(max_notional_usd=10_000.0, **kw)


def _exec(**kw):
    """KaminoLiveExecutor wired to PASS the safety gate (kill off + DEPLOY ctx)."""
    kw.setdefault("policy", _ok_policy())
    kw.setdefault("safety_ctx", _OK_CTX)
    kw.setdefault("global_kill_fn", lambda: False)
    return le.KaminoLiveExecutor("OWNER", **kw)


@pytest.fixture
def no_network(monkeypatch):
    """Stub the sidecar build + the onchainos CLI so nothing touches a chain."""
    monkeypatch.setattr(le, "build_unsigned_kamino_tx", lambda **kw: dict(_FAKE_BUILD))
    monkeypatch.setattr(le, "_b64_to_b58", lambda b64: "FAKEB58")
    calls = {"contract_call": 0}

    class _Proc:
        stdout = '{"ok":true,"data":{"txHash":"FAKETX"}}'
        stderr = ""

    def _fake_run(cmd, **kw):
        calls["contract_call"] += 1
        return _Proc()

    monkeypatch.setattr(le.subprocess, "run", _fake_run)
    return calls


def test_dry_run_never_submits(no_network):
    ex = _exec(dry_run=True)
    out = ex.deposit(10.0, confirm=True)  # confirm but dry_run → still no submit
    assert out.ok and out.submitted is False and "dry_run" in out.detail
    assert no_network["contract_call"] == 0


def test_armed_but_unconfirmed_never_submits(no_network):
    ex = _exec(dry_run=False)
    out = ex.deposit(10.0, confirm=False)  # armed but not confirmed → no submit
    assert out.ok and out.submitted is False and "confirm=False" in out.detail
    assert no_network["contract_call"] == 0


def test_both_gates_submits(no_network):
    ex = _exec(dry_run=False)
    out = ex.deposit(10.0, confirm=True)  # both gates → submit (mocked CLI)
    assert out.ok and out.submitted is True and out.tx_hash == "FAKETX"
    assert no_network["contract_call"] == 1


def test_withdraw_path(no_network):
    ex = _exec(dry_run=False)
    out = ex.withdraw(10.0, confirm=True)
    assert out.action == "withdraw" and out.submitted is True


def test_sidecar_build_failure_surfaces(monkeypatch):
    monkeypatch.setattr(le, "build_unsigned_kamino_tx", lambda **kw: {"ok": False, "error": "boom"})
    ex = _exec(dry_run=False)
    out = ex.deposit(10.0, confirm=True)
    assert out.ok is False and out.submitted is False and "build failed" in out.detail


def test_contract_call_error_surfaces(monkeypatch):
    monkeypatch.setattr(le, "build_unsigned_kamino_tx", lambda **kw: dict(_FAKE_BUILD))
    monkeypatch.setattr(le, "_b64_to_b58", lambda b64: "FAKEB58")

    class _Proc:
        stdout = '{"ok":false,"error":"policy limit exceeded"}'
        stderr = ""

    monkeypatch.setattr(le.subprocess, "run", lambda cmd, **kw: _Proc())
    ex = _exec(dry_run=False)
    out = ex.deposit(999.0, confirm=True)  # under the 10_000 gate cap; CLI rejects it
    assert out.ok is False and out.submitted is False and "contract-call error" in out.detail


# ── NEW: safety-gate coverage (the kill-switch + caps must cover Kamino) ──
def test_global_kill_blocks_no_broadcast(no_network):
    """Global kill engaged → refuse, NEVER reach the onchainos contract-call."""
    ex = _exec(dry_run=False, global_kill_fn=lambda: True)
    out = ex.deposit(10.0, confirm=True)
    assert out.ok is False and out.submitted is False
    assert "safety-gate denied" in out.detail and "kill_switch" in out.detail
    assert no_network["contract_call"] == 0  # broadcast NEVER fired


def test_notional_cap_blocks_no_broadcast(no_network):
    """Policy notional cap below the order → refuse, no broadcast."""
    ex = _exec(dry_run=False, policy=ts.kamino_policy(max_notional_usd=5.0))
    out = ex.deposit(10.0, confirm=True)  # $10 > $5 cap
    assert out.ok is False and out.submitted is False
    assert "safety-gate denied" in out.detail and "notional" in out.detail
    assert no_network["contract_call"] == 0


def test_unverified_strategy_blocks_no_broadcast(no_network):
    """Deny-default: no DEPLOY verdict → refuse even within caps + kill off."""
    ex = _exec(dry_run=False, safety_ctx=ts.SafetyContext(strategy_verdict=None))
    out = ex.deposit(10.0, confirm=True)
    assert out.ok is False and out.submitted is False
    assert "safety-gate denied" in out.detail and "not DEPLOY" in out.detail
    assert no_network["contract_call"] == 0


def test_within_caps_kill_off_confirmed_proceeds(no_network):
    """Within caps + kill off + DEPLOY + confirm + armed → proceeds (mocked broadcast)."""
    ex = _exec(dry_run=False)
    out = ex.deposit(10.0, confirm=True)
    assert out.ok is True and out.submitted is True
    assert no_network["contract_call"] == 1
