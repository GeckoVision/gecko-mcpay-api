"""make_wallet_provider() — env-gated wallet-provider factory (V1 Phase 2, Task 2.3).

The factory is the ONE place gecko-api decides which `WalletProvider` to use:

    PrivyWalletAdapter  IFF  is_privy_configured()  AND  GECKO_WALLET_PROVIDER != "stub"
    StubWalletProvider  otherwise (the dev/test/stub default — byte-identical to today).

These tests monkeypatch the environment + `is_privy_configured` so they never
read real Privy creds and never touch the network. Constructing the Privy branch
must NOT make a network call (PrivyClient is lazy — it only calls Privy on a real
wallet/policy operation), so the `creds present` case asserts on type alone.
"""

from __future__ import annotations

import gecko_core.wallets.factory as factory
from gecko_core.wallets import StubWalletProvider
from gecko_core.wallets.factory import make_wallet_provider
from gecko_core.wallets.privy_adapter import PrivyWalletAdapter


def test_no_privy_creds_returns_stub(monkeypatch):
    """(a) no Privy creds → StubWalletProvider, regardless of GECKO_WALLET_PROVIDER."""
    monkeypatch.delenv("GECKO_WALLET_PROVIDER", raising=False)
    monkeypatch.setattr(factory, "is_privy_configured", lambda: False)
    assert isinstance(make_wallet_provider(), StubWalletProvider)


def test_explicit_stub_override_wins_even_with_creds(monkeypatch):
    """(b) GECKO_WALLET_PROVIDER=stub → StubWalletProvider even when creds present."""
    monkeypatch.setenv("GECKO_WALLET_PROVIDER", "stub")
    monkeypatch.setattr(factory, "is_privy_configured", lambda: True)
    assert isinstance(make_wallet_provider(), StubWalletProvider)


def test_creds_present_not_overridden_returns_privy_adapter(monkeypatch):
    """(c) creds present + not overridden → PrivyWalletAdapter."""
    monkeypatch.delenv("GECKO_WALLET_PROVIDER", raising=False)
    monkeypatch.setattr(factory, "is_privy_configured", lambda: True)
    # PrivyClient is lazy — constructing the adapter must not call Privy. Provide
    # sentinel-free creds so the (eager) PrivyClient constructor is satisfied.
    monkeypatch.setenv("PRIVY_APP_ID", "test-app-id")
    monkeypatch.setenv("PRIVY_APP_SECRET", "test-app-secret")
    provider = make_wallet_provider()
    assert isinstance(provider, PrivyWalletAdapter)


def test_provider_value_other_than_stub_does_not_block_privy(monkeypatch):
    """Only the literal "stub" override forces the stub; e.g. "privy" still routes
    to the adapter when creds are present (the override is a stub-pin, not a vendor
    selector — vendor selection beyond Privy is a later task)."""
    monkeypatch.setenv("GECKO_WALLET_PROVIDER", "privy")
    monkeypatch.setattr(factory, "is_privy_configured", lambda: True)
    monkeypatch.setenv("PRIVY_APP_ID", "test-app-id")
    monkeypatch.setenv("PRIVY_APP_SECRET", "test-app-secret")
    assert isinstance(make_wallet_provider(), PrivyWalletAdapter)
