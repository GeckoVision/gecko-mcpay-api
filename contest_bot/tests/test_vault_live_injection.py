"""Phase 1 — live-executor injection into VaultOrchestrator. Fake exec, no real money."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from kamino import vault_gate as vg  # noqa: E402
from kamino import vault_orchestrator as vo  # noqa: E402
from kamino.monitor import CRYPTO_ONLY  # noqa: E402


class _Outcome:
    def __init__(self, submitted, tx):
        self.submitted = submitted
        self.tx_hash = tx
        self.detail = "fake"


class _FakeExec:
    """Records calls; mimics KaminoLiveExecutor.deposit/withdraw double-gate."""

    def __init__(self):
        self.calls = []

    def deposit(self, amt, confirm=False):
        self.calls.append(("deposit", amt, confirm))
        return _Outcome(confirm, "TX" if confirm else None)

    def withdraw(self, amt, confirm=False):
        self.calls.append(("withdraw", amt, confirm))
        return _Outcome(confirm, "TX" if confirm else None)


def _pol(**kw):
    base = {"max_allocation_usd": 10_000.0}
    base.update(kw)
    return vg.VaultPolicy(**base)


def test_no_executor_is_paper_only():
    orch = vo.VaultOrchestrator(profile="conservative", policy=_pol(), hurdle=CRYPTO_ONLY)
    rep = orch.allocate_profit(1000.0)
    assert "live" not in rep["deposited"][0]  # paper, no live routing


def test_conservative_routes_to_executor_but_does_not_submit_by_default():
    ex = _FakeExec()
    orch = vo.VaultOrchestrator(profile="conservative", policy=_pol(), hurdle=CRYPTO_ONLY, executor=ex)
    rep = orch.allocate_profit(1000.0)
    assert ex.calls == [("deposit", 1000.0, False)]  # routed, confirm=False (no submit)
    assert rep["deposited"][0]["live"]["submitted"] is False


def test_live_confirm_threads_through():
    ex = _FakeExec()
    orch = vo.VaultOrchestrator(profile="conservative", policy=_pol(), hurdle=CRYPTO_ONLY,
                                executor=ex, live_confirm=True)
    rep = orch.allocate_profit(500.0)
    assert ex.calls == [("deposit", 500.0, True)]  # confirm=True passed through
    assert rep["deposited"][0]["live"]["submitted"] is True
    assert rep["deposited"][0]["live"]["tx_hash"] == "TX"


def test_leveraged_legs_never_routed_to_executor():
    ex = _FakeExec()
    orch = vo.VaultOrchestrator(profile="aggressive", policy=_pol(max_leverage=10.0),
                                hurdle=CRYPTO_ONLY, executor=ex)
    orch.allocate_profit(1000.0)
    # aggressive = LST 8x + JLP 3.2x + lend 0.2; ONLY the conservative lend leg routes
    assert all(c[0] == "deposit" for c in ex.calls)
    assert len(ex.calls) == 1  # just the stable_spread lend leg


def test_exit_routes_live_withdraw_for_conservative():
    ex = _FakeExec()
    orch = vo.VaultOrchestrator(profile="conservative", policy=_pol(), hurdle=CRYPTO_ONLY, executor=ex)
    orch.allocate_profit(100.0)
    ex.calls.clear()
    # force an EXIT verdict on the lend lot
    verdicts = [{"source": "stable_spread", "action": "EXIT"}]
    changed = orch.apply_actions(verdicts)
    assert ("withdraw", 100.0, False) in ex.calls
    assert changed[0]["did"] == "exited" and "live" in changed[0]


def test_executor_error_never_breaks_allocation():
    class _Boom:
        def deposit(self, amt, confirm=False):
            raise RuntimeError("rpc down")

    orch = vo.VaultOrchestrator(profile="conservative", policy=_pol(), hurdle=CRYPTO_ONLY, executor=_Boom())
    rep = orch.allocate_profit(100.0)  # must not raise
    assert rep["deposited"][0]["live"]["submitted"] is False
    assert orch.lots  # paper lot still recorded
