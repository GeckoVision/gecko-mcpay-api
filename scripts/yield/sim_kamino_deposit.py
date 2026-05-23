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

# The structural validation now lives in gecko-core (Step 2, Pattern C). This
# script is a thin caller; it owns only the CLI fetch + the argparse surface.
from gecko_core.execution.yield_base import (
    KAMINO_USDC_INVESTMENT_ID,
    SOLANA_CHAIN_INDEX,
    USDC_MINT,
    USDC_PRECISION,
    SimFailure,
    assert_deposit_calldata,
    expected_minimal_units,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
# id 227050 = Kamino USDC SUPPLY (SINGLE_EARN). The old 29130 fixture was the
# BORROW side and is kept only as a negative case (gate must reject it).
DEPOSIT_FIXTURE = FIXTURE_DIR / "deposit_227050_5usdc.json"

# Sample deposit notional used to (re)generate the fixture.
SAMPLE_AMOUNT_USDC = "5"


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
    for k, v in summary.to_dict().items():
        print(f"  {k}: {v}")
    print("\nStep 1 free-sim (deposit calldata): PASS")
    print("  -> structurally-valid UNSIGNED Kamino USDC-lend deposit tx, $0 spent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
