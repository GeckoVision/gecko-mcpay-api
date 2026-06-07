"""Phase 2 — Jupiter swap execution adapter + kill-switch.

DISCIPLINE: every test mocks the subprocess sidecar build AND the onchainos CLI,
so NOTHING ever touches a Solana RPC or broadcasts a tx. Mirrors the Kamino
live-executor test posture (test_live_executor.py). No network, no money, ever.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import pytest  # noqa: E402
import trade_safety as ts  # noqa: E402

_OWNER = "GeckoOwnerPubkey11111111111111111111111111"
_OUT_MINT = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"  # arbitrary output mint


def _good_build(price_impact="0.0010", out="990000", thresh="985000", **kw):
    """A well-formed sidecar envelope (priceImpactPct 0.10% by default)."""
    return {
        "ok": True,
        "unsignedTxBase64": "AAECAwQF",  # nonsense base64; never decoded unless we submit
        "inputMint": ts._USDC_MINT,
        "outputMint": _OUT_MINT,
        "feePayer": _OWNER,
        "quote": {
            "inAmount": "1000000",
            "outAmount": out,
            "otherAmountThreshold": thresh,
            "priceImpactPct": price_impact,
            "slippageBps": 50,
            "route": ["Orca", "Raydium"],
        },
    }


class _FakeOnchainOS:
    """Records contract-call invocations; returns a fake txHash. NEVER shells out."""

    def __init__(self, resp=None):
        self.calls = 0
        self.last_unsigned = None
        self._resp = resp or {"ok": True, "data": {"txHash": "FAKETXHASH"}}

    def wallet_contract_call(self, to, unsigned_tx):
        self.calls += 1
        self.last_unsigned = unsigned_tx
        return self._resp


def _adapter(build, *, dry_run=True, policy=None, onchainos=None, slippage_bps=50):
    """Construct an adapter with the sidecar build injected (no subprocess)."""
    pol = policy or ts.jupiter_swap_policy()
    return ts.JupiterSwapExecutionAdapter(
        _OWNER,
        pol,
        output_mint=_OUT_MINT,
        slippage_bps=slippage_bps,
        dry_run=dry_run,
        build_fn=lambda **kw: dict(build),
        onchainos_client=onchainos,
    )


def _order(notional=10.0):
    return ts.Order(symbol="JUP", venue="jupiter", notional_usd=notional)


# ── 1. sidecar-build parse (the bridge envelope → adapter) ──────────────────
def test_sidecar_build_parses_quote_into_dry_result():
    adapter = _adapter(_good_build())
    res = adapter.place_order(_order(), ref_price=1.0)
    assert res.ok and res.submitted is False
    assert "out=990000" in res.detail and "impact=0.0010" in res.detail
    # the build envelope is captured for the dashboard
    assert adapter.last_build is not None
    assert adapter.last_build["quote"]["route"] == ["Orca", "Raydium"]


def test_conforms_to_execution_adapter_protocol():
    adapter = _adapter(_good_build())
    assert isinstance(adapter, ts.ExecutionAdapter)
    assert adapter.venue == "jupiter"


# ── 2. adapter price-impact reject (the memecoin-slippage guard) ────────────
def test_price_impact_over_cap_rejected(monkeypatch):
    # priceImpactPct 0.05 = 500 bps; default cap is 100 bps → reject, never submit.
    build = _good_build(price_impact="0.05")
    oc = _FakeOnchainOS()
    adapter = _adapter(build, dry_run=False, onchainos=oc)
    res = adapter.place_order(_order(), ref_price=1.0, confirm=True)
    assert res.ok is False and res.submitted is False
    assert "quote-guard denied" in res.detail and "price impact" in res.detail
    assert oc.calls == 0  # fail-closed: no broadcast on a bad quote


def test_zero_min_out_rejected():
    build = _good_build(thresh="0")
    oc = _FakeOnchainOS()
    adapter = _adapter(build, dry_run=False, onchainos=oc)
    res = adapter.place_order(_order(), ref_price=1.0, confirm=True)
    assert res.ok is False and "no enforceable slippage floor" in res.detail
    assert oc.calls == 0


def test_price_impact_at_cap_passes_guard():
    # exactly at cap (100 bps = 0.01) must NOT be rejected (strict > comparison).
    build = _good_build(price_impact="0.01")
    adapter = _adapter(build, dry_run=True)
    res = adapter.place_order(_order(), ref_price=1.0)
    assert res.ok and "quote-guard denied" not in res.detail


# ── 3. adapter dry-no-submit (gate 1) ───────────────────────────────────────
def test_dry_run_never_submits():
    oc = _FakeOnchainOS()
    adapter = _adapter(_good_build(), dry_run=True, onchainos=oc)
    res = adapter.place_order(_order(), ref_price=1.0, confirm=True)  # confirm but dry
    assert res.ok and res.submitted is False and "dry_run" in res.detail
    assert oc.calls == 0


def test_armed_but_unconfirmed_never_submits():
    oc = _FakeOnchainOS()
    adapter = _adapter(_good_build(), dry_run=False, onchainos=oc)
    res = adapter.place_order(_order(), ref_price=1.0, confirm=False)  # armed, not confirmed
    assert res.ok and res.submitted is False and "confirm=False" in res.detail
    assert oc.calls == 0


def test_dispatch_never_passes_confirm():
    # dispatch() calls place_order WITHOUT confirm → even an armed adapter is dry.
    oc = _FakeOnchainOS()
    adapter = _adapter(_good_build(), dry_run=False, onchainos=oc)
    ctx = ts.SafetyContext(strategy_verdict="DEPLOY")
    res = ts.dispatch(_order(), adapter.policy, ctx, adapter, ref_price=1.0)
    assert res.submitted is False and oc.calls == 0


# ── 4. both-gates-submit (mocked TEE) ───────────────────────────────────────
def test_both_gates_submits_mocked():
    oc = _FakeOnchainOS()
    adapter = _adapter(_good_build(), dry_run=False, onchainos=oc)
    res = adapter.place_order(_order(), ref_price=1.0, confirm=True)  # both gates
    assert res.ok and res.submitted is True and res.tx_hash == "FAKETXHASH"
    assert oc.calls == 1
    assert adapter.last_build is not None  # tx was built before submit


def test_contract_call_error_surfaces():
    # an error key in the CLI response → surface verbatim, never faked-success
    oc = _FakeOnchainOS(resp={"error": "policy limit exceeded"})
    adapter = _adapter(_good_build(), dry_run=False, onchainos=oc)
    res = adapter.place_order(_order(), ref_price=1.0, confirm=True)
    assert res.ok is False and res.submitted is False
    assert "contract-call error" in res.detail and "policy limit exceeded" in res.detail


def test_contract_call_ok_false_surfaces():
    # ok=false (no error key) → surface as a failed submit, never faked-success
    oc = _FakeOnchainOS(resp={"ok": False})
    adapter = _adapter(_good_build(), dry_run=False, onchainos=oc)
    res = adapter.place_order(_order(), ref_price=1.0, confirm=True)
    assert res.ok is False and res.submitted is False and "ok=false" in res.detail


def test_sidecar_build_failure_surfaces():
    def _boom(**kw):
        raise ts.SwapSidecarError("Error: Jupiter /quote HTTP 400: no route found")

    adapter = ts.JupiterSwapExecutionAdapter(
        _OWNER,
        ts.jupiter_swap_policy(),
        output_mint=_OUT_MINT,
        dry_run=False,
        build_fn=_boom,
    )
    res = adapter.place_order(_order(), ref_price=1.0, confirm=True)
    assert res.ok is False and "no route found" in res.detail  # verbatim


# ── 5. kill-switch denies (per-agent + global) ──────────────────────────────
def test_kill_switch_denies_at_gate():
    pol = ts.jupiter_swap_policy()
    pol.kill_switch = True
    ctx = ts.SafetyContext(strategy_verdict="DEPLOY")
    res = ts.dispatch(_order(), pol, ctx, _adapter(_good_build()), ref_price=1.0)
    assert res.ok is False and "kill_switch engaged" in res.detail


def test_global_kill_folds_into_policy():
    pol = ts.jupiter_swap_policy()
    assert pol.kill_switch is False
    killed = ts.with_global_kill(pol, global_kill=True)
    assert killed.kill_switch is True
    # original untouched (we did not mutate the stored policy)
    assert pol.kill_switch is False
    # no global kill → returns the same policy object
    assert ts.with_global_kill(pol, global_kill=False) is pol


def test_global_kill_denies_dispatch():
    pol = ts.with_global_kill(ts.jupiter_swap_policy(), global_kill=True)
    ctx = ts.SafetyContext(strategy_verdict="DEPLOY")
    oc = _FakeOnchainOS()
    adapter = _adapter(_good_build(), dry_run=False, onchainos=oc)
    res = ts.dispatch(_order(), pol, ctx, adapter, ref_price=1.0)
    assert res.ok is False and "kill_switch engaged" in res.detail
    assert oc.calls == 0  # never reached the adapter


# ── policy helper: jupiter venue opt-in is per-agent, not default ────────────
def test_jupiter_not_in_default_allowed_venues():
    assert "jupiter" not in ts.TradeSafetyPolicy().allowed_venues


def test_jupiter_policy_enables_venue_and_passes_gate():
    pol = ts.jupiter_swap_policy(max_notional_usd=25.0)
    assert "jupiter" in pol.allowed_venues
    ctx = ts.SafetyContext(strategy_verdict="DEPLOY")
    v = ts.check_order(_order(10.0), pol, ctx)
    assert v.allow is True


def test_unverified_strategy_blocked_on_jupiter():
    pol = ts.jupiter_swap_policy()
    ctx = ts.SafetyContext(strategy_verdict="PAPER ONLY")
    v = ts.check_order(_order(10.0), pol, ctx)
    assert v.allow is False and any("not DEPLOY" in r for r in v.reasons)


# ── base-units conversion (no float drift) ──────────────────────────────────
@pytest.mark.parametrize("usd,expected", [(10.0, "10000000"), (1.5, "1500000"), (0.25, "250000")])
def test_usd_to_base_units(usd, expected):
    adapter = _adapter(_good_build())
    assert adapter._to_base_units(usd) == expected
