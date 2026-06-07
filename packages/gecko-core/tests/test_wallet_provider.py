"""Non-custodial WalletProvider seam — invariant contract tests.

These run against StubWalletProvider but encode the contract EVERY vendor
adapter (Privy / OKX / MagicBlock) must satisfy.
"""

from __future__ import annotations

import pytest
from gecko_core.wallets import (
    NotLinkedError,
    RevokedError,
    ScopeError,
    StubWalletProvider,
    WalletProvider,
    user_scope,
)

USER = "user-1"
USER_ADDR = "USERaddr1111111111111111111111111111111111"
EVIL_ADDR = "ATTACKERaddr22222222222222222222222222222222"


def _linked() -> StubWalletProvider:
    p = StubWalletProvider()
    p.link(USER, USER_ADDR)
    p.grant_scope(USER, user_scope(USER_ADDR))
    return p


def test_stub_satisfies_protocol():
    assert isinstance(StubWalletProvider(), WalletProvider)


def test_custody_is_always_user_owned_and_no_keys_returned():
    link = StubWalletProvider().link(USER, USER_ADDR)
    assert link.custody == "user-owned"
    # the link object carries NO private-key field
    assert not any("key" in f.lower() or "secret" in f.lower() for f in vars(link))


def test_execute_allows_in_scope_action():
    r = _linked().execute(USER, "kamino_deposit", 100.0)
    assert r.ok and r.action == "kamino_deposit"


def test_execute_rejects_out_of_scope_action():
    with pytest.raises(ScopeError):
        _linked().execute(USER, "send_to_anyone", 100.0)  # not in trade-only scope


def test_withdraw_only_to_user_address():
    r = _linked().withdraw(USER, 50.0, USER_ADDR)
    assert r.ok and r.to_address == USER_ADDR


def test_withdraw_to_other_address_blocked():
    with pytest.raises(ScopeError):
        _linked().withdraw(USER, 50.0, EVIL_ADDR)  # not allow-listed → can't exfiltrate


def test_revoke_blocks_execute_and_withdraw():
    p = _linked()
    p.revoke(USER)
    with pytest.raises(RevokedError):
        p.execute(USER, "kamino_deposit", 1.0)
    with pytest.raises(RevokedError):
        p.withdraw(USER, 1.0, USER_ADDR)


def test_grant_requires_link():
    p = StubWalletProvider()
    with pytest.raises(NotLinkedError):
        p.grant_scope(USER, user_scope(USER_ADDR))


def test_execute_requires_grant():
    p = StubWalletProvider()
    p.link(USER, USER_ADDR)
    with pytest.raises(NotLinkedError):
        p.execute(USER, "kamino_deposit", 1.0)
