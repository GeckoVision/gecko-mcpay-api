"""Real non-custodial custody adapter behind the ``WalletProvider`` seam
(V1 Phase 2, Task 2.2).

``PrivyWalletAdapter`` is the first VENDOR implementation of the
``WalletProvider`` Protocol (the in-memory ``StubWalletProvider`` is the
contract reference). It composes three pieces:

  * ``PrivyClient``        — the async Privy v2 REST client (wallet + policy).
  * ``scope_to_privy_rules`` — pure ``Scope`` → Privy ``rules[]`` mapper (Task 2.1).
  * a ``GrantStore``       — the user → (wallet, policy, scope) persistence seam.

NON-CUSTODIAL INVARIANTS (sacred — identical to the stub; see ``provider.py``):
  1. Custody is ALWAYS ``"user-owned"``. ``link`` returns
     ``WalletLink(custody="user-owned")``. The adapter never holds key material —
     Privy holds the (user-owned) key; we only ever hold a scoped, revocable
     policy grant.
  2. ``execute`` only runs in-scope actions; ``withdraw`` may only target the
     user's own address. Both are enforced against the persisted ``Scope``
     BEFORE any Privy signing call (signing itself is gated — see below).
  3. ``withdraw`` is NEVER kill-switch-gated: a withdraw to the user's own
     address is always permitted by the live scope's allowlist.
  4. ``revoke`` genuinely removes authority (see ``revoke`` docstring for the
     Privy mechanism) and is observable via ``scope_for``.

SIGNING IS GATED (Task D4). ``execute`` and ``withdraw`` raise
``NotImplementedError`` rather than signing. V1 is advisor-first; real signing
lands in a separate, gated task pending live-Privy-doc verification of the
Solana ``signAndSendTransaction`` path. We ship NO half-real signing.

ASYNC BRIDGE. The ``WalletProvider`` Protocol is synchronous, but ``PrivyClient``
is async. The adapter runs each Privy call on a private event loop via
``_run`` so the sync Protocol surface is preserved without leaking a loop
requirement onto every caller. This keeps the adapter a drop-in for the stub.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Final

from gecko_core.wallets.privy import PrivyClient
from gecko_core.wallets.privy_rules import scope_to_privy_rules
from gecko_core.wallets.provider import (
    NotLinkedError,
    RevokedError,
    Scope,
    ScopeError,
    WalletLink,
    WalletProvider,
)

# ---------------------------------------------------------------------------
# Persistence seam.
#
# The canonical home for this mapping is Supabase (`wallet_links` +
# `agent_grants` in migration 20260607010000_supabase_remodel.sql). Those
# tables are RLS-gated and async/Supabase-bound; wiring them directly into a
# unit-tested adapter would force a network/db dependency into the test path.
#
# So we depend on a small `GrantStore` Protocol and ship an in-memory default
# (mirroring how StubWalletProvider keeps its own dicts). The in-memory store
# is $0 + network-free for tests; a Supabase-backed `GrantStore` implementing
# the same Protocol can drop in later, persisting:
#     wallet_links(user_id, address, provider='privy', custody='user-owned')
#     agent_grants(user_id, allowed_actions, withdraw_allowlist, revoked)
# plus the Privy wallet_id + policy_id (held here, not in those tables today).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GrantRecord:
    """Everything the adapter persists per user. Carries NO key material."""

    user_id: str
    wallet_id: str
    address: str
    policy_id: str | None = None
    scope: Scope | None = None


class GrantStore:
    """In-memory user → ``GrantRecord`` store. Swappable for a Supabase impl.

    Methods are sync because the adapter's Protocol surface is sync; a real
    async-backed store would expose the same names and the adapter would bridge
    them through ``_run`` exactly as it does the Privy calls.
    """

    def __init__(self) -> None:
        self._records: dict[str, GrantRecord] = {}

    def get(self, user_id: str) -> GrantRecord | None:
        return self._records.get(user_id)

    def put(self, record: GrantRecord) -> None:
        self._records[record.user_id] = record


# ---------------------------------------------------------------------------
# Deny-all revoke rule.
#
# Revoke must GENUINELY remove authority. We do NOT detach the policy from the
# wallet (Privy's docs do not guarantee an unattached wallet is deny-by-default
# — detaching could widen authority to permissionless signing). Instead we
# rewrite the granted policy's rules to a single deny-all rule (method "*", no
# conditions, action DENY). Because Privy evaluates DENY > ALLOW and the policy
# stays attached, the wallet can sign nothing. Re-granting rewrites the rules
# back, so the policy_id is preserved (audit trail), mirroring the
# `agent_grants.revoked` flag.
# ---------------------------------------------------------------------------
_DENY_ALL_RULE: Final[dict[str, Any]] = {
    "name": "revoked-deny-all",
    "method": "*",
    "conditions": [],
    "action": "DENY",
}

_SIGNING_GATED_MSG: Final[str] = "privy signing — gated task D4"


class PrivyWalletAdapter:
    """``WalletProvider`` implemented over Privy. Non-custodial by construction.

    Construct with an injected ``PrivyClient`` (real or respx-mocked) and an
    optional ``GrantStore``. The client is gated by ``is_privy_configured()``
    at the call site (gecko-api); the adapter itself never reads secrets.
    """

    provider: Final[str] = "privy"

    def __init__(
        self,
        client: PrivyClient,
        *,
        store: GrantStore | None = None,
    ) -> None:
        self._client = client
        self._store = store if store is not None else GrantStore()

    # -- async bridge ----------------------------------------------------

    @staticmethod
    def _run(coro: Any) -> Any:
        """Run a Privy coroutine to completion on a private loop.

        The Protocol surface is sync; PrivyClient is async. ``asyncio.run``
        gives us a fresh loop per call, which is fine for the link/grant/revoke
        control-plane operations (not a hot path). Callers already inside a
        running loop should use the async store/client directly — this adapter
        targets the sync onboarding control plane.
        """
        return asyncio.run(coro)

    # -- WalletProvider --------------------------------------------------

    def link(self, user_id: str, address: str) -> WalletLink:
        """Create (idempotently) the user's Privy wallet and bind it.

        Idempotent per ``user_id``: a second ``link`` for the same user does
        NOT create a second Privy wallet — we short-circuit on the persisted
        mapping. ``user_id`` is passed to Privy as ``external_id`` (owner_label)
        so even a store wipe collides on Privy's side rather than duplicating.

        Custody is ALWAYS ``"user-owned"`` (non-custodial invariant #1).
        """
        existing = self._store.get(user_id)
        if existing is not None:
            return WalletLink(
                user_id=user_id,
                address=existing.address,
                provider=self.provider,
                custody="user-owned",
            )

        wallet = self._run(self._client.create_solana_wallet(owner_label=user_id))
        self._store.put(
            GrantRecord(user_id=user_id, wallet_id=wallet.wallet_id, address=wallet.address)
        )
        return WalletLink(
            user_id=user_id,
            address=wallet.address,
            provider=self.provider,
            custody="user-owned",
        )

    def grant_scope(self, user_id: str, scope: Scope) -> Scope:
        """Create a Privy policy from ``scope`` and attach it to the wallet.

        Builds rules via ``scope_to_privy_rules`` (which itself refuses a
        widened withdraw allowlist — non-custodial invariant #3), creates the
        policy, attaches it, and persists ``(wallet_id, policy_id, scope)``.
        """
        record = self._store.get(user_id)
        if record is None:
            raise NotLinkedError(f"no wallet linked for {user_id!r}")

        # scope_to_privy_rules enforces withdraw_allowlist == {user_address}.
        rules = scope_to_privy_rules(scope, record.address)
        policy = self._run(self._client.create_policy(name=f"gecko-scope-{user_id}", rules=rules))
        self._run(
            self._client.attach_policy_to_wallet(
                wallet_id=record.wallet_id, policy_ids=[policy.policy_id]
            )
        )
        self._store.put(replace(record, policy_id=policy.policy_id, scope=scope))
        return scope

    def scope_for(self, user_id: str) -> Scope | None:
        """The user's current grant (or None if never granted). Read-only.

        Reflects ``revoke``: after a revoke the persisted scope has
        ``revoked=True``.
        """
        record = self._store.get(user_id)
        if record is None:
            return None
        return record.scope

    def revoke(self, user_id: str) -> None:
        """Genuinely remove the granted authority.

        Mechanism: rewrite the attached policy's rules to a single deny-all
        rule (``PATCH /v1/policies/{policy_id}``). The policy STAYS attached, so
        the wallet does not become permissionless — it can now sign nothing.
        We then flip the persisted scope's ``revoked`` flag so ``scope_for``
        and the local execute/withdraw guards reflect it immediately.

        No-op if the user has no live grant.
        """
        record = self._store.get(user_id)
        if record is None or record.scope is None:
            return
        if record.policy_id is not None:
            self._run(
                self._client.update_policy_rules(policy_id=record.policy_id, rules=[_DENY_ALL_RULE])
            )
        revoked = replace(record.scope, revoked=True)
        self._store.put(replace(record, scope=revoked))

    def _live_scope(self, user_id: str) -> Scope:
        record = self._store.get(user_id)
        if record is None or record.scope is None:
            raise NotLinkedError(f"no grant for {user_id!r}")
        if record.scope.revoked:
            raise RevokedError(f"grant for {user_id!r} was revoked")
        return record.scope

    def execute(self, user_id: str, action: str, amount: float) -> Any:
        """Gated (Task D4). Enforces scope first, then refuses to sign.

        We still run the non-custodial guards (live-scope + allowlist) so the
        gate's error shape matches the stub for revoked / out-of-scope cases,
        and only raise the signing-gated error for an otherwise-valid call.
        """
        scope = self._live_scope(user_id)
        if action not in scope.allowed_actions:
            raise ScopeError(f"action {action!r} not in granted scope")
        raise NotImplementedError(_SIGNING_GATED_MSG)

    def withdraw(self, user_id: str, amount: float, to_address: str) -> Any:
        """Gated (Task D4). Withdraw-to-self allowlist enforced, then refuses.

        Withdrawal is sacred and never kill-switch-gated, but it is still bound
        to the allowlist (= the user's own address). The allowlist check runs
        before the signing-gated raise so an exfiltration attempt surfaces as a
        ``ScopeError`` exactly like the stub.
        """
        scope = self._live_scope(user_id)
        if to_address not in scope.withdraw_allowlist:
            raise ScopeError(
                f"withdraw target {to_address!r} not in allow-list (only the user's own address)"
            )
        raise NotImplementedError(_SIGNING_GATED_MSG)


# Structural conformance: the adapter satisfies the WalletProvider Protocol.
_: WalletProvider = PrivyWalletAdapter.__new__(PrivyWalletAdapter)


__all__ = [
    "GrantRecord",
    "GrantStore",
    "PrivyWalletAdapter",
]
