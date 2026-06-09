"""Privy v2 server-side embedded-wallet client (S2-05).

We use Privy's REST API directly via httpx — no SDK, on purpose:
    * one fewer supply-chain dependency to vet,
    * the SDK is a thin wrapper around three endpoints we use, and
    * direct httpx makes mocking with `respx` trivial in tests.

Auth scheme (per https://docs.privy.io/wallets/wallets/create as of
April 2026):
    HTTP Basic auth using `<PRIVY_APP_ID>:<PRIVY_APP_SECRET>` PLUS a
    `privy-app-id: <PRIVY_APP_ID>` header. Both are required — Basic auth
    alone returns 401, and the header alone returns 403. We send both on
    every call.

Wallet ownership: app-owned (server-controlled) wallets, identified to our
side by `external_id = <project uuid>`. We deliberately DO NOT pass an
`owner.user_id` because that would require minting a Privy user DID for
each project — unnecessary complexity for a server-controlled wallet.

Sentinel detection: `__unset__`, `__dev_change_me__`, and empty string are
all treated as truly unconfigured. `is_privy_configured()` is the gate the
api layer uses before instantiating a client.
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinels — kept local rather than importing from `payments.cdp` to avoid a
# cross-module dependency between two unrelated subsystems. Tiny duplication
# is fine; the canonical list is small and rarely changes.
# ---------------------------------------------------------------------------
_SENTINELS: Final[frozenset[str]] = frozenset({"", "__unset__", "__dev_change_me__"})


def _is_sentinel(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip() in _SENTINELS


def is_privy_configured(
    *,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> bool:
    """True iff both PRIVY_APP_ID and PRIVY_APP_SECRET are set + non-sentinel.

    Reads from the process environment when arguments are omitted so callers
    that don't have a Settings object handy can still gate cleanly.
    """
    aid = app_id if app_id is not None else os.environ.get("PRIVY_APP_ID")
    sec = app_secret if app_secret is not None else os.environ.get("PRIVY_APP_SECRET")
    return not (_is_sentinel(aid) or _is_sentinel(sec))


# ---------------------------------------------------------------------------
# Models + errors
# ---------------------------------------------------------------------------


class PrivyWallet(BaseModel):
    """Read model for a Privy v2 wallet response.

    Mirrors the API's response shape but only surfaces the fields gecko-core
    cares about. `chain_type` is always `'solana'` in this codebase — we
    refuse to construct a wallet for any other chain (S2-05 is Solana only).
    """

    wallet_id: str
    address: str
    chain_type: str = "solana"
    created_at: datetime | None = None

    model_config = {"frozen": True}


class PrivyPolicy(BaseModel):
    """Read model for a Privy v2 policy response (S26-B).

    Policies scope what an attached wallet can do — per-method allowlist,
    per-recipient allowlist, per-token cap. Attaching a policy to a wallet
    means the wallet's signing path enforces the rules *before* signing.

    The policy spec itself is opaque to gecko-core: we accept whatever
    rule-array shape Privy currently documents and pass it through. Callers
    that need typed builders can compose on top.
    """

    policy_id: str
    name: str | None = None
    chain_type: str = "solana"
    created_at: datetime | None = None

    model_config = {"frozen": True}


class PrivyClientError(RuntimeError):
    """Privy returned a non-2xx response. Body is preserved verbatim."""


class PrivyNotConfiguredError(RuntimeError):
    """PRIVY_APP_ID / PRIVY_APP_SECRET missing or sentinel — refuse to call."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


_PRIVY_BASE_URL: Final[str] = "https://api.privy.io"
_DEFAULT_TIMEOUT_S: Final[float] = 10.0


