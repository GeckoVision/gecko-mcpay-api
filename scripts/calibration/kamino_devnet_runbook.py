#!/usr/bin/env python3
"""Kamino profit-vault DEVNET runbook (S43).

ONE end-to-end devnet pass: load/create a gitignored devnet keypair, airdrop
devnet SOL, deposit into the (mock-or-Kamino) vault, accrue, read the position,
and run the merged S42 monitor to print a HOLD / EXIT / DELEVERAGE / ROTATE
verdict on a REAL on-chain position.

NO real money. NO mainnet. Default cluster = devnet, default adapter = mock.

Usage (from repo root):
    uv run python scripts/calibration/kamino_devnet_runbook.py
    uv run python scripts/calibration/kamino_devnet_runbook.py --principal 1000 --accrue-days 365
    uv run python scripts/calibration/kamino_devnet_runbook.py --leverage 5 --drawdown 0.10
    uv run python scripts/calibration/kamino_devnet_runbook.py --profile crypto_only
    uv run python scripts/calibration/kamino_devnet_runbook.py --no-network   # offline: skip RPC, monitor-only
    uv run python scripts/calibration/kamino_devnet_runbook.py --adapter kamino  # raises (stub): see runbook doc

Keypair: ~/.config/gecko/devnet-vault.keypair.json (gitignored via *.keypair.json),
override with --keypair or GECKO_DEVNET_KEYPAIR. Only the PUBLIC key is printed.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

# Put contest_bot on the path so `kamino.*` imports resolve (mirrors the repo
# convention in contest_bot/kamino/__init__.py).
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "contest_bot"))

from kamino.devnet_harness import (  # noqa: E402
    DEVNET_RPC,
    default_keypair_path,
    ensure_devnet_funds,
    hurdle_from_profile,
    load_or_create_keypair,
    make_adapter,
    run_flow,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Kamino profit-vault devnet harness (S43)")
    ap.add_argument("--adapter", choices=["mock", "kamino"], default="mock")
    ap.add_argument("--rpc", default=DEVNET_RPC, help="devnet RPC URL")
    ap.add_argument("--keypair", default=None, help="path to *.keypair.json (gitignored)")
    ap.add_argument("--principal", type=float, default=1000.0, help="logical USD deposit")
    ap.add_argument("--accrue-days", type=float, default=365.0, help="simulated position age")
    ap.add_argument("--leverage", type=float, default=5.0)
    ap.add_argument("--collateral-yield", type=float, default=0.06)
    ap.add_argument("--borrow-rate", type=float, default=0.04)
    ap.add_argument(
        "--correlated",
        action="store_true",
        default=True,
        help="correlated pair (stable/stable, LST/SOL) — no price-liquidation risk",
    )
    ap.add_argument(
        "--uncorrelated",
        dest="correlated",
        action="store_false",
        help="volatile/uncorrelated — exercises the liquidation-buffer branch",
    )
    ap.add_argument(
        "--drawdown",
        type=float,
        default=None,
        help="Oracle-predicted downside on the collateral leg (e.g. 0.10 = 10%%)",
    )
    ap.add_argument("--profile", choices=["fiat_cdb_br", "crypto_only"], default="fiat_cdb_br")
    ap.add_argument(
        "--no-network",
        action="store_true",
        help="skip RPC/airdrop/deposit; run the monitor only (offline falsifier)",
    )
    args = ap.parse_args()

    kp_path = Path(args.keypair) if args.keypair else default_keypair_path()
    keypair = load_or_create_keypair(kp_path)
    hurdle = hurdle_from_profile(args.profile)
    principal = Decimal(str(args.principal))
    accrue_seconds = args.accrue_days * 24 * 3600

    print("── Kamino profit-vault DEVNET harness (S43) ──────────────────────")
    print(f"  cluster      : devnet ({args.rpc})")
    print(f"  adapter      : {args.adapter}")
    print(f"  keypair      : {kp_path}  (gitignored, secret never printed)")
    print(f"  pubkey       : {keypair.pubkey()}")
    print(f"  principal    : ${principal} (logical)")
    print(f"  leverage     : {args.leverage}x   correlated={args.correlated}")
    print(f"  rates        : yield {args.collateral_yield:.2%} / borrow {args.borrow_rate:.2%}")
    print(f"  accrual      : {args.accrue_days} days")
    print(f"  hurdle       : {hurdle.apy:.2%} ({hurdle.label})")
    if args.drawdown is not None:
        print(f"  oracle dd    : {args.drawdown:.2%} predicted downside")
    print()

    adapter = (
        make_adapter(
            args.adapter,
            rpc_url=args.rpc,
            mock_collateral_yield=args.collateral_yield,
            mock_borrow_rate=args.borrow_rate,
            leverage=args.leverage,
            correlated=args.correlated,
        )
        if args.adapter == "mock"
        else make_adapter(args.adapter, rpc_url=args.rpc)
    )

    balance_sol = 0.0
    if not args.no_network and args.adapter == "mock":
        from solana.rpc.api import Client

        client = Client(args.rpc)
        print("  [1/4] ensuring devnet funds (airdrop if low)…")
        try:
            balance_sol = ensure_devnet_funds(client, keypair.pubkey(), rpc_url=args.rpc)
        except Exception as exc:  # surface verbatim per CLAUDE.md
            print(f"        airdrop failed: {type(exc).__name__}: {exc}")
            print("        -> fund manually at https://faucet.solana.com (paste the pubkey above)")
            return 2
        print(f"        balance: {balance_sol:.4f} SOL")
        if balance_sol < 0.002:
            print("        insufficient for a deposit tx; fund at https://faucet.solana.com")
            return 2

    if args.no_network:
        # Offline monitor-only: read_position needs no network for the mock adapter.
        from kamino.devnet_harness import HarnessResult
        from kamino.monitor import evaluate

        position = adapter.read_position(keypair.pubkey(), principal, accrue_seconds)
        verdict = evaluate(position.strategy, hurdle=hurdle, predicted_drawdown_pct=args.drawdown)
        result = HarnessResult(
            pubkey=str(keypair.pubkey()),
            balance_sol=0.0,
            deposit_sig="(offline — no deposit)",
            position=position,
            verdict=verdict,
        )
    else:
        print("  [2/4] depositing into vault (real devnet tx)…")
        print("  [3/4] reading position + accruing…")
        result = run_flow(
            adapter,
            keypair,
            principal_usd=principal,
            accrual_seconds=accrue_seconds,
            hurdle=hurdle,
            predicted_drawdown_pct=args.drawdown,
            balance_sol=balance_sol,
        )
        print(f"        deposit sig: {result.deposit_sig}")
        if args.adapter == "mock":
            print(
                f"        explorer   : https://explorer.solana.com/tx/{result.deposit_sig}?cluster=devnet"
            )

    pos = result.position
    print("  [4/4] S42 monitor verdict:")
    print()
    print(f"    net APY        : {pos.strategy.net_apy:.2%}")
    print(
        f"    spread         : {pos.strategy.spread:.2%} (inverted={pos.strategy.spread_inverted})"
    )
    print(f"    operating LTV  : {pos.strategy.operating_ltv:.2%}")
    print(f"    liq drop buffer: {pos.strategy.liquidation_drop_pct:.0%}")
    print(
        f"    value          : ${pos.value_usd:.2f}  (principal ${pos.principal_usd}, "
        f"+${pos.value_usd - pos.principal_usd:.2f} over {pos.elapsed_years:.2f}y)"
    )
    print()
    print(f"    >>> VERDICT: {result.verdict.action}")
    print(f"        {result.verdict.reason}")
    if result.verdict.suggested_leverage is not None:
        print(f"        suggested leverage: {result.verdict.suggested_leverage}x")
    print()
    print("  done. (no mainnet, no real money; devnet SOL only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
