"""Symbol → Solana mint map for the trading universe.

Mirror of contest_bot/jto_breakout_gecko_gated_contest_bot.py INSTRUMENTS (the
current PYTH/WIF/JUP/RAY/JTO universe) plus BOME (recent + H1-verified). Kept as a
standalone module so calibration/enrichment scripts resolve mints WITHOUT importing
the side-effectful bot script (which starts a dashboard server at import).

Single source of truth note: if the bot's INSTRUMENTS changes, update this map (or
extract INSTRUMENTS into a shared module both import — deferred to avoid restarting
the running paper stress test). All mints verified on-chain (H1 by-address probe +
the bot's `onchainos token info` checks).
"""

from __future__ import annotations

SYMBOL_TO_MINT: dict[str, str] = {
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "JTO": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
    "BOME": "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82",
}


def mint_for(symbol: str) -> str | None:
    return SYMBOL_TO_MINT.get(symbol)
