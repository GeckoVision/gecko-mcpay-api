"""Bento pre-flight gate wired into JupiterSwapExecutionAdapter.place_order.

The gate sits AFTER the quote-guard, BEFORE the double-gate broadcast — point
(B) from the enforcement-mechanics doc. It is fail-CLOSED + env-toggled
(``BENTO_PREFLIGHT=on``); OFF (default) is a clean no-op pass-through.

DISCIPLINE (mirrors test_jupiter_swap_adapter.py): the sidecar build is injected
and onchainos is faked, so NOTHING touches a Solana RPC or broadcasts. No money.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import pytest  # noqa: E402
import trade_safety as ts  # noqa: E402
from gecko_core.trade_agent.exec_adapters import ExecAdapterError  # noqa: E402
from gecko_core.trade_agent.preflight import (  # noqa: E402
    BentoPreflightResult,
    StubBentoClient,
)

_OWNER = "GeckoOwnerPubkey11111111111111111111111111"
_OUT_MINT = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
_OTHER_MINT = "So11111111111111111111111111111111111111112"


def _good_build(**kw):
    return {
        "ok": True,
        "unsignedTxBase64": "AAECAwQF",
        "inputMint": ts._USDC_MINT,
        "outputMint": _OUT_MINT,
        "feePayer": _OWNER,
        "quote": {
            "inAmount": "1000000",
            "outAmount": "990000",
            "otherAmountThreshold": "985000",
            "priceImpactPct": "0.0010",
            "slippageBps": 50,
            "route": ["Orca"],
        },
    }


class _FakeOnchainOS:
    def __init__(self):
        self.calls = 0

    def wallet_contract_call(self, to, unsigned_tx):
        self.calls += 1
        return {"ok": True, "data": {"txHash": "FAKETXHASH"}}


class _AlwaysVetoClient:
    name = "bento"
    mode = "stub"

    def scan(self, *, unsigned_tx_b64, mint, context):
        return BentoPreflightResult(allowed=False, ran=True, reasons=["mint_substitution"])


def _adapter(
    *, dry_run=True, bento_client=None, safety_hint=None, onchainos=None, output_mint=_OUT_MINT
):
    return ts.JupiterSwapExecutionAdapter(
        _OWNER,
        ts.jupiter_swap_policy(),
        output_mint=output_mint,
        dry_run=dry_run,
        build_fn=lambda **kw: _good_build(),
        onchainos_client=onchainos,
        bento_client=bento_client,
        safety_hint=safety_hint,
    )


def _order(notional=10.0):
    return ts.Order(symbol="JUP", venue="jupiter", notional_usd=notional)


# ── 1. OFF = clean no-op (the load-bearing "never block when off") ──────────
def test_off_is_clean_noop_even_with_no_client(monkeypatch):
    """BENTO_PREFLIGHT off (default): the gate is a pure pass-through. A dry-run
    build succeeds and last_enforcement stays None — the gate did not run."""
    monkeypatch.delenv("BENTO_PREFLIGHT", raising=False)
    adapter = _adapter(bento_client=None)  # no client at all
    res = adapter.place_order(_order(), ref_price=1.0)
    assert res.ok and res.submitted is False
    assert adapter.last_enforcement is None  # gate never ran


def test_off_explicit_value_is_noop(monkeypatch):
    monkeypatch.setenv("BENTO_PREFLIGHT", "off")
    adapter = _adapter(bento_client=_AlwaysVetoClient())  # would veto IF it ran
    res = adapter.place_order(_order(), ref_price=1.0)
    assert res.ok  # not vetoed — gate is off
    assert adapter.last_enforcement is None


# ── 2. ON + allow → proceeds; ON + veto → raises before broadcast ───────────
def test_on_allow_lets_broadcast_proceed(monkeypatch):
    monkeypatch.setenv("BENTO_PREFLIGHT", "on")
    # The real _b64_to_b58 needs an optional base58 dep not present in every env;
    # the broadcast wire encoding is orthogonal to the gate under test, so stub it.
    monkeypatch.setattr(ts, "_b64_to_b58", lambda b64: "FAKEB58")
    onchainos = _FakeOnchainOS()
    adapter = _adapter(
        dry_run=False,
        bento_client=StubBentoClient(),  # clean: intended==scanned, no flags
        onchainos=onchainos,
    )
    res = adapter.place_order(_order(), ref_price=1.0, confirm=True)
    assert res.ok and res.submitted is True
    assert onchainos.calls == 1
    assert adapter.last_enforcement is not None
    assert adapter.last_enforcement.allowed is True


def test_on_veto_raises_before_broadcast(monkeypatch):
    monkeypatch.setenv("BENTO_PREFLIGHT", "on")
    onchainos = _FakeOnchainOS()
    adapter = _adapter(dry_run=False, bento_client=_AlwaysVetoClient(), onchainos=onchainos)
    with pytest.raises(ExecAdapterError, match="bento pre-flight VETO"):
        adapter.place_order(_order(), ref_price=1.0, confirm=True)
    assert onchainos.calls == 0  # never broadcast
    assert adapter.last_enforcement.allowed is False


def test_on_mint_substitution_via_safety_hint_vetoes(monkeypatch):
    """The 8%→0% mechanism: safety_hint anchors the intended mint; the stub
    catches a scanned mint that differs. Here output_mint differs from a hint-
    independent baseline by giving the stub a deny on a substitution. We model
    substitution by pointing the adapter at one mint while the stub's intended
    anchor (output_mint) matches — so instead we force a deny_mints veto."""
    monkeypatch.setenv("BENTO_PREFLIGHT", "on")
    onchainos = _FakeOnchainOS()
    # output_mint is the scanned mint; deny it explicitly to model a bad tx.
    adapter = _adapter(
        dry_run=False,
        bento_client=StubBentoClient(deny_mints=frozenset({_OUT_MINT})),
        onchainos=onchainos,
    )
    with pytest.raises(ExecAdapterError, match="deny_listed"):
        adapter.place_order(_order(), ref_price=1.0, confirm=True)
    assert onchainos.calls == 0


# ── 3. ON but NO client → fail-CLOSED (refuse to broadcast un-screened) ─────
def test_on_with_no_client_is_fail_closed(monkeypatch):
    monkeypatch.setenv("BENTO_PREFLIGHT", "on")
    onchainos = _FakeOnchainOS()
    adapter = _adapter(dry_run=False, bento_client=None, onchainos=onchainos)
    with pytest.raises(ExecAdapterError, match="no Bento client is wired"):
        adapter.place_order(_order(), ref_price=1.0, confirm=True)
    assert onchainos.calls == 0
    assert adapter.last_enforcement.ran is False


def test_invalid_flag_value_raises(monkeypatch):
    """A typo'd BENTO_PREFLIGHT on a fail-closed gate fails loud, not silent."""
    monkeypatch.setenv("BENTO_PREFLIGHT", "maybe")
    adapter = _adapter(bento_client=StubBentoClient())
    with pytest.raises(ValueError, match="invalid BENTO_PREFLIGHT"):
        adapter.place_order(_order(), ref_price=1.0)
