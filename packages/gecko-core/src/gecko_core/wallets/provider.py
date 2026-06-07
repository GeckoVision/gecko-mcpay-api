"""Non-custodial wallet-provider seam (V1 Phase A, 2026-06-07).

Custody decision: **Gecko is NON-CUSTODIAL.** The USER owns their wallet keys;
Gecko only ever holds a *scoped, revocable* grant to act on their behalf —
trade-only, with withdrawals locked to the user's own address. See
`memory/project_noncustodial_custody_decision_2026_06_07` +
`docs/superpowers/specs/2026-06-07-phase-a-onboarding-noncustodial-design.md`.

This module is the ONE seam every custody vendor implements — the rest of
gecko-core / gecko-api depends on this Protocol, never on a vendor:

    - Privy embedded wallet + delegated session signer
    - OKX agentic wallet + owner-set transfer-whitelist policy
    - MagicBlock Session Keys (Solana-native scoped, revocable signing)

All three express the same contract: *user owns keys, agent gets a scoped grant,
withdrawals only to the user.* `StubWalletProvider` encodes + ENFORCES the
non-custodial invariants so they're testable without any vendor or network ($0),
and gives every real adapter an executable contract to match.

INVARIANTS (the stub enforces these; every real adapter MUST uphold them):
  1. Custody is ALWAYS ``"user-owned"`` — the provider never returns/holds keys.
  2. ``execute`` only runs actions inside the grant's ``allowed_actions``.
  3. ``withdraw`` can ONLY send to an address in ``withdraw_allowlist`` (= the
     user's own address). No arbitrary external send is EVER in Gecko's scope.
  4. A grant is revocable; after ``revoke`` both execute and withdraw raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

# Non-custodial by construction: there is no "app-owned" value. If a future
# custodial mode is ever needed it must be a deliberate, separately-reviewed
# addition — not a silent default.
Custody = Literal["user-owned"]


class WalletProviderError(Exception):
    """Base for provider errors."""


class NotLinkedError(WalletProviderError):
    """No wallet linked / no grant for this user."""


class ScopeError(WalletProviderError):
    """Action not in the granted scope, or withdraw target not allow-listed."""


class RevokedError(WalletProviderError):
    """The grant has been revoked by the user."""


# The canonical V1 trade-only action set. Withdrawal/unwind back to the user is
# allowed (kamino_withdraw); arbitrary external transfer is NOT in this set.
TRADE_ONLY_ACTIONS: frozenset[str] = frozenset(
    {"kamino_deposit", "kamino_withdraw", "jupiter_swap", "drift_trade"}
)


@dataclass(frozen=True)
class WalletLink:
    """A user-owned wallet bound to a Gecko user. Carries NO key material."""

    user_id: str
    address: str
    provider: str  # "privy" | "okx" | "magicblock" | "stub"
    custody: Custody = "user-owned"


@dataclass(frozen=True)
class Scope:
    """The revocable grant the user gives Gecko's agent."""

    allowed_actions: frozenset[str]
    withdraw_allowlist: frozenset[str]  # addresses funds may go to (= user's own)
    revoked: bool = False


@dataclass(frozen=True)
class ExecReceipt:
    user_id: str
    action: str
    amount: float
    ok: bool
    to_address: str | None = None
    note: str = ""


def user_scope(user_address: str, actions: frozenset[str] = TRADE_ONLY_ACTIONS) -> Scope:
    """The canonical V1 grant: trade-only, withdraw ONLY to the user's own address."""
    return Scope(allowed_actions=actions, withdraw_allowlist=frozenset({user_address}))


@runtime_checkable
class WalletProvider(Protocol):
    """Seam implemented by Privy / OKX / MagicBlock adapters."""

    def link(self, user_id: str, address: str) -> WalletLink: ...
    def grant_scope(self, user_id: str, scope: Scope) -> Scope: ...
    def revoke(self, user_id: str) -> None: ...
    def execute(self, user_id: str, action: str, amount: float) -> ExecReceipt: ...
    def withdraw(self, user_id: str, amount: float, to_address: str) -> ExecReceipt: ...


class StubWalletProvider:
    """In-memory, deterministic, $0. Enforces the non-custodial invariants.

    NEVER holds private keys — it only tracks the public address + the grant.
    Real adapters (Privy/OKX/MagicBlock) replace this but MUST keep the same
    observable behavior (the invariant tests run against this contract)."""

    def __init__(self) -> None:
        self._links: dict[str, WalletLink] = {}
        self._scopes: dict[str, Scope] = {}

    def link(self, user_id: str, address: str) -> WalletLink:
        link = WalletLink(user_id=user_id, address=address, provider="stub", custody="user-owned")
        self._links[user_id] = link
        return link

    def grant_scope(self, user_id: str, scope: Scope) -> Scope:
        if user_id not in self._links:
            raise NotLinkedError(f"no wallet linked for {user_id!r}")
        self._scopes[user_id] = scope
        return scope

    def revoke(self, user_id: str) -> None:
        scope = self._scopes.get(user_id)
        if scope is not None:
            self._scopes[user_id] = Scope(
                allowed_actions=scope.allowed_actions,
                withdraw_allowlist=scope.withdraw_allowlist,
                revoked=True,
            )

    def _live_scope(self, user_id: str) -> Scope:
        scope = self._scopes.get(user_id)
        if scope is None:
            raise NotLinkedError(f"no grant for {user_id!r}")
        if scope.revoked:
            raise RevokedError(f"grant for {user_id!r} was revoked")
        return scope

    def execute(self, user_id: str, action: str, amount: float) -> ExecReceipt:
        scope = self._live_scope(user_id)
        if action not in scope.allowed_actions:
            raise ScopeError(f"action {action!r} not in granted scope")
        return ExecReceipt(user_id=user_id, action=action, amount=amount, ok=True, note="stub-exec")

    def withdraw(self, user_id: str, amount: float, to_address: str) -> ExecReceipt:
        # Withdrawal is SACRED but still bound to the allow-list (= user's own
        # address). It is NOT gated by any kill-switch — callers must not add one.
        scope = self._live_scope(user_id)
        if to_address not in scope.withdraw_allowlist:
            raise ScopeError(
                f"withdraw target {to_address!r} not in allow-list (only the user's own address)"
            )
        return ExecReceipt(
            user_id=user_id,
            action="withdraw",
            amount=amount,
            ok=True,
            to_address=to_address,
            note="stub-withdraw",
        )
