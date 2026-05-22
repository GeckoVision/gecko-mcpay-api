"""Yield-base sleeve — Kamino USDC-lend calldata validation (gecko-core).

This package owns the *structural validation* of the unsigned deposit/withdraw
calldata that onchainOS's `defi` verbs return for the Kamino USDC-lend reserve.
It is pure, typed, and network-free: it decodes a Solana ``MessageV0`` /
``VersionedTransaction`` and asserts the wire shape we lock in for the sleeve.

It deliberately holds NO signing, NO broadcast, NO RPC, NO private keys. The
script ``scripts/yield/sim_kamino_deposit.py`` (the $0 falsifier) and the
contract test ``test_yield_base_kamino_contract.py`` are thin callers of the
helpers exposed here — per the "business logic lives in gecko-core" rule.

Build plan: ``docs/strategy/2026-05-22-yield-base-build-plan.md`` §4 Step 2.
"""

from __future__ import annotations

from gecko_core.execution.yield_base.validation import (
    EMPTY_SIG,
    KAMINO_USDC_INVESTMENT_ID,
    KLEND_PROGRAM_ID,
    SOLANA_CHAIN_INDEX,
    USDC_MINT,
    USDC_PRECISION,
    CalldataSummary,
    SimFailure,
    assert_deposit_calldata,
    b58decode,
    expected_minimal_units,
)

__all__ = [
    "EMPTY_SIG",
    "KAMINO_USDC_INVESTMENT_ID",
    "KLEND_PROGRAM_ID",
    "SOLANA_CHAIN_INDEX",
    "USDC_MINT",
    "USDC_PRECISION",
    "CalldataSummary",
    "SimFailure",
    "assert_deposit_calldata",
    "b58decode",
    "expected_minimal_units",
]
