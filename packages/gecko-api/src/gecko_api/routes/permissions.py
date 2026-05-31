"""S26-C — Permissions Center backend.

`GET /v1/permissions` returns the per-agent permission grid the app's
`PermissionsView` consumes. Mirrors the Zod schema in
gecko-mcpay-app/lib/schemas.ts (`PermissionsResponseSchema` /
`AgentPermissionsSchema`) — Pattern A enforcement.

Today's behavior:
- Default response is the "mock" shape — same lanes + agent IDs the app's
  `INITIAL_PERMISSIONS` mock surfaces — so the frontend can ship the wire
  without Privy creds being live.
- When `PRIVY_APP_ID` + `PRIVY_APP_SECRET` are non-sentinel AND the
  caller passes `?include_wallets=true`, we look up the project's
  Privy wallet (existing `bind_privy_wallet` rows in sessions store)
  and replace `privy_wallet_status` with the real status.
- `place_trades` / `move_funds` / `withdraw_vault` are gated server-side
  on wallet presence — agents with `privy_wallet_status != "active"`
  always get `pending` for those keys regardless of the per-agent
  authorization bitset.

What this endpoint is NOT (deferred to later S26 work):
- The scope-policy editor — that lives in S26-D's app shell + needs a
  PATCH /v1/permissions/{agent_id} endpoint with PrivyClient.attach_policy.
- The audit log of permission changes — Sprint 27+.
- Persistence of per-agent permission overrides — today's response is
  derived (lane → default grid). The app's optimistic-toggle UI will
  block on a writable backend until the Mongo `agent_permissions`
  collection lands.

CORS / auth: this route is mounted under the app-wide CORS middleware
(geckovision.tech origins) and the existing auth chain. No special
public surface — the Permissions Center is for authenticated builders
looking at their own agent fleet.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from gecko_core.permissions import (
    PERMISSION_KEYS,
    PermissionKey,
    PermissionState,
    PrivyWalletStatus,
)
from gecko_core.wallets.privy import is_privy_configured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/permissions", tags=["permissions"])


# ---------------------------------------------------------------------------
# Response models — mirror lib/schemas.ts shape exactly
# ---------------------------------------------------------------------------


AgentLane = Literal["drafts", "paper", "real", "deployed"]


class AgentPermissionsRead(BaseModel):
    """Mirrors `AgentPermissionsSchema` in gecko-mcpay-app/lib/schemas.ts."""

    agent_id: str = Field(serialization_alias="agentId")
    agent_name: str = Field(serialization_alias="agentName")
    lane: AgentLane
    privy_wallet_status: PrivyWalletStatus = Field(
        serialization_alias="privyWalletStatus"
    )
    permissions: dict[PermissionKey, PermissionState]

    model_config = {"populate_by_name": True}


class PermissionsResponse(BaseModel):
    """Mirrors `PermissionsResponseSchema` in lib/schemas.ts."""

    agents: list[AgentPermissionsRead]


# ---------------------------------------------------------------------------
# Lane → default permission grid
#
# These are SERVER-AUTHORITATIVE defaults. The Permissions Center UI can
# toggle individual cells (optimistic) but the actual on-chain enforcement
# happens via the Privy policy attached to the agent's server-wallet
# (S26-B). Until the per-agent override store ships, these defaults are
# the only state the endpoint surfaces.
#
# Discipline notes (per the Permissions Center copy in permissions-view.tsx):
#  - "drafts" lane never gets on-chain permissions, period
#  - "paper" lane gets read + simulate, never move_funds or withdraw_vault
#  - "real" lane gets the full grid IFF wallet is active
#  - "deployed" lane = killed agents, all denied
# ---------------------------------------------------------------------------


_LANE_DEFAULTS: dict[AgentLane, dict[PermissionKey, PermissionState]] = {
    "drafts": {
        "read_market": "granted",
        "place_trades": "denied",
        "move_funds": "denied",
        "sign_contracts": "denied",
        "withdraw_vault": "denied",
        "access_oracle": "granted",
    },
    "paper": {
        "read_market": "granted",
        "place_trades": "granted",
        "move_funds": "denied",
        "sign_contracts": "denied",
        "withdraw_vault": "denied",
        "access_oracle": "granted",
    },
    "real": {
        "read_market": "granted",
        "place_trades": "granted",
        "move_funds": "granted",
        "sign_contracts": "granted",
        "withdraw_vault": "granted",
        "access_oracle": "granted",
    },
    "deployed": {
        "read_market": "denied",
        "place_trades": "denied",
        "move_funds": "denied",
        "sign_contracts": "denied",
        "withdraw_vault": "denied",
        "access_oracle": "denied",
    },
}

#: On-chain permissions — these require an ACTIVE Privy wallet regardless
#: of lane defaults. If `privy_wallet_status != "active"`, these flip to
#: `pending` (waiting on wallet bootstrap).
_ON_CHAIN_KEYS: frozenset[PermissionKey] = frozenset(
    {"place_trades", "move_funds", "sign_contracts", "withdraw_vault"}
)


def _apply_wallet_gate(
    permissions: dict[PermissionKey, PermissionState],
    wallet_status: PrivyWalletStatus,
) -> dict[PermissionKey, PermissionState]:
    """Downgrade on-chain keys to `pending` when wallet isn't active."""
    if wallet_status == "active":
        return permissions
    out = dict(permissions)
    for key in _ON_CHAIN_KEYS:
        if out.get(key) == "granted":
            out[key] = "pending"
    return out


