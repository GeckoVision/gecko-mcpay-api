"""S10-LIVE-03 — `_resolve_network_kind` typed enum mapper.

A `solana:<MINT>` id should classify cleanly into mainnet / devnet so the
operator-facing mismatch message can say "you're on devnet, server expected
mainnet" instead of pasting two opaque base58 blobs.
"""

from __future__ import annotations

import pytest
from gecko_core.payments.x402_client import (
    SOLANA_DEVNET_USDC_MINT,
    SOLANA_MAINNET_USDC_MINT,
    NetworkKind,
    _resolve_network_kind,
)


def test_resolves_mainnet_usdc_mint() -> None:
    assert _resolve_network_kind(f"solana:{SOLANA_MAINNET_USDC_MINT}") is NetworkKind.SOLANA_MAINNET


def test_resolves_devnet_usdc_mint() -> None:
    assert _resolve_network_kind(f"solana:{SOLANA_DEVNET_USDC_MINT}") is NetworkKind.SOLANA_DEVNET


@pytest.mark.parametrize(
    "value",
    [
        "",
        "solana",
        "solana:",
        ":EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "ethereum:0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "not-a-caip-id",
    ],
)
def test_malformed_or_non_solana_returns_unknown(value: str) -> None:
    assert _resolve_network_kind(value) is NetworkKind.UNKNOWN


def test_unknown_solana_mint_returns_unknown() -> None:
    # A plausible-looking but un-mapped Solana mint (e.g. a random SPL token)
    # must classify as UNKNOWN — we never silently treat strangers as
    # mainnet.
    assert (
        _resolve_network_kind("solana:So11111111111111111111111111111111111111112")
        is NetworkKind.UNKNOWN
    )
