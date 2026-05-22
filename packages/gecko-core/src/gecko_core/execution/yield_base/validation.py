"""Pure structural validation of onchainOS Kamino USDC-lend calldata.

Promoted from ``scripts/yield/sim_kamino_deposit.py`` (Step 1 throwaway) into
gecko-core (Step 2, Pattern C). Every function here is pure + typed + offline:
it decodes a Solana ``VersionedTransaction`` from the ``serializedData`` an
onchainOS ``defi deposit`` response carries and asserts the wire shape we lock
in for the yield-base sleeve.

Hard safety invariants enforced here (the whole point of the $0 gate):
    - the tx must be UNSIGNED — every signature slot is the empty 64-'1' base58
      sentinel solders renders for an unsigned slot. A signed tx means something
      tried to sign; that is a FAIL, never silently accepted.
    - ``to`` (and at least one invoked program) is the Kamino klend program.
    - the fee-payer (account[0]) matches the response ``from``.
    - amounts round-trip to exact 10^6 minimal units (no float, no dust).

NO network. NO signing. NO broadcast. NO private keys. NO RPC.

Reference: ``docs/strategy/2026-05-22-yield-base-build-plan.md`` §4 Step 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from solders.transaction import VersionedTransaction

# --- the wire shape we lock in --------------------------------------------
KLEND_PROGRAM_ID = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOLANA_CHAIN_INDEX = "501"
KAMINO_USDC_INVESTMENT_ID = "29130"  # Kamino / Main Pool, USDC lend, Solana
USDC_PRECISION = 6
# solders renders an unsigned signature slot as 64 base58 '1's.
EMPTY_SIG = "1" * 64

# --- base58 (no external dep; the repo ships solders but not base58) -------
_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class SimFailure(AssertionError):
    """Raised when the calldata fails a structural assertion (a Step gate FAIL)."""


@dataclass(frozen=True)
class CalldataSummary:
    """Structured result of a passing deposit-calldata validation."""

    to: str
    payer: str | None
    decoded_bytes: int
    num_account_keys: int
    num_instructions: int
    klend_instruction_count: int
    programs: tuple[str, ...]
    unsigned: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "to": self.to,
            "payer": self.payer,
            "decoded_bytes": self.decoded_bytes,
            "num_account_keys": self.num_account_keys,
            "num_instructions": self.num_instructions,
            "klend_instruction_count": self.klend_instruction_count,
            "programs": list(self.programs),
            "unsigned": self.unsigned,
        }


def b58decode(s: str) -> bytes:
    """Decode a base58 string to bytes. Pure; no external dependency."""
    n = 0
    for ch in s.encode():
        n = n * 58 + _B58_ALPHABET.index(ch)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def expected_minimal_units(amount_human: str, precision: int) -> int:
    """100 USDC at 6 decimals -> 100_000_000. Exact, no float, dust rejected."""
    scaled = Decimal(amount_human) * (Decimal(10) ** precision)
    if scaled != scaled.to_integral_value():
        raise SimFailure(f"amount {amount_human} not representable in {precision} decimals (dust)")
    return int(scaled)


def assert_deposit_calldata(
    payload: dict[str, Any], *, expect_payer: str | None = None
) -> CalldataSummary:
    """Assert an onchainOS deposit response carries a structurally-valid,
    UNSIGNED Kamino deposit transaction.

    Returns a :class:`CalldataSummary` on PASS; raises :class:`SimFailure` on
    any structural violation. Pure + offline — no network, no signing.
    """
    if not payload.get("ok"):
        raise SimFailure(f"response ok=False: {payload.get('error')!r}")

    data = payload.get("data") or {}
    data_list = data.get("dataList")
    if not data_list:
        raise SimFailure("empty dataList — no calldata returned")
    if len(data_list) != 1:
        # not fatal in general, but our v1 expects a single tx for a USDC lend
        raise SimFailure(f"expected 1 tx in dataList, got {len(data_list)}")

    item = data_list[0]
    to = item.get("to")
    ser = item.get("serializedData")
    payer = item.get("from")

    if to != KLEND_PROGRAM_ID:
        raise SimFailure(f"'to' is {to!r}, expected Kamino klend {KLEND_PROGRAM_ID}")
    if not ser:
        raise SimFailure("serializedData is empty")
    if expect_payer is not None and payer != expect_payer:
        raise SimFailure(f"'from' {payer!r} != expected payer {expect_payer!r}")

    # decode + parse as a real Solana versioned tx
    raw = b58decode(ser)
    if len(raw) < 64:
        raise SimFailure(f"decoded tx too small ({len(raw)} bytes)")
    try:
        tx = VersionedTransaction.from_bytes(raw)
    except Exception as exc:
        raise SimFailure(f"serializedData is not a decodable Solana tx: {exc}") from exc

    msg = tx.message
    sigs = list(tx.signatures)
    if len(sigs) < 1:
        raise SimFailure("tx has no signature slots")
    # SAFETY GATE: the tx must be UNSIGNED. A signed tx here means something
    # tried to sign — the whole point of the gate is that nothing signs.
    if not all(str(s) == EMPTY_SIG for s in sigs):
        raise SimFailure("tx is SIGNED — the gate must never sign; aborting")

    akeys = list(msg.account_keys)
    instrs = list(msg.instructions)
    if not instrs:
        raise SimFailure("tx has zero instructions")

    prog_ids = [str(akeys[ix.program_id_index]) for ix in instrs]
    if KLEND_PROGRAM_ID not in prog_ids:
        raise SimFailure(f"no Kamino klend instruction in tx; programs invoked: {prog_ids}")

    payer_acct = str(akeys[0]) if akeys else None
    if payer is not None and payer_acct != payer:
        raise SimFailure(f"fee-payer account[0] {payer_acct!r} != response 'from' {payer!r}")

    return CalldataSummary(
        to=to,
        payer=payer_acct,
        decoded_bytes=len(raw),
        num_account_keys=len(akeys),
        num_instructions=len(instrs),
        klend_instruction_count=prog_ids.count(KLEND_PROGRAM_ID),
        programs=tuple(sorted(set(prog_ids))),
        unsigned=True,
    )
