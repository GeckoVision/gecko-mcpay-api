"""S41 yield-base — recorded-fixture contract test (Pattern C).

Locks the onchainOS Kamino USDC-lend `defi deposit` wire shape against a
committed, redacted fixture so a future CLI change can't silently break the
yield-base sleeve. The DEFAULT run is OFFLINE replay of the committed fixture
through the gecko-core validator — no network, no auth, no signing, CI-safe.

Pattern C (CLAUDE.md): "tests that exercise stubs, not real wires" is the
failure mode. Sprint 12 CDP `/settle` broke because only the stub path was
tested. Here we replay the REAL onchainOS response bytes and decode them as a
genuine Solana ``VersionedTransaction``; nothing is stubbed.

Re-recording the fixture (a once-off live `defi deposit` calldata fetch — still
read-only, still never broadcast) is gated behind the ``live_kamino`` marker so
it never runs in the default sweep. The redeem-calldata fixture is tracked as a
skipped placeholder: it cannot be recorded until a real on-chain position
exists, which only happens at Step 3 (founder-authorized live deposit).

Reference: ``docs/strategy/2026-05-22-yield-base-build-plan.md`` §4 Step 2.

    # default offline replay (runs in CI):
    uv run pytest packages/gecko-core/tests/execution/test_yield_base_kamino_contract.py

    # once-off live re-record (operator opt-in, never broadcasts):
    GECKO_YIELD_KAMINO_LIVE=1 \
    uv run pytest packages/gecko-core/tests/execution/test_yield_base_kamino_contract.py \
        -m live_kamino
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from gecko_core.execution.yield_base import (
    KLEND_PROGRAM_ID,
    USDC_PRECISION,
    CalldataSummary,
    SimFailure,
    assert_deposit_calldata,
    expected_minimal_units,
)

FIXTURES = Path(__file__).parent / "fixtures" / "yield_base"
DEPOSIT_FIXTURE = FIXTURES / "deposit_29130_25usdc.json"
REDEEM_FAIL_FIXTURE = FIXTURES / "redeem_29130_ratio1_FAIL.json"

# The wallet that built the recorded deposit (public Solana address, not a
# secret). The validator asserts account[0] of the decoded tx == this `from`.
EXPECTED_PAYER = "3HrXPry37q5bcaa5C3m543bHLShpMxu7LF4KbRjBJN4i"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


# --- offline replay (the contract test proper — runs in CI) ---------------


def test_deposit_fixture_replays_to_valid_calldata() -> None:
    """The committed onchainOS deposit response decodes to a structurally
    valid, UNSIGNED Kamino klend deposit tx."""
    summary = assert_deposit_calldata(_load(DEPOSIT_FIXTURE))
    assert isinstance(summary, CalldataSummary)
    assert summary.to == KLEND_PROGRAM_ID
    assert summary.unsigned is True
    assert summary.klend_instruction_count >= 1
    assert KLEND_PROGRAM_ID in summary.programs
    assert summary.num_instructions >= summary.klend_instruction_count
    assert summary.decoded_bytes > 64


def test_deposit_fixture_fee_payer_matches() -> None:
    """Fee-payer (account[0]) round-trips to the response `from` field."""
    summary = assert_deposit_calldata(_load(DEPOSIT_FIXTURE), expect_payer=EXPECTED_PAYER)
    assert summary.payer == EXPECTED_PAYER


def test_deposit_calldata_is_unsigned() -> None:
    """SAFETY GATE: the recorded calldata carries no signature. A signed tx
    here would mean something tried to sign — that must FAIL."""
    summary = assert_deposit_calldata(_load(DEPOSIT_FIXTURE))
    assert summary.unsigned is True


def test_deposit_fixture_targets_kamino_klend() -> None:
    """Step-1 finding locked in: 5 klend instructions, klend is the target."""
    summary = assert_deposit_calldata(_load(DEPOSIT_FIXTURE))
    assert summary.programs.count(KLEND_PROGRAM_ID) == 1
    assert summary.klend_instruction_count == 5


def test_precision_25_usdc_to_minimal_units() -> None:
    """$25 → 25_000_000 minimal units (10^6), exact, no float."""
    assert expected_minimal_units("25", USDC_PRECISION) == 25_000_000
    assert expected_minimal_units("100", USDC_PRECISION) == 100_000_000
    assert expected_minimal_units("0.000001", USDC_PRECISION) == 1


def test_precision_rejects_dust() -> None:
    """Sub-minimal-unit amounts are rejected (no silent truncation)."""
    with pytest.raises(SimFailure):
        expected_minimal_units("0.0000001", USDC_PRECISION)  # 7th decimal = dust


def test_redeem_no_position_is_clean_error_not_garbage() -> None:
    """The redeem-without-position fixture is a CLEAN error, not malformed
    calldata. assert_deposit_calldata must reject it loudly (ok=False),
    proving the integration did not silently build a garbage exit tx."""
    payload = _load(REDEEM_FAIL_FIXTURE)
    assert payload["ok"] is False
    assert "84027" in payload["error"]
    with pytest.raises(SimFailure):
        assert_deposit_calldata(payload)


# --- structural-violation guards (the validator catches drift) ------------


def test_wrong_to_program_fails() -> None:
    payload = _load(DEPOSIT_FIXTURE)
    payload["data"]["dataList"][0]["to"] = "11111111111111111111111111111111"
    with pytest.raises(SimFailure):
        assert_deposit_calldata(payload)


def test_empty_datalist_fails() -> None:
    payload = _load(DEPOSIT_FIXTURE)
    payload["data"]["dataList"] = []
    with pytest.raises(SimFailure):
        assert_deposit_calldata(payload)


def test_mismatched_payer_fails() -> None:
    with pytest.raises(SimFailure):
        assert_deposit_calldata(_load(DEPOSIT_FIXTURE), expect_payer="NotOurWallet")


# --- redeem-calldata placeholder (blocked on Step 3 position) --------------


@pytest.mark.skip(reason="redeem fixture recorded post-Step-3 deposit")
def test_redeem_calldata_replays_to_valid_exit() -> None:
    """PLACEHOLDER — tracked, not forgotten.

    A real `defi redeem --ratio 1` returns valid exit calldata ONLY when the
    wallet holds a Kamino position. Step 1 confirmed it clean-errors (84027)
    with no position. Once Step 3's $5-10 live deposit confirms, record the
    redeem calldata into fixtures/yield_base/redeem_29130_ratio1.json and
    fill this in: assert it decodes, targets klend, is unsigned, payer matches.
    Until then this stays skipped so the gap is visible, not silent.
    """
    raise AssertionError("unreachable — skipped until the Step-3 redeem fixture exists")


# --- once-off live re-record (operator opt-in; never broadcasts) -----------


@pytest.mark.live_kamino
def test_record_deposit_fixture_live() -> None:
    """Re-fetch the deposit calldata from the live onchainOS CLI and assert it
    still matches the locked shape. Read-only — NEVER calls `wallet
    contract-call`, NEVER signs, NEVER broadcasts. Gated behind both the
    ``live_kamino`` marker AND ``GECKO_YIELD_KAMINO_LIVE=1`` so the default
    sweep and CI never touch the network."""
    if os.environ.get("GECKO_YIELD_KAMINO_LIVE") != "1":
        pytest.skip("set GECKO_YIELD_KAMINO_LIVE=1 to re-record against the live CLI")

    # Imported lazily: the script owns the CLI fetch (subprocess), kept out of
    # the offline import path so the default test never imports a CLI shell-out.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts" / "yield"))
    from sim_kamino_deposit import fetch_live_deposit, get_wallet_address  # type: ignore

    addr = get_wallet_address()
    payload = fetch_live_deposit(addr, "25")
    summary = assert_deposit_calldata(payload, expect_payer=addr)
    assert summary.to == KLEND_PROGRAM_ID
    assert summary.unsigned is True
