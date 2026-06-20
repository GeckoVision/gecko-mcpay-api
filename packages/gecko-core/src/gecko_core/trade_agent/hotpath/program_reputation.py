"""Program reputation (Jito-map I2) — bundle→originating-program attribution.

When the firewall sees a bundle/snipe, *which* program originated the swap is a
sharp tell: a swap through a known AMM (Raydium / Orca / Pump.fun / Meteora) is
ordinary; a swap through a **first-seen / unknown custom program** alongside a
Jito bundle + a fresh wallet is a very-high-confidence snipe (bespoke sniper
programs are spun up per campaign).

Pure + offline: a curated allowlist of established Solana DEX/launchpad program
ids + a classifier. The runner extracts ``programIdIndex`` from the parsed-tx
(deferred ingest); this module is the judgment. Stdlib only.
"""

from __future__ import annotations

from typing import Literal

ProgramReputation = Literal["established", "unknown"]

# Established Solana DEX / launchpad program ids (mainnet). A swap routed through
# one of these is ordinary infrastructure — not itself a snipe signal. Curated;
# extend as new majors appear (Pattern A: one canonical place).
ESTABLISHED_PROGRAMS: frozenset[str] = frozenset(
    {
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM v4
        "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # Raydium CPMM
        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # Raydium CLMM
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Orca Whirlpools
        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  # Meteora DLMM
        "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB",  # Meteora pools
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # Pump.fun bonding curve
        "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",  # PumpSwap AMM
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter v6 aggregator
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # SPL Token program
        "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM",  # Token-2022
        "11111111111111111111111111111111",  # System program
    }
)


def classify_program(program_id: str) -> ProgramReputation:
    """``established`` if the program is a known major; ``unknown`` otherwise.

    An ``unknown`` program is not itself proof of harm — but an unknown program
    in a Jito bundle with a fresh-wallet buyer is a very-high-confidence snipe.
    """
    return "established" if program_id in ESTABLISHED_PROGRAMS else "unknown"


def has_unknown_program(program_ids: list[str]) -> bool:
    """True if any program in the set is not a known major (a custom-program tell)."""
    return any(classify_program(p) == "unknown" for p in program_ids)


__all__ = [
    "ESTABLISHED_PROGRAMS",
    "ProgramReputation",
    "classify_program",
    "has_unknown_program",
]
