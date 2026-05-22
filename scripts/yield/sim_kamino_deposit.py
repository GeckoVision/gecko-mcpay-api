#!/usr/bin/env python3
"""Step 1 free-simulation gate for the yield-base sleeve (Kamino USDC lend).

Pattern B/C gate, FIRST step: a $0 falsifier. It fetches (or replays) the
*unsigned* deposit calldata that onchainOS `defi deposit` returns and asserts
its structure offline. It NEVER signs and NEVER broadcasts — it does not call
`onchainos wallet contract-call`. If the calldata is malformed, the integration
is wrong and we learn it for $0, before any money moves.

Two modes:
    (default) replay  — decode + assert the committed fixture under fixtures/.
                        No network, no auth, CI-safe.
    --live            — re-fetch live calldata via the `onchainos defi deposit`
                        verb, then run the same assertions. Requires the CLI to
                        be authenticated (its own auth; this script reads no .env
                        secrets). Still never broadcasts.

Usage:
    python scripts/yield/sim_kamino_deposit.py            # offline replay (gate)
    python scripts/yield/sim_kamino_deposit.py --live     # re-fetch then assert

Exit code 0 = PASS (calldata structurally valid). Non-zero = FAIL.

Reference: docs/strategy/2026-05-22-yield-base-build-plan.md §4 Step 1.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from typing import Any

from solders.transaction import VersionedTransaction

# --- constants we assert against (the wire shape we're locking in) ---------
KLEND_PROGRAM_ID = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOLANA_CHAIN_INDEX = "501"
KAMINO_USDC_INVESTMENT_ID = "29130"  # Kamino / Main Pool, USDC lend, Solana
USDC_PRECISION = 6
EMPTY_SIG = "1" * 64  # solders renders an unsigned slot as 64 base58 '1's

FIXTURE_DIR = Path(__file__).parent / "fixtures"
DEPOSIT_FIXTURE = FIXTURE_DIR / "deposit_29130_25usdc.json"

# Sample deposit notional used to (re)generate the fixture.
SAMPLE_AMOUNT_USDC = "25"


# --- base58 (no external dep; the repo ships solders but not base58) --------
_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s.encode():
        n = n * 58 + _B58_ALPHABET.index(ch)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


class SimFailure(AssertionError):
    """Raised when the calldata fails a structural assertion (Step-1 FAIL)."""


def expected_minimal_units(amount_human: str, precision: int) -> int:
    """100 USDC at 6 decimals -> 100_000_000. Exact, no float."""
    from decimal import Decimal

    scaled = Decimal(amount_human) * (Decimal(10) ** precision)
    if scaled != scaled.to_integral_value():
        raise SimFailure(f"amount {amount_human} not representable in {precision} decimals (dust)")
    return int(scaled)


# --- the assertions --------------------------------------------------------
def assert_deposit_calldata(
    payload: dict[str, Any], *, expect_payer: str | None = None
) -> dict[str, Any]:
    """Assert an onchainOS deposit response carries a structurally-valid,
    unsigned Kamino deposit transaction. Returns a summary dict on PASS."""
    if not payload.get("ok"):
        raise SimFailure(f"response ok=False: {payload.get('error')!r}")

    data = payload.get("data") or {}
    data_list = data.get("dataList")
    if not data_list:
        raise SimFailure("empty dataList — no calldata returned")
    if len(data_list) != 1:
        # not fatal, but our v1 expects a single tx for a USDC lend deposit
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
    # tried to sign — the whole point of Step 1 is that nothing signs.
    if not all(str(s) == EMPTY_SIG for s in sigs):
        raise SimFailure("tx is SIGNED — Step 1 must never sign; aborting")

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

    return {
        "to": to,
        "payer": payer_acct,
        "decoded_bytes": len(raw),
        "num_account_keys": len(akeys),
        "num_instructions": len(instrs),
        "klend_instruction_count": prog_ids.count(KLEND_PROGRAM_ID),
        "programs": sorted(set(prog_ids)),
        "unsigned": True,
    }


# --- live fetch (never broadcasts) -----------------------------------------
def fetch_live_deposit(address: str, amount_human: str) -> dict[str, Any]:
    user_input = json.dumps(
        [
            {
                "tokenAddress": USDC_MINT,
                "chainIndex": SOLANA_CHAIN_INDEX,
                "coinAmount": amount_human,
                "tokenPrecision": str(USDC_PRECISION),
            }
        ]
    )
    cmd = [
        "onchainos",
        "defi",
        "deposit",
        "--investment-id",
        KAMINO_USDC_INVESTMENT_ID,
        "--address",
        address,
        "--chain",
        "solana",
        "--user-input",
        user_input,
    ]
    # Explicitly NOT `wallet contract-call`. This verb only builds calldata.
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise SimFailure(f"defi deposit CLI failed: {proc.stderr.strip()}")
    result: dict[str, Any] = json.loads(proc.stdout)
    return result


def get_wallet_address() -> str:
    proc = subprocess.run(
        ["onchainos", "wallet", "addresses"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    data = json.loads(proc.stdout)["data"]
    sol = data.get("sol") or data.get("solana") or []
    if not sol:
        raise SimFailure("no Solana address on the wallet")
    addr: str = sol[0]["address"]
    return addr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--live",
        action="store_true",
        help="re-fetch calldata via the CLI before asserting (still never broadcasts)",
    )
    ap.add_argument("--amount", default=SAMPLE_AMOUNT_USDC, help="deposit notional (human)")
    args = ap.parse_args()

    # precision check first (pure, no I/O)
    units = expected_minimal_units(args.amount, USDC_PRECISION)
    print(f"[precision] {args.amount} USDC -> {units} minimal units (10^{USDC_PRECISION})")

    expect_payer = None
    if args.live:
        addr = get_wallet_address()
        expect_payer = addr
        print(f"[live] fetching deposit calldata for {addr[:6]}...{addr[-4:]}")
        payload = fetch_live_deposit(addr, args.amount)
    else:
        if not DEPOSIT_FIXTURE.exists():
            print(f"FAIL: fixture missing: {DEPOSIT_FIXTURE}", file=sys.stderr)
            return 2
        print(f"[replay] {DEPOSIT_FIXTURE.name}")
        payload = json.loads(DEPOSIT_FIXTURE.read_text())

    try:
        summary = assert_deposit_calldata(payload, expect_payer=expect_payer)
    except SimFailure as exc:
        print(f"\nStep 1 free-sim: FAIL — {exc}", file=sys.stderr)
        return 1

    print("\n[deposit calldata summary]")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("\nStep 1 free-sim (deposit calldata): PASS")
    print("  -> structurally-valid UNSIGNED Kamino USDC-lend deposit tx, $0 spent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
