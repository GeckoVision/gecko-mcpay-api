"""Wallet provisioning + balance helpers (S2-05).

Currently only Privy v2 embedded wallets. Lazy-instantiated; the rest of
gecko-core never imports this module unless `is_privy_configured()` returns
True at the call site, so devnet flows without Privy keys keep working.
"""

from gecko_core.wallets.privy import (
    PrivyClient,
    PrivyClientError,
    PrivyNotConfiguredError,
    PrivyPolicy,
    PrivyWallet,
    is_privy_configured,
)
from gecko_core.wallets.provider import (
    TRADE_ONLY_ACTIONS,
    ExecReceipt,
    NotLinkedError,
    RevokedError,
    Scope,
    ScopeError,
    StubWalletProvider,
    WalletLink,
    WalletProvider,
    WalletProviderError,
    user_scope,
)

__all__ = [
    "TRADE_ONLY_ACTIONS",
    "ExecReceipt",
    "NotLinkedError",
    "PrivyClient",
    "PrivyClientError",
    "PrivyNotConfiguredError",
    "PrivyPolicy",
    "PrivyWallet",
    "RevokedError",
    "Scope",
    "ScopeError",
    "StubWalletProvider",
    "WalletLink",
    "WalletProvider",
    "WalletProviderError",
    "is_privy_configured",
    "user_scope",
]
