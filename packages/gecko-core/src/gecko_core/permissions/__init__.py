"""Canonical PermissionKey definitions for S26 Permissions Center.

Pattern A — single source of truth. Every consumer (Python backend,
TypeScript app, future SQL CHECK constraint) reads from here. Adding
a new permission requires touching exactly one Python file + the
mirror in gecko-mcpay-app/lib/schemas.ts (`PermissionKeySchema`).

The drift test in `tests/test_permission_keys_consistency.py`
enforces Python-internal Literal == tuple. The TS mirror is kept in
sync by code-review discipline today; when /api/permissions ships
the contract in OpenAPI, the app side becomes auto-derived.
"""

from __future__ import annotations

from typing import Final, Literal

#: Canonical ordered tuple of permission keys. The order is the
#: column order shown in the Permissions Center grid; keep it stable.
PERMISSION_KEYS: Final[tuple[str, ...]] = (
    "read_market",
    "place_trades",
    "move_funds",
    "sign_contracts",
    "withdraw_vault",
    "access_oracle",
)

#: Static type alias derived from PERMISSION_KEYS.
PermissionKey = Literal[
    "read_market",
    "place_trades",
    "move_funds",
    "sign_contracts",
    "withdraw_vault",
    "access_oracle",
]

#: Per-key state. Mirrors PermissionStateSchema in lib/schemas.ts.
PermissionState = Literal["granted", "denied", "pending"]

#: Per-agent Privy server-wallet posture. Mirrors PrivyWalletStatusSchema.
PrivyWalletStatus = Literal["active", "pending_sprint_26", "not_set", "revoked"]

__all__ = [
    "PERMISSION_KEYS",
    "PermissionKey",
    "PermissionState",
    "PrivyWalletStatus",
]
