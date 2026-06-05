"""A6 — Kamino live executor double-gate. Mocked: NEVER submits a real tx."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import pytest  # noqa: E402
from kamino import live_executor as le  # noqa: E402

_FAKE_BUILD = {"ok": True, "unsignedTxBase64": "AAAA", "numInstructions": 6}


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
    ex = le.KaminoLiveExecutor("OWNER", dry_run=True)
    out = ex.deposit(10.0, confirm=True)  # confirm but dry_run → still no submit
    assert out.ok and out.submitted is False and "dry_run" in out.detail
    assert no_network["contract_call"] == 0


def test_armed_but_unconfirmed_never_submits(no_network):
    ex = le.KaminoLiveExecutor("OWNER", dry_run=False)
    out = ex.deposit(10.0, confirm=False)  # armed but not confirmed → no submit
    assert out.ok and out.submitted is False and "confirm=False" in out.detail
    assert no_network["contract_call"] == 0


def test_both_gates_submits(no_network):
    ex = le.KaminoLiveExecutor("OWNER", dry_run=False)
    out = ex.deposit(10.0, confirm=True)  # both gates → submit (mocked CLI)
    assert out.ok and out.submitted is True and out.tx_hash == "FAKETX"
    assert no_network["contract_call"] == 1


def test_withdraw_path(no_network):
    ex = le.KaminoLiveExecutor("OWNER", dry_run=False)
    out = ex.withdraw(10.0, confirm=True)
    assert out.action == "withdraw" and out.submitted is True


def test_sidecar_build_failure_surfaces(monkeypatch):
    monkeypatch.setattr(le, "build_unsigned_kamino_tx", lambda **kw: {"ok": False, "error": "boom"})
    ex = le.KaminoLiveExecutor("OWNER", dry_run=False)
    out = ex.deposit(10.0, confirm=True)
    assert out.ok is False and out.submitted is False and "build failed" in out.detail


def test_contract_call_error_surfaces(monkeypatch):
    monkeypatch.setattr(le, "build_unsigned_kamino_tx", lambda **kw: dict(_FAKE_BUILD))
    monkeypatch.setattr(le, "_b64_to_b58", lambda b64: "FAKEB58")

    class _Proc:
        stdout = '{"ok":false,"error":"policy limit exceeded"}'
        stderr = ""

    monkeypatch.setattr(le.subprocess, "run", lambda cmd, **kw: _Proc())
    ex = le.KaminoLiveExecutor("OWNER", dry_run=False)
    out = ex.deposit(999.0, confirm=True)
    assert out.ok is False and out.submitted is False and "contract-call error" in out.detail
