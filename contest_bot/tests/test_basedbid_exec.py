"""based.bid execution adapter — double-gate + API shape. Mocked: NEVER submits."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import basedbid_exec as bb  # noqa: E402
import pytest  # noqa: E402
import trade_safety as ts  # noqa: E402

_FAKE_RESP = {"transaction": "AAAA", "blockhash": "bh", "lastValidBlockHeight": 123}

# A policy+ctx that PASS the safety gate (verified DEPLOY, generous caps, kill off)
# so the double-gate / API-shape paths can be exercised in isolation.
_OK_CTX = ts.SafetyContext(strategy_verdict="DEPLOY")


def _ok_policy(**kw):
    return ts.basedbid_policy(max_notional_usd=10_000.0, **kw)


def _adapter(**kw):
    """BasedBidExecutionAdapter wired to PASS the safety gate (kill off + DEPLOY)."""
    kw.setdefault("policy", _ok_policy())
    kw.setdefault("safety_ctx", _OK_CTX)
    kw.setdefault("global_kill_fn", lambda: False)
    return bb.BasedBidExecutionAdapter("OWNER", **kw)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


class _FakeClient:
    def __init__(self, resp=None):
        self.resp = resp or _FAKE_RESP
        self.posts = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "body": json, "headers": headers})
        return _Resp(self.resp)


@pytest.fixture
def no_submit(monkeypatch):
    monkeypatch.setattr(bb, "_b64_to_b58", lambda b64: "B58")
    calls = {"n": 0}

    class _Proc:
        stdout = '{"ok":true,"data":{"txHash":"TX"}}'
        stderr = ""

    def _run(cmd, **kw):
        calls["n"] += 1
        return _Proc()

    monkeypatch.setattr(bb.subprocess, "run", _run)
    return calls


def test_sandbox_uses_devnet_chain_and_url():
    fc = _FakeClient()
    ad = _adapter(sandbox=True, http_client=fc)
    ad.buy("MINT", 0.1)
    post = fc.posts[0]
    assert post["url"] == "https://cdn.based.bid/api/sol/lbp-buy"
    assert post["body"]["chainId"] == 5011 and post["body"]["isSandboxMode"] is True
    assert post["body"]["signer"] == "OWNER" and post["body"]["memeMint"] == "MINT"


def test_prod_uses_mainnet_chain_and_url():
    fc = _FakeClient()
    _adapter(sandbox=False, http_client=fc).sell("M", 0.2)
    post = fc.posts[0]
    assert post["url"] == "https://static.based.bid/api/sol/lbp-sell"
    assert post["body"]["chainId"] == 501 and post["body"]["isSandboxMode"] is False


def test_dry_run_never_submits(no_submit):
    fc = _FakeClient()
    out = _adapter(dry_run=True, http_client=fc).buy("M", 0.1, confirm=True)
    assert out.ok and out.submitted is False and "dry_run" in out.detail
    assert no_submit["n"] == 0


def test_armed_but_unconfirmed_never_submits(no_submit):
    fc = _FakeClient()
    out = _adapter(dry_run=False, http_client=fc).buy("M", 0.1, confirm=False)
    assert out.submitted is False and "confirm=False" in out.detail
    assert no_submit["n"] == 0


def test_both_gates_submit_via_tee(no_submit):
    fc = _FakeClient()
    out = _adapter(dry_run=False, sandbox=True, http_client=fc).buy("M", 0.1, confirm=True)
    assert out.ok and out.submitted is True and out.tx_hash == "TX"
    assert no_submit["n"] == 1


def test_api_key_header_only_when_set():
    fc = _FakeClient()
    _adapter(api_key="bb_live_x", http_client=fc).buy("M", 0.1)
    assert fc.posts[0]["headers"].get("x-api-key") == "bb_live_x"
    fc2 = _FakeClient()
    _adapter(http_client=fc2).buy("M", 0.1)
    assert "x-api-key" not in fc2.posts[0]["headers"]


def test_missing_transaction_surfaces():
    fc = _FakeClient(resp={"error": "no such pool"})
    out = _adapter(dry_run=False, http_client=fc).buy("M", 0.1, confirm=True)
    assert out.ok is False and "no transaction" in out.detail


def test_api_error_surfaces(monkeypatch):
    class _Boom:
        def post(self, *a, **k):
            raise RuntimeError("502")

    out = _adapter(http_client=_Boom()).buy("M", 0.1, confirm=True)
    assert out.ok is False and "based.bid API error" in out.detail


# ── NEW: safety-gate coverage (the kill-switch + caps must cover based.bid) ──
def test_global_kill_blocks_no_broadcast(no_submit):
    """Global kill engaged → refuse, NEVER reach the onchainos contract-call."""
    fc = _FakeClient()
    out = _adapter(dry_run=False, http_client=fc, global_kill_fn=lambda: True).buy(
        "M", 0.1, confirm=True
    )
    assert out.ok is False and out.submitted is False
    assert "safety-gate denied" in out.detail and "kill_switch" in out.detail
    assert no_submit["n"] == 0  # broadcast NEVER fired


def test_notional_cap_blocks_no_broadcast(no_submit):
    """Policy notional cap below the order → refuse, no broadcast.
    0.1 SOL * $250/SOL = $25 notional; cap at $5 → deny."""
    fc = _FakeClient()
    out = _adapter(
        dry_run=False, http_client=fc, policy=ts.basedbid_policy(max_notional_usd=5.0)
    ).buy("M", 0.1, confirm=True)
    assert out.ok is False and out.submitted is False
    assert "safety-gate denied" in out.detail and "notional" in out.detail
    assert no_submit["n"] == 0


def test_unverified_strategy_blocks_no_broadcast(no_submit):
    """Deny-default: no DEPLOY verdict → refuse even within caps + kill off."""
    fc = _FakeClient()
    out = _adapter(
        dry_run=False, http_client=fc, safety_ctx=ts.SafetyContext(strategy_verdict=None)
    ).buy("M", 0.1, confirm=True)
    assert out.ok is False and out.submitted is False
    assert "safety-gate denied" in out.detail and "not DEPLOY" in out.detail
    assert no_submit["n"] == 0


def test_within_caps_kill_off_confirmed_proceeds(no_submit):
    """Within caps + kill off + DEPLOY + confirm + armed → proceeds (mocked broadcast)."""
    fc = _FakeClient()
    out = _adapter(dry_run=False, sandbox=True, http_client=fc).buy("M", 0.1, confirm=True)
    assert out.ok is True and out.submitted is True
    assert no_submit["n"] == 1


def test_default_policy_honors_global_kill_when_nothing_wired(no_submit, monkeypatch):
    """Un-wired path (default policy, default kill resolver) still honors the global
    kill: monkeypatch agent_store.is_global_kill → True and assert no broadcast."""
    import agent_store

    monkeypatch.setattr(agent_store, "is_global_kill", lambda: True)
    fc = _FakeClient()
    # NO policy / safety_ctx / global_kill_fn passed → all defaults
    out = bb.BasedBidExecutionAdapter("OWNER", dry_run=False, http_client=fc).buy(
        "M", 0.1, confirm=True
    )
    assert out.ok is False and out.submitted is False
    assert "kill_switch" in out.detail
    assert no_submit["n"] == 0
