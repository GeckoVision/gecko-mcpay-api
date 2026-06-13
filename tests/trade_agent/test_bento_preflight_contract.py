"""Recorded-fixture contract test for the Bento pre-flight client (Pattern C).

We have NO Bento creds yet, so the live client does not ship. Per CLAUDE.md
Pattern C, the gate on shipping any wire-protocol integration is a recorded
fixture of the facilitator's relevant endpoint shape + a contract test that
pins the conformer against it. This file IS that fixture + contract:

  * ``_FIXTURE`` records the EXPECTED Bento scan-endpoint response shape
    (allow/deny + reason) we are coding against. When real creds land, the
    live client must reproduce these cases against the real endpoint before it
    is allowed to ship.
  * The contract tests assert the StubBentoClient honors the load-bearing
    invariants from the layering doc §3a: mint-equality cross-check (the 8%→0%
    mechanism), and "the advisory hint NEVER disarms the fail-closed veto."

No network, no money, no Solana stack. Pure + fast.
"""

from __future__ import annotations

from gecko_core.trade_agent.preflight import (
    BentoClient,
    BentoPreflightContext,
    BentoPreflightResult,
    StubBentoClient,
    default_bento_client,
)

_CLEAN_MINT = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
_OTHER_MINT = "So11111111111111111111111111111111111111112"

# Recorded fixture: the (input → expected allow/deny + reasons) cases the real
# Bento scan endpoint must reproduce. Each row is a contract case.
_FIXTURE = [
    # name, intended_mint, scanned_mint, rug_flags, checked, expect_allow, expect_reasons
    ("clean_match", _CLEAN_MINT, _CLEAN_MINT, [], True, True, []),
    ("clean_no_hint", None, _CLEAN_MINT, [], False, True, []),
    ("mint_substitution", _CLEAN_MINT, _OTHER_MINT, [], True, False, ["mint_substitution"]),
    (
        "flagged_mint_escalates",
        _CLEAN_MINT,
        _CLEAN_MINT,
        ["mint_not_renounced"],
        True,
        False,
        ["hint:mint_not_renounced"],
    ),
    # A clean Gecko signal (no flags) must NOT relax a substitution veto — the
    # hint can only ADD reasons, never disarm. checked=True + mismatch ⇒ veto.
    (
        "clean_hint_cannot_rescue_substitution",
        _CLEAN_MINT,
        _OTHER_MINT,
        [],
        True,
        False,
        ["mint_substitution"],
    ),
]


def test_stub_conforms_to_bento_client_protocol() -> None:
    assert isinstance(StubBentoClient(), BentoClient)


def test_default_client_is_stub_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("BENTO_MODE", raising=False)
    client = default_bento_client()
    assert isinstance(client, StubBentoClient)
    assert client.mode == "stub"


def test_live_mode_is_gated_not_shipped() -> None:
    """Pattern C: the live client is gated on this contract passing + creds."""
    import pytest

    with pytest.raises(NotImplementedError):
        default_bento_client("live")


def test_recorded_fixture_contract() -> None:
    """Every recorded case reproduces against the stub conformer."""
    client = StubBentoClient()
    for (
        name,
        intended,
        scanned,
        flags,
        checked,
        expect_allow,
        expect_reasons,
    ) in _FIXTURE:
        ctx = BentoPreflightContext(
            intended_mint=intended,
            gecko_rug_flags=list(flags),
            gecko_safety_checked=checked,
        )
        result = client.scan(unsigned_tx_b64="AAECAwQF", mint=scanned, context=ctx)
        assert isinstance(result, BentoPreflightResult)
        assert result.ran is True, name
        assert result.allowed is expect_allow, f"{name}: allow mismatch"
        assert result.reasons == expect_reasons, f"{name}: reasons mismatch"


def test_hint_never_disarms_veto_even_when_signal_clean() -> None:
    """The load-bearing invariant: a fail-OPEN clean signal must not weaken the
    fail-CLOSED veto. A clean hint + a substituted mint still vetoes."""
    client = StubBentoClient()
    ctx = BentoPreflightContext(
        intended_mint=_CLEAN_MINT,
        gecko_rug_flags=[],  # signal says "clean"
        gecko_safety_checked=True,
    )
    result = client.scan(unsigned_tx_b64="AAECAwQF", mint=_OTHER_MINT, context=ctx)
    assert result.allowed is False
    assert "mint_substitution" in result.reasons


def test_explicit_deny_mint_vetoes() -> None:
    client = StubBentoClient(deny_mints=frozenset({_CLEAN_MINT}))
    ctx = BentoPreflightContext(intended_mint=_CLEAN_MINT, gecko_safety_checked=True)
    result = client.scan(unsigned_tx_b64="AAECAwQF", mint=_CLEAN_MINT, context=ctx)
    assert result.allowed is False
    assert "deny_listed" in result.reasons