class PrivyClient:
    """Server-side Privy v2 client for embedded-wallet operations.

    Lazy-instantiated. Callers should `is_privy_configured()`-gate before
    construction; the constructor itself enforces non-sentinel creds and
    raises `PrivyNotConfiguredError` rather than calling Privy with garbage.

    Balance lookups deliberately do NOT call Privy — Privy doesn't surface
    SPL token balances cleanly per-token. We delegate to the Solana RPC the
    rest of the x402 stack already uses.
    """

    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        base_url: str = _PRIVY_BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        aid = app_id if app_id is not None else os.environ.get("PRIVY_APP_ID")
        sec = app_secret if app_secret is not None else os.environ.get("PRIVY_APP_SECRET")
        if _is_sentinel(aid) or _is_sentinel(sec):
            raise PrivyNotConfiguredError(
                "PRIVY_APP_ID and PRIVY_APP_SECRET must both be set (sentinel "
                "or empty value detected). Set them in .env / SSM before "
                "instantiating PrivyClient."
            )
        # Mypy: post-sentinel-check, both are non-None non-empty strings.
        assert aid is not None and sec is not None
        self._app_id: str = aid.strip()
        self._app_secret: str = sec.strip()
        self._base_url: str = base_url.rstrip("/")
        self._owns_client: bool = client is None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=timeout_s,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> PrivyClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- HTTP plumbing ---------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """Basic auth + privy-app-id header.

        We construct the Basic header by hand rather than relying on
        httpx's `auth=` so that mocks see the literal Authorization header
        value (some respx versions don't surface httpx-injected auth).
        """
        token = base64.b64encode(f"{self._app_id}:{self._app_secret}".encode()).decode("ascii")
        return {
            "Authorization": f"Basic {token}",
            "privy-app-id": self._app_id,
            "Content-Type": "application/json",
        }

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        resp = await self._client.post(url, json=body, headers=self._auth_headers())
        return self._handle(resp)

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        resp = await self._client.get(url, headers=self._auth_headers())
        return self._handle(resp)

    async def _patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        resp = await self._client.patch(url, json=body, headers=self._auth_headers())
        return self._handle(resp)

    @staticmethod
    def _handle(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            # Surface the body verbatim — Privy errors include actionable
            # messages like "external_id already exists" that callers above
            # need to see, not a sanitized "5xx".
            raise PrivyClientError(
                f"Privy {resp.request.method} {resp.request.url.path} "
                f"-> {resp.status_code}: {resp.text}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise PrivyClientError(
                f"Privy {resp.request.method} {resp.request.url.path} "
                f"returned non-JSON: {resp.text[:200]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise PrivyClientError(
                f"Privy {resp.request.method} {resp.request.url.path} "
                f"returned non-object JSON: {type(data).__name__}"
            )
        return data

    # -- Public API ------------------------------------------------------

    async def create_solana_wallet(
        self,
        *,
        owner_label: str,
    ) -> PrivyWallet:
        """Create an app-owned Solana wallet.

        `owner_label` is mapped to `external_id` (max 64 chars per Privy).
        We pass the project UUID as-is — 36 chars, well under the cap.
        """
        body: dict[str, Any] = {
            "chain_type": "solana",
            "external_id": owner_label,
        }
        data = await self._post("/v1/wallets", body)
        return _parse_wallet(data)

    async def get_wallet(self, wallet_id: str) -> PrivyWallet:
        """Fetch an existing wallet by Privy id."""
        data = await self._get(f"/v1/wallets/{wallet_id}")
        return _parse_wallet(data)

    # -- Policies (S26-B) -----------------------------------------------
    #
    # Privy v2 policies scope what an attached wallet can do. The wire
    # shape is `POST /v1/policies` with a `rules: [...]` array; attach via
    # `PATCH /v1/wallets/{wallet_id}` with `policy_ids: [policy_id]`.
    #
    # gecko-core's wedge is "scoped permissions for trading agents" — a
    # policy is the on-chain enforcement of the Permissions Center UI's
    # granted/denied per-key grid. The mapping (PermissionKey → rules)
    # lives in the caller, not here, so this client stays generic.

    async def create_policy(
        self,
        *,
        name: str,
        rules: list[dict[str, Any]],
        chain_type: str = "solana",
    ) -> PrivyPolicy:
        """Create a scoped policy.

        `rules` is passed through to Privy verbatim — gecko-core does not
        validate rule structure, because Privy occasionally adds new rule
        kinds and we'd rather not bottleneck on a wrapper update. The caller
        composes the rule shape from the PermissionKey grid.

        Returns a frozen PrivyPolicy with the new policy_id.
        """
        if chain_type != "solana":
            raise PrivyClientError(
                f"create_policy: chain_type={chain_type!r} unsupported "
                "(gecko-core is Solana-only per S2-05)."
            )
        body: dict[str, Any] = {
            "name": name,
            "chain_type": chain_type,
            "rules": rules,
        }
        data = await self._post("/v1/policies", body)
        return _parse_policy(data)

    async def attach_policy_to_wallet(
        self,
        *,
        wallet_id: str,
        policy_ids: list[str],
    ) -> PrivyWallet:
        """Attach one or more policies to an existing wallet.

        Privy's wallet-PATCH endpoint accepts the full desired policy set,
        not a delta — so callers must pass the *complete* policy list they
        want enforced. Empty list = remove all policies (rarely what you
        want; refuse it here to avoid a footgun).
        """
        if not policy_ids:
            raise PrivyClientError(
                "attach_policy_to_wallet: refusing empty policy_ids list. "
                "Pass the full desired set; use detach_all_policies() if you "
                "really mean to remove all policy enforcement."
            )
        body: dict[str, Any] = {"policy_ids": policy_ids}
        data = await self._patch(f"/v1/wallets/{wallet_id}", body)
        return _parse_wallet(data)

    async def update_policy_rules(
        self,
        *,
        policy_id: str,
        rules: list[dict[str, Any]],
    ) -> PrivyPolicy:
        """Replace a policy's rule set in place (``PATCH /v1/policies/{id}``).

        Privy's policy-PATCH accepts the FULL desired ``rules`` array, not a
        delta — the returned policy enforces exactly what is passed. The
        policy_id is preserved, so the wallet stays attached and no detach is
        needed.

        This is the lever ``PrivyWalletAdapter.revoke`` uses: rewriting the
        granted policy's rules to a single deny-all rule removes ALL signing
        authority while keeping the policy attached. We deliberately do NOT
        detach the policy from the wallet to revoke, because a wallet with no
        policy attached is NOT guaranteed by Privy's docs to be deny-by-default
        — detaching could *widen* authority to permissionless signing. Keeping
        the policy attached and flipping its rules to deny-all is fail-closed.
        """
        data = await self._patch(f"/v1/policies/{policy_id}", {"rules": rules})
        return _parse_policy(data)

    async def get_wallet_balance(self, wallet_id: str) -> Decimal:
        """USDC balance for a wallet's Solana address.

        NOTE: this does NOT call Privy — Privy doesn't surface SPL token
        balances cleanly per-token. The intended implementation is to read
        from the Solana RPC the rest of x402 already uses; until that wiring
        lands (separate ticket), the method intentionally raises so callers
        know to fall back to the on-chain balance check rather than silently
        getting a stale 0.
        """
        raise NotImplementedError(
            "PrivyClient.get_wallet_balance: read SPL USDC balance via the "
            "Solana RPC, not Privy. Wire to gecko_core.payments.networks once "
            "balance gating lands."
        )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_wallet(data: dict[str, Any]) -> PrivyWallet:
    wallet_id = data.get("id")
    address = data.get("address")
    if not isinstance(wallet_id, str) or not isinstance(address, str):
        raise PrivyClientError(f"Privy response missing id/address: keys={sorted(data.keys())}")
    chain_type = data.get("chain_type") or "solana"
    if chain_type != "solana":
        # Defensive: the API echoes whatever chain we asked for, but if a
        # non-solana wallet ever leaks through we'd rather fail loud than
        # write a bogus address into projects.privy_wallet_address.
        raise PrivyClientError(f"Privy returned chain_type={chain_type!r}, expected 'solana'")
    created_raw = data.get("created_at")
    created_at: datetime | None = None
    if isinstance(created_raw, str):
        try:
            created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except ValueError:
            created_at = None
    elif isinstance(created_raw, (int, float)):
        # Privy occasionally returns ms epoch — handle both.
        ts = float(created_raw)
        if ts > 1e12:  # ms
            ts /= 1000.0
        try:
            created_at = datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            created_at = None
    return PrivyWallet(
        wallet_id=wallet_id,
        address=address,
        chain_type="solana",
        created_at=created_at,
    )


def _parse_policy(data: dict[str, Any]) -> PrivyPolicy:
    """Parse a Privy v2 policy response into a frozen PrivyPolicy.

    Same lenient created_at handling as _parse_wallet — Privy returns
    either ISO-8601 strings or epoch (s or ms). Anything unrecognized
    becomes None rather than raising, since the policy is still usable
    without a precise creation timestamp.
    """
    policy_id = data.get("id")
    if not isinstance(policy_id, str):
        raise PrivyClientError(f"Privy policy response missing id: keys={sorted(data.keys())}")
    name_raw = data.get("name")
    name = name_raw if isinstance(name_raw, str) else None
    chain_type = data.get("chain_type") or "solana"
    if chain_type != "solana":
        raise PrivyClientError(
            f"Privy returned policy chain_type={chain_type!r}, expected 'solana'"
        )
    created_raw = data.get("created_at")
    created_at: datetime | None = None
    if isinstance(created_raw, str):
        try:
            created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except ValueError:
            created_at = None
    elif isinstance(created_raw, (int, float)):
        ts = float(created_raw)
        if ts > 1e12:
            ts /= 1000.0
        try:
            created_at = datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            created_at = None
    return PrivyPolicy(
        policy_id=policy_id,
        name=name,
        chain_type="solana",
        created_at=created_at,
    )


__all__ = [
    "PrivyClient",
    "PrivyClientError",
    "PrivyNotConfiguredError",
    "PrivyPolicy",
    "PrivyWallet",
    "is_privy_configured",
]
