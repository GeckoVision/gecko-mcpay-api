"""Founder-approved tape universe + timeframes (s46).

Symbols: traded names (PYTH, WIF, JTO, POPCAT, BOME) + regime/market context
(SOL, BTC). Mint addresses are for Birdeye on-chain fallback (memes not listed on
OKX spot). OKX listing was probed live 2026-05-23: PYTH/WIF/JTO/BOME/SOL/BTC are
-USDT listed; POPCAT-USDT returns OKX code 51001 (not listed) -> Birdeye-only.
"""

from __future__ import annotations

TIMEFRAMES: list[str] = ["5m", "15m", "1H", "4H"]

# (symbol, solana_mint, role). mint used only for the Birdeye fallback.
UNIVERSE: list[tuple[str, str, str]] = [
    ("PYTH", "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", "traded"),
    ("WIF", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "traded"),
    ("JTO", "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL", "traded"),
    ("POPCAT", "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "traded"),
    ("BOME", "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82", "traded"),
    ("SOL", "So11111111111111111111111111111111111111112", "context"),
    # BTC has no Solana mint; OKX-only (regime/market context).
    ("BTC", "", "context"),
]

SYMBOLS: list[str] = [s for s, _, _ in UNIVERSE]
MINTS: dict[str, str] = {s: m for s, m, _ in UNIVERSE}

# Lookback target. ~6mo minimum; OKX history-candles reaches ~6mo+ for these.
DEFAULT_LOOKBACK_DAYS = 270  # ~9mo target; collector stops early if data ends
DAY_MS = 86_400_000
DAY_S = 86_400
