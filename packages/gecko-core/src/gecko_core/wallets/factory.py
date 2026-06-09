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

GRANTSTORE SELECTION. When the Privy branch is taken we persist the grant
mapping in Supabase IFF Supabase is configured: `SupabaseGrantStore` (same
`GrantStore` Protocol; `wallet_links` + `agent_grants` in the Supabase remodel)
survives across processes/replicas — the prod-persistence prerequisite for
flipping `GECKO_WALLET_PROVIDER` to Privy. The Supabase client is built lazily
(on first grant op), so picking it here costs no network call.

If Supabase is NOT configured we fall back to the in-memory `GrantStore` and emit
a LOUD `logger.warning` — that store does NOT persist across processes, so a
multi-process prod Privy deploy on the in-memory store would lose grant state
between replicas. The in-memory fallback is fine for single-replica / dev.
"""

from __future__ import annotations

import logging
import os

from gecko_core.wallets.privy import PrivyClient, is_privy_configured
from gecko_core.wallets.privy_adapter import GrantStore, PrivyWalletAdapter
from gecko_core.wallets.provider import StubWalletProvider, WalletProvider

logger = logging.getLogger(__name__)


def make_wallet_provider() -> WalletProvider:
    """Return the wallet provider for the current environment.

    Returns `StubWalletProvider` unless Privy is fully configured AND the
    `GECKO_WALLET_PROVIDER` env var is not the literal `"stub"`. When Privy is
    enabled, the grant store is Supabase-backed if Supabase is configured, else
    an in-memory fallback (with a loud warning — see module docstring).
    """
    if os.environ.get("GECKO_WALLET_PROVIDER", "").strip() == "stub":
        return StubWalletProvider()
    if not is_privy_configured():
        return StubWalletProvider()
    # Privy enabled. PrivyClient reads PRIVY_APP_ID/SECRET from env (already
    # validated non-sentinel by is_privy_configured) and is lazy — no network
    # call until a real operation.
    return PrivyWalletAdapter(PrivyClient(), store=_make_grant_store())


def _make_grant_store() -> GrantStore:
    """Supabase-backed store when configured (prod persistence), else in-memory.

    `is_supabase_configured()` is a cheap, network-free env/sentinel check, and
    `SupabaseGrantStore` builds its client lazily, so this never touches the
    network or reads the service-role key at wiring time.
    """
    from gecko_core.db import is_supabase_configured

    if is_supabase_configured():
        from gecko_core.wallets.supabase_grant_store import SupabaseGrantStore

        # SupabaseGrantStore conforms to the GrantStore get/put surface.
        return SupabaseGrantStore()  # type: ignore[return-value]

    logger.warning(
        "Privy enabled but Supabase is NOT configured — using the in-memory "
        "GrantStore. Grant state will NOT persist across processes/replicas; do "
        "NOT run Privy in multi-process prod on this fallback. Configure "
        "SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY for persistence."
    )
    return GrantStore()


__all__ = ["make_wallet_provider"]
