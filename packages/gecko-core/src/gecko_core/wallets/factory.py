"""Env-gated wallet-provider factory (V1 Phase 2, Task 2.3).

`make_wallet_provider()` is the ONE place the rest of the system decides which
`WalletProvider` to use. The decision is intentionally trivial and fail-safe:

    PrivyWalletAdapter   IFF   is_privy_configured()  AND  GECKO_WALLET_PROVIDER != "stub"
    StubWalletProvider   otherwise.

DEFAULT IS THE STUB. With no Privy creds (the normal dev / test / stub state)
the factory returns `StubWalletProvider` — behavior is byte-identical to the
hardcoded `StubWalletProvider()` that onboarding shipped before this task. The
real adapter only ever appears when an operator has BOTH configured Privy creds
AND not pinned `GECKO_WALLET_PROVIDER=stub`. The explicit `stub` pin always wins
so an operator can force-disable Privy without unsetting creds.

NETWORK-SAFE IMPORT. `PrivyClient` is lazy — its constructor validates creds but
does NOT call Privy; a network call only happens on a real wallet/policy
operation. So importing onboarding (which calls this factory at import time) with
no Privy env returns the stub and never touches the network.

KNOWN LIMITATION — in-memory GrantStore. When the Privy branch is taken we
construct `PrivyWalletAdapter` with a fresh in-memory `GrantStore`. That store
does NOT persist across processes/requests, so enabling Privy in a multi-process
prod deploy will lose grant state between replicas. A Supabase-backed `GrantStore`
(same Protocol; `wallet_links` + `agent_grants` in the Supabase remodel) is a
REQUIRED follow-up before flipping `GECKO_WALLET_PROVIDER` to Privy in prod. This
factory stays advisor-first / single-replica until then.
"""

from __future__ import annotations

import os

from gecko_core.wallets.privy import PrivyClient, is_privy_configured
from gecko_core.wallets.privy_adapter import GrantStore, PrivyWalletAdapter
from gecko_core.wallets.provider import StubWalletProvider, WalletProvider


def make_wallet_provider() -> WalletProvider:
    """Return the wallet provider for the current environment.

    Returns `StubWalletProvider` unless Privy is fully configured AND the
    `GECKO_WALLET_PROVIDER` env var is not the literal `"stub"`. See module
    docstring for the in-memory-GrantStore limitation that gates a prod flip.
    """
    if os.environ.get("GECKO_WALLET_PROVIDER", "").strip() == "stub":
        return StubWalletProvider()
    if not is_privy_configured():
        return StubWalletProvider()
    # Privy enabled. PrivyClient reads PRIVY_APP_ID/SECRET from env (already
    # validated non-sentinel by is_privy_configured) and is lazy — no network
    # call until a real operation. Fresh in-memory GrantStore — see the
    # module-docstring limitation before enabling in multi-process prod.
    return PrivyWalletAdapter(PrivyClient(), store=GrantStore())


__all__ = ["make_wallet_provider"]
