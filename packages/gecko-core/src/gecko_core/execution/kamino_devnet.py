"""Kamino devnet adapter — Python port of gecko-social-fi-creators-api/src/services/kamino.service.ts.

Two surfaces:
    - simulate: returns an intent dict, never signs, never hits network.
    - devnet:  fetches an unsigned base64 versioned tx from KTX REST.
               Sign + submit lives client-side (in the example skill) so
               this module never holds private keys.

Mainnet is intentionally not supported here — the example skill must not
custody mainnet funds. Mainnet deposits stay with the user's chosen UI
(Kamino webapp, lana.ai, etc).

Reference: kamino.service.ts:46-220 (KAMINO_MODE, ktxPost, signAndSend).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import httpx

KaminoMode = Literal["simulate", "devnet"]


@dataclass(frozen=True)
class KaminoIntent:
    mode: KaminoMode
    wallet: str
    market: str
    reserve: str
    amount_usdc: Decimal
    signed_tx_b64: str | None = None
    signature: str | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "venue": "kamino",
            "action": "deposit",
            "wallet": self.wallet,
            "market": self.market,
            "reserve": self.reserve,
            "amount_usdc": str(self.amount_usdc),
        }


def build_simulate_intent(
    *,
    wallet: str,
    market: str,
    reserve: str,
    amount_usdc: Decimal,
) -> KaminoIntent:
    return KaminoIntent(
        mode="simulate",
        wallet=wallet,
        market=market,
        reserve=reserve,
        amount_usdc=amount_usdc,
    )


async def fetch_unsigned_deposit_tx(
    *,
    ktx_url: str,
    wallet: str,
    market: str,
    reserve: str,
    amount_usdc: Decimal,
) -> str:
    """Call KTX /ktx/klend/deposit and return the base64 unsigned transaction.

    Mirrors `ktxPost` from kamino.service.ts:124-141.
    """
    payload = {
        "wallet": wallet,
        "market": market,
        "reserve": reserve,
        "amount": str(amount_usdc),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{ktx_url}/ktx/klend/deposit", json=payload)
        resp.raise_for_status()
        body = resp.json()
    tx = body.get("transaction")
    if not isinstance(tx, str):
        raise RuntimeError(f"KTX deposit returned no transaction: {body!r}")
    return tx
