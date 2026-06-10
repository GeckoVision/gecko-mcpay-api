"""QuickNode (Solana JSON-RPC) raw-chain client.

Wire reference: Solana JSON-RPC (https://solana.com/docs/rpc). QuickNode is just
the endpoint URL (``QUICKNODE_RPC_URL``); the request/response shapes are the
Solana RPC spec, so this client works against any Solana RPC provider.

For the safety layer, raw chain access = **rug / honeypot checks** that no
price feed can give you:

  - **mint authority** present  → the dev can mint unlimited supply.
  - **freeze authority** present → the dev can freeze your tokens in place.
  - **holder concentration**    → a few wallets hold most of the supply.

A token whose mint/freeze authority is *not* renounced is an elevated rug risk;
a renounced token (both ``None``) is materially safer. The gate reads this
before ever sizing a position.

Structured market/chain source — httpx + pydantic only; not a RAG/corpus source.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class MintInfo(BaseModel):
    """Parsed SPL mint account (from ``getAccountInfo`` jsonParsed)."""

    model_config = ConfigDict(extra="ignore")

    mint: str
    mint_authority: str | None = None
    freeze_authority: str | None = None
    decimals: int | None = None
    supply: str | None = None
    is_initialized: bool = True


@dataclass(frozen=True)
class TokenSafety:
    """Rug/honeypot read for an SPL mint.

    ``rug_risk`` is the gate signal: True when either authority is *not*
    renounced (the dev retains mint or freeze power).
    """

    mint: str
    mint_renounced: bool
    freeze_renounced: bool
    decimals: int | None
    supply: str | None
    rug_risk: bool


def _safety_from_mint(info: MintInfo) -> TokenSafety:
    mint_renounced = info.mint_authority is None
    freeze_renounced = info.freeze_authority is None
    return TokenSafety(
        mint=info.mint,
        mint_renounced=mint_renounced,
        freeze_renounced=freeze_renounced,
        decimals=info.decimals,
        supply=info.supply,
        rug_risk=not (mint_renounced and freeze_renounced),
    )


class QuickNodeClient:
    """Async Solana JSON-RPC client (configured to a QuickNode endpoint)."""

    def __init__(
        self,
        rpc_url: str,
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._rpc_url = rpc_url
        self._timeout = timeout
        self._client = client

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        if self._client is not None:
            resp = await self._client.post(self._rpc_url, json=body, timeout=self._timeout)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._rpc_url, json=body)
        resp.raise_for_status()
        payload = resp.json()
        if "error" in payload:
            raise RuntimeError(f"Solana RPC error for {method}: {payload['error']}")
        return payload.get("result")

    async def get_mint_info(self, mint: str) -> MintInfo:
        result = await self._rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        info = (
            (((result or {}).get("value") or {}).get("data") or {})
            .get("parsed", {})
            .get("info", {})
        )
        return MintInfo(
            mint=mint,
            mint_authority=info.get("mintAuthority"),
            freeze_authority=info.get("freezeAuthority"),
            decimals=info.get("decimals"),
            supply=info.get("supply"),
            is_initialized=bool(info.get("isInitialized", True)),
        )

    async def token_largest_accounts(self, mint: str) -> list[dict[str, Any]]:
        result = await self._rpc("getTokenLargestAccounts", [mint])
        return list((result or {}).get("value") or [])

    async def token_safety(self, mint: str) -> TokenSafety:
        """The rug/honeypot read for a mint — mint/freeze renounced?"""
        return _safety_from_mint(await self.get_mint_info(mint))


__all__ = [
    "MintInfo",
    "QuickNodeClient",
    "TokenSafety",
]
