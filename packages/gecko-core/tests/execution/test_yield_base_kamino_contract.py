"""S41 yield-base — recorded-fixture contract test (Pattern C).

Locks the onchainOS Kamino USDC-lend `defi deposit` wire shape against a
committed, redacted fixture so a future CLI change can't silently break the
yield-base sleeve. The DEFAULT run is OFFLINE replay of the committed fixture
through the gecko-core validator — no network, no auth, no signing, CI-safe.

Pattern C (CLAUDE.md): "tests that exercise stubs, not real wires" is the
failure mode. Sprint 12 CDP `/settle` broke because only the stub path was
tested. Here we replay the REAL onchainOS response bytes and decode them as a
genuine Solana ``VersionedTransaction``; nothing is stubbed.

Step-3 blocker resolution (2026-05-22): the original target investment-id
**29130** turned out to be the BORROW side of the Kamino USDC reserve
(investType=6, terminal klend instruction ``borrow_obligation_liquidity``).
Broadcasting it fails simulation with ``ObligationDepositsEmpty`` (klend code
23) because a fresh obligation has no collateral to borrow against. The correct
USDC SUPPLY product is **227050** (SINGLE_EARN, investType=1, terminal
instruction ``deposit_reserve_liquidity_and_obligation_collateral``). The
validator now enforces SUPPLY *semantics* (``require_supply=True``): it rejects
any tx that invokes a borrow instruction and requires a deposit instruction.
The 29130 borrow fixture is retained here as a NEGATIVE case the gate must catch.

Re-recording the supply fixture (a once-off live `defi deposit` calldata fetch —
still read-only, still never broadcast) is gated behind the ``live_kamino``
marker so it never runs in the default sweep. The redeem-calldata fixture is
tracked as a skipped placeholder: it cannot be recorded until a real on-chain
position exists, which only happens once a live deposit is broadcast (a separate
founder decision — at the time of writing no position has been created).

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
DEPOSIT_FIXTURE = FIXTURES / "deposit_227050_5usdc.json"  # USDC SUPPLY (correct)
BORROW_FIXTURE = FIXTURES / "deposit_29130_BORROW.json"  # borrow side (negative)
REDEEM_FAIL_FIXTURE = FIXTURES / "redeem_29130_ratio1_FAIL.json"
REDEEM_FIXTURE = FIXTURES / "redeem_29130_ratio1.json"  # exists only post-deposit

# The wallet that built the recorded deposit (public Solana address, not a
# secret). The validator asserts account[0] of the decoded tx == this `from`.
EXPECTED_PAYER = "3HrXPry37q5bcaa5C3m543bHLShpMxu7LF4KbRjBJN4i"

# klend deposit/supply instruction discriminator we expect to terminate the tx.
DEPOSIT_RESERVE_LIQ_AND_OBLIG_COLL = "81c70402de271a2e"
BORROW_OBLIGATION_LIQUIDITY = "797f12cc49f5e141"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


# --- offline replay (the contract test proper — runs in CI) ---------------


def test_deposit_fixture_replays_to_valid_calldata() -> None:
    """The committed onchainOS deposit response decodes to a structurally
    valid, UNSIGNED Kamino klend SUPPLY tx."""
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


def test_deposit_fixture_is_supply_not_borrow() -> None:
    """SEMANTIC GATE: the supply fixture invokes a Kamino deposit instruction
    and NOT a borrow instruction. This is the guard that resolves the Step-3
    blocker (29130 was the borrow side)."""
    summary = assert_deposit_calldata(_load(DEPOSIT_FIXTURE))
    assert summary.has_supply_instruction is True
    assert summary.has_borrow_instruction is False
    assert DEPOSIT_RESERVE_LIQ_AND_OBLIG_COLL in summary.klend_discriminators
    assert BORROW_OBLIGATION_LIQUIDITY not in summary.klend_discriminators


def test_borrow_fixture_is_rejected_by_supply_gate() -> None:
    """NEGATIVE case — the 29130 BORROW calldata must be rejected by the
    default (require_supply=True) gate. This is the exact tx that failed
    on-chain simulation with ObligationDepositsEmpty; the gate now catches it
    OFFLINE for $0 before any broadcast."""
    payload = _load(BORROW_FIXTURE)
    with pytest.raises(SimFailure, match="BORROW"):
        assert_deposit_calldata(payload, expect_payer=EXPECTED_PAYER)


def test_borrow_fixture_passes_when_supply_not_required() -> None:
    """With require_supply=False the borrow tx still passes the purely-
    structural checks (it IS a valid unsigned klend tx) — proving the
    rejection above is the *semantic* guard, not a structural artifact."""
    summary = assert_deposit_calldata(
        _load(BORROW_FIXTURE), expect_payer=EXPECTED_PAYER, require_supply=False
    )
    assert summary.has_borrow_instruction is True
    assert summary.has_supply_instruction is False
    assert BORROW_OBLIGATION_LIQUIDITY in summary.klend_discriminators


def test_precision_5_usdc_to_minimal_units() -> None:
    """$5 → 5_000_000 minimal units (10^6), exact, no float."""
    assert expected_minimal_units("5", USDC_PRECISION) == 5_000_000
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


# --- redeem-calldata placeholder (blocked on a live position) --------------


@pytest.mark.skipif(
    not REDEEM_FIXTURE.exists(),
    reason="redeem fixture is recorded only after a live deposit creates a position",
)
def test_redeem_calldata_replays_to_valid_exit() -> None:
    """A real `defi redeem --ratio 1` returns valid exit calldata ONLY when the
    wallet holds a Kamino position. With no position it clean-errors (84027).

    This test is auto-enabled the moment the redeem fixture file lands (recorded
    immediately after a live deposit confirms). It asserts the exit calldata
    decodes, targets klend, is unsigned, the payer matches, and invokes a
    withdraw/redeem instruction (not a deposit/borrow). Until the fixture
    exists, skipif keeps the gap VISIBLE rather than silent."""
    from gecko_core.execution.yield_base import KLEND_WITHDRAW_DISCRIMINATORS

    payload = _load(REDEEM_FIXTURE)
    # The exit tx is a valid unsigned klend tx but is NOT a supply deposit, so
    # validate it with require_supply=False and assert withdraw semantics here.
    summary = assert_deposit_calldata(payload, expect_payer=EXPECTED_PAYER, require_supply=False)
    assert summary.to == KLEND_PROGRAM_ID
    assert summary.unsigned is True
    assert summary.payer == EXPECTED_PAYER
    assert any(d in KLEND_WITHDRAW_DISCRIMINATORS for d in summary.klend_discriminators), (
        f"exit tx invokes no withdraw/redeem instruction: {summary.klend_discriminators}"
    )
    assert summary.has_borrow_instruction is False


# --- once-off live re-record (operator opt-in; never broadcasts) -----------


@pytest.mark.live_kamino
def test_record_deposit_fixture_live() -> None:
    """Re-fetch the deposit calldata from the live onchainOS CLI and assert it
    still matches the locked SUPPLY shape. Read-only — NEVER calls `wallet
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
    payload = fetch_live_deposit(addr, "5")
    summary = assert_deposit_calldata(payload, expect_payer=addr)
    assert summary.to == KLEND_PROGRAM_ID
    assert summary.unsigned is True
    assert summary.has_supply_instruction is True
    assert summary.has_borrow_instruction is False