# ---------------------------------------------------------------------------
# Mock fixture — mirrors the app's INITIAL_PERMISSIONS shape so frontend
# can ship the wire before Privy is live in production.
# ---------------------------------------------------------------------------


def _mock_agents(default_wallet_status: PrivyWalletStatus) -> list[AgentPermissionsRead]:
    """Three mock agents covering the four lanes the UI knows about."""
    rows: list[tuple[str, str, AgentLane]] = [
        ("agent-jto-breakout", "JTO breakout (Setup C)", "paper"),
        ("agent-kamino-yield", "Kamino USDC yield sink", "drafts"),
        ("agent-okx-copy", "OKX copy-grader subscriber", "deployed"),
    ]
    out: list[AgentPermissionsRead] = []
    for agent_id, agent_name, lane in rows:
        # Drafts get "not_set" by default (no wallet attached yet).
        # Deployed get "revoked" (wallet was active, now killed).
        wstatus: PrivyWalletStatus
        if lane == "drafts":
            wstatus = "not_set"
        elif lane == "deployed":
            wstatus = "revoked"
        else:
            wstatus = default_wallet_status
        gated = _apply_wallet_gate(_LANE_DEFAULTS[lane], wstatus)
        out.append(
            AgentPermissionsRead(
                agent_id=agent_id,
                agent_name=agent_name,
                lane=lane,
                privy_wallet_status=wstatus,
                permissions=gated,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=PermissionsResponse, response_model_by_alias=True)
async def get_permissions(
    include_wallets: bool = Query(
        default=False,
        description=(
            "When true AND Privy is configured, look up the real wallet "
            "status from the sessions store. When false, return the mock "
            "fixture (paper-lane = pending_sprint_26 until the persistent "
            "per-agent override store ships)."
        ),
    ),
) -> PermissionsResponse:
    """Return the Permissions Center grid.

    Today's response is derived from per-lane defaults — see _LANE_DEFAULTS.
    Once the agent-permissions collection lands (Sprint 27+), this will
    merge user overrides on top.
    """
    privy_live = is_privy_configured() and include_wallets
    default_wallet = (
        "active" if privy_live else ("not_set" if include_wallets else "pending_sprint_26")
    )
    agents = _mock_agents(default_wallet)  # type: ignore[arg-type]
    return PermissionsResponse(agents=agents)


@router.get("/keys")
async def list_permission_keys() -> dict[str, list[str]]:
    """Echo the canonical PERMISSION_KEYS tuple.

    Useful for the frontend's column-order discovery — single source of
    truth lives in `gecko_core.permissions`, the app reads it from here
    so it never drifts.
    """
    return {"keys": list(PERMISSION_KEYS)}
