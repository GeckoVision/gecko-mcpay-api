"""Tests for Jito bundle / dontfront fingerprints (from docs.jito.wtf)."""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.jito import (
    JITO_DONTFRONT_PREFIX,
    JITO_TIP_ACCOUNTS,
    has_dontfront_guard,
    is_jito_bundle_tx,
)

_TIP = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"  # a real tip account


def test_eight_tip_accounts():
    assert len(JITO_TIP_ACCOUNTS) == 8
    assert _TIP in JITO_TIP_ACCOUNTS


def test_bundle_detected_when_tip_account_present():
    keys = ["Payer1111", "SomeProgram1111", _TIP, "DestVault1111"]
    assert is_jito_bundle_tx(keys) is True


def test_not_a_bundle_without_tip_account():
    assert is_jito_bundle_tx(["Payer1111", "SomeProgram1111", "DestVault1111"]) is False
    assert is_jito_bundle_tx([]) is False


def test_dontfront_guard_detected():
    keys = ["Payer1111", f"{JITO_DONTFRONT_PREFIX}111111111111111111111111111111", "Prog1111"]
    assert has_dontfront_guard(keys) is True


def test_no_dontfront_guard():
    assert has_dontfront_guard(["Payer1111", "Prog1111", _TIP]) is False
    assert has_dontfront_guard([]) is False
