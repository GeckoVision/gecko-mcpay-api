"""Jupiter Aggregator price client — Sprint 29 Phase 1.

Jupiter Price API V2: free public REST, no auth required.
  GET https://price.jup.ag/v2/price?ids=<mint1>,<mint2>,...

Response shape (June 2026):
  {
    "data": {
      "<mint>": {
        "id": "<mint>",
        "type": "derivedPrice",
        "price": "0.041234"
      }
    },
    "timeTaken": 0.012
  }

This gives EXECUTABLE price (computed from DEX aggregator routing) —
distinct from Pyth's "fair value" (multi-publisher consensus). The
delta between Pyth and Jupiter is real slippage / liquidity stress.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import httpx

logger = logging.getLogger("contest_bot.oracle.jupiter")

JUPITER_PRICE_BASE_URL: Final[str] = "https://price.jup.ag"

# Solana mainnet mints for our universe — pinned so a token-list
# restructure doesn't silently break us. These match the same mints
# the bot's INSTRUMENTS list uses.
JUPITER_MINTS: Final[dict[str, str]] = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "JTO": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
}


@dataclass(frozen=True)
class JupiterPriceSnapshot:
    """One symbol's executable price from Jupiter at a single point."""

    symbol: str
    mint: str
    price: float
    source: str = "jupiter"


class JupiterPriceRestClient:
    """Stateless REST poller. Cheap to construct; reuse for batch fetch."""

    def __init__(
        self,
        base_url: str = JUPITER_PRICE_BASE_URL,
        timeout_s: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def fetch(self, symbols: list[str]) -> dict[str, JupiterPriceSnapshot]:
        """Fetch latest prices for the given symbols. Synchronous."""
        mints = [
            (sym.upper(), JUPITER_MINTS[sym.upper()])
            for sym in symbols
            if sym.upper() in JUPITER_MINTS
        ]
        if not mints:
            return {}

        ids_param = ",".join(mint for _sym, mint in mints)
        url = f"{self._base_url}/v2/price"

        try:
            resp = httpx.get(url, params={"ids": ids_param}, timeout=self._timeout_s)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("jupiter.fetch_failed err=%s", type(exc).__name__)
            return {}

        # data["data"] is {mint: {price: str, ...}}
        data_block = data.get("data") if isinstance(data, dict) else None
        if not isinstance(data_block, dict):
            return {}

        sym_by_mint = {mint: sym for sym, mint in mints}
        out: dict[str, JupiterPriceSnapshot] = {}
        for mint, row in data_block.items():
            try:
                if not isinstance(row, dict):
                    continue
                price_raw = row.get("price")
                if price_raw is None:
                    continue
                price_float = float(price_raw)
                if price_float <= 0:
                    continue
                sym = sym_by_mint.get(mint)
                if not sym:
                    continue
                out[sym] = JupiterPriceSnapshot(
                    symbol=sym,
                    mint=mint,
                    price=price_float,
                )
            except Exception as exc:
                logger.warning("jupiter.parse_failed mint=%s err=%s",
                               mint, type(exc).__name__)
                continue
        return out


__all__ = ["JupiterPriceSnapshot", "JupiterPriceRestClient", "JUPITER_MINTS"]
