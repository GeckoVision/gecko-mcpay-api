#!/usr/bin/env python3
"""based.bid DEVNET round-trip smoke (S50) — buy → poll → sell on chainId 5011.

The moment we have a sandbox token mint, ONE command proves the full devnet path:
based.bid builds the unsigned tx (HTTP) → we sign it with a LOCAL devnet keypair
(solders) → submit to the devnet RPC. No OKX TEE, no mainnet, no real money.

DOUBLE-GATED. Dry-run by DEFAULT — it builds + safety-gates the tx but NEVER
submits. `--confirm` arms BOTH gates (dry_run off + per-call confirm) and actually
submits on devnet. Without `--confirm` this script can NOT move a single lamport.

    # dry-run (default — builds, gates, never submits):
    uv run python scripts/calibration/basedbid_devnet_roundtrip.py --mint <MINT>

    # actually submit on devnet (needs the funded devnet keypair):
    uv run python scripts/calibration/basedbid_devnet_roundtrip.py --mint <MINT> --confirm

Env:
  GECKO_DEVNET_KEYPAIR   path to the gitignored devnet keypair (default
                         ~/.config/gecko/devnet-vault.keypair.json)
  GECKO_DEVNET_RPC       devnet cluster RPC (default https://api.devnet.solana.com)

The keypair's secret is NEVER printed — only its public key.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

_CB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "contest_bot")
if _CB not in sys.path:
    sys.path.insert(0, _CB)

import basedbid_exec as bb  # noqa: E402
import trade_safety as ts  # noqa: E402


def _print_outcome(label: str, out: bb.BasedBidOutcome) -> None:
    flag = "OK " if out.ok else "ERR"
    sub = "SUBMITTED" if out.submitted else "not-submitted"
    print(f"  [{flag}] {label}: {sub}")
    print(f"        {out.detail}")
    if out.tx_hash:
        print(f"        txHash: {out.tx_hash}")
        print(f"        explorer: https://explorer.solana.com/tx/{out.tx_hash}?cluster=devnet")


def main() -> int:
    ap = argparse.ArgumentParser(description="based.bid devnet round-trip smoke")
    ap.add_argument("--mint", required=True, help="sandbox token mint (chainId 5011)")
    ap.add_argument("--amount", type=float, default=0.01, help="SOL per leg (default 0.01)")
    ap.add_argument("--poll", type=float, default=8.0, help="seconds to wait between buy and sell")
    ap.add_argument(
        "--confirm",
        action="store_true",
        help="ARM both gates and ACTUALLY submit on devnet (default: dry-run, no submit)",
    )
    args = ap.parse_args()

    dry_run = not args.confirm
    rpc = bb.default_devnet_rpc()

    print("=" * 72)
    print("based.bid DEVNET round-trip smoke (chainId 5011)")
    print(f"  mint    : {args.mint}")
    print(f"  amount  : {args.amount} SOL/leg")
    print(f"  rpc     : {rpc}")
    print(f"  mode    : {'DRY-RUN (no submit)' if dry_run else 'CONFIRM → WILL SUBMIT ON DEVNET'}")
    print("=" * 72)

    # Load the local devnet keypair (public key only is ever printed).
    try:
        keypair = bb.load_devnet_keypair()
    except Exception as exc:
        print(f"FATAL: cannot load devnet keypair: {type(exc).__name__}: {exc}")
        return 2
    owner = str(keypair.pubkey())
    print(f"  signer  : {owner} (local devnet keypair)")

    # Read-only balance preflight (safe — no submit).
    if not dry_run:
        try:
            from solana.rpc.api import Client

            bal = Client(rpc).get_balance(keypair.pubkey()).value / 1_000_000_000
            print(f"  balance : {bal:.4f} SOL")
            if bal < args.amount * 2:
                print(f"  WARN: balance below {args.amount * 2} SOL needed for 2 legs + fees")
        except Exception as exc:
            print(f"  WARN: balance preflight failed: {type(exc).__name__}: {exc}")

    # A policy + ctx that PASS the safety gate (DEPLOY verdict, generous devnet cap).
    policy = ts.basedbid_policy(max_notional_usd=10_000.0)
    safety_ctx = ts.SafetyContext(strategy_verdict="DEPLOY")

    adapter = bb.BasedBidExecutionAdapter(
        owner,
        dry_run=dry_run,
        sandbox=True,  # chainId 5011
        signer=bb.SIGNER_LOCAL_KEYPAIR,
        devnet_keypair=keypair,
        devnet_rpc=rpc,
        policy=policy,
        safety_ctx=safety_ctx,
        global_kill_fn=lambda: False,  # smoke script: kill off
    )

    print("\n[1/3] BUY")
    buy = adapter.buy(args.mint, args.amount, confirm=args.confirm)
    _print_outcome("buy", buy)
    if not buy.ok:
        print("\nBUY failed — aborting round-trip.")
        return 1

    print(f"\n[2/3] POLL ({args.poll}s)")
    if not dry_run:
        time.sleep(args.poll)
    else:
        print("  (dry-run: skipping wait)")

    print("\n[3/3] SELL")
    sell = adapter.sell(args.mint, args.amount, confirm=args.confirm)
    _print_outcome("sell", sell)
    if not sell.ok:
        print("\nSELL failed.")
        return 1

    print("\n" + "=" * 72)
    if dry_run:
        print("DRY-RUN complete: both legs BUILT + safety-gated, NOTHING submitted.")
        print("Re-run with --confirm (and a funded devnet keypair) to submit on devnet.")
    else:
        print("CONFIRM complete: both legs submitted on devnet. Verify the txHashes above.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
