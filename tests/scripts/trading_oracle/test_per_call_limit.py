"""Tests for the buyer-side per-call hard limit logic.

Light fakes only — see feedback_lighter_tests.md. We exercise the pure
helpers (``_check_advertised_within_limit``, ``_extract_settled_amount``)
directly; no httpx, no signing, no network.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Load run.py by file path — scripts/ isn't on sys.path by default. Same
# pattern as test_service_call_specs.py.
_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "trading_oracle" / "run.py"
_spec = importlib.util.spec_from_file_location("trading_oracle_run", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
run_mod = importlib.util.module_from_spec(_spec)
sys.modules["trading_oracle_run"] = run_mod
_spec.loader.exec_module(run_mod)

_check_advertised_within_limit = run_mod._check_advertised_within_limit
_extract_settled_amount = run_mod._extract_settled_amount


def _accepts(max_atomic: int) -> list[dict[str, object]]:
    """Build an x402 accepts[] entry with the given USDC atomic max."""
    return [
        {
            "maxAmountRequired": str(max_atomic),
            "payTo": "0xseller",
            "asset": "USDC",
            "network": "base-mainnet",
        }
    ]


def test_advertised_max_within_limit_proceeds() -> None:
    # advertised $0.05, per_call_limit $0.10 -> returns 0.05, no raise.
    accepts = _accepts(50_000)  # 0.05 USDC at 6 decimals
    result = _check_advertised_within_limit(accepts, Decimal("0.10"))
    assert result == Decimal("0.05")


def test_advertised_max_over_limit_raises() -> None:
    # advertised $10, per_call_limit $0.10 -> raises with clear message.
    accepts = _accepts(10_000_000)  # $10 USDC
    with pytest.raises(RuntimeError) as excinfo:
        _check_advertised_within_limit(accepts, Decimal("0.10"))
    msg = str(excinfo.value)
    assert "advertised maxAmount" in msg
    assert "$10.0000" in msg
    assert "$0.1000" in msg
    assert "buyer per-call hard limit" in msg


def test_settled_amount_from_receipt_overrides_advertised() -> None:
    # advertised $0.05, X-Payment-Receipt header says actually $0.001 ->
    # settled=$0.001 used, not $0.05.
    headers = {"X-Payment-Receipt": "1000"}  # 0.001 USDC at 6 decimals
    settled = _extract_settled_amount(headers, fallback_usd=Decimal("0.05"))
    assert settled == Decimal("0.001")


def test_settled_amount_falls_back_when_header_absent() -> None:
    # No receipt header -> fall back to advertised max.
    settled = _extract_settled_amount({}, fallback_usd=Decimal("0.05"))
    assert settled == Decimal("0.05")
