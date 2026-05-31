"""S26-A — schema-drift guard for PermissionKey / PermissionState / PrivyWalletStatus.

Pattern A. Canonical source: `gecko_core.permissions`. This test asserts
the static Literal types match the runtime tuple/values so an editor that
changes one and forgets the other fails CI rather than production.

The TypeScript mirror lives at `gecko-mcpay-app/lib/schemas.ts`
(`PermissionKeySchema`, `PermissionStateSchema`, `PrivyWalletStatusSchema`).
That repo is a sibling, not vendored — sync is enforced by PR review
today, and will become auto-derived once the FastAPI `/api/permissions`
endpoint ships its OpenAPI contract.
"""

from __future__ import annotations

from typing import get_args

from gecko_core.permissions import (
    PERMISSION_KEYS,
    PermissionKey,
    PermissionState,
    PrivyWalletStatus,
)


def test_canonical_permission_keys_value() -> None:
    """Lock the canonical list. Adding a key forces this assertion to
    change, which forces the developer to think about the TS mirror too."""
    assert PERMISSION_KEYS == (
        "read_market",
        "place_trades",
        "move_funds",
        "sign_contracts",
        "withdraw_vault",
        "access_oracle",
    )


def test_permission_key_literal_matches_runtime_tuple() -> None:
    """Static Literal and runtime tuple cannot drift inside permissions/."""
    assert get_args(PermissionKey) == PERMISSION_KEYS


def test_permission_state_literal_values() -> None:
    """Mirror of PermissionStateSchema in lib/schemas.ts."""
    assert set(get_args(PermissionState)) == {"granted", "denied", "pending"}


def test_privy_wallet_status_literal_values() -> None:
    """Mirror of PrivyWalletStatusSchema in lib/schemas.ts.

    `pending_sprint_26` is the explicit transition state — agents whose
    wallet provisioning is deferred until the live Privy spike lands.
    Removing it requires updating both repos AND the existing app mock data.
    """
    assert set(get_args(PrivyWalletStatus)) == {
        "active",
        "pending_sprint_26",
        "not_set",
        "revoked",
    }
