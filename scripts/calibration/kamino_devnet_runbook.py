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


def _run_kamino(args, keypair, principal: Decimal) -> int:
    """Real Kamino klend deposit via the TS sidecar: build (sidecar) -> sign
    (harness keypair) -> optionally submit. Surfaces build/submit errors verbatim.
    """
    from kamino.devnet_harness import KaminoDevnetVaultAdapter, SidecarError

    rpc = args.rpc
    if args.cluster == "mainnet" and rpc == DEVNET_RPC:
        rpc = "https://api.mainnet-beta.solana.com"

    print("── Kamino REAL klend deposit (TS-sidecar) ────────────────────────")
    print(f"  cluster      : {args.cluster} ({rpc})")
    print("  adapter      : kamino (klend TS-sidecar build -> Python sign)")
    print(f"  pubkey       : {keypair.pubkey()}  (gitignored, secret never printed)")
    print(f"  principal    : ${principal} USDC (logical)")
    print(f"  submit       : {args.submit}")
    if args.cluster == "mainnet" and args.submit:
        print("  REFUSING mainnet submit from the runbook — founder-gated.")
        return 2
    print()

    adapter = KaminoDevnetVaultAdapter(
        rpc_url=rpc,
        cluster=args.cluster,
        market=args.market,
        reserve=args.reserve,
        submit=args.submit,
    )
    try:
        print("  [1/2] building unsigned tx via sidecar + signing locally…")
        sig = adapter.deposit(keypair, principal)
    except SidecarError as exc:  # verbatim per CLAUDE.md
        print(f"        FAILED (verbatim): {exc}")
        if args.cluster == "devnet":
            print(
                "        -> devnet USDC reserve has no working oracle "
                "(verify_devnet.ts). Use --cluster mainnet for the real build path."
            )
        return 2

    b = adapter.last_build or {}
    print("  [2/2] build + sign verified:")
    print(f"        program id : {b.get('programId')}")
    print(f"        action     : {b.get('action')}")
    print(f"        num ix     : {b.get('numInstructions')}")
    print(f"        ix labels  : {b.get('ixLabels')}")
    print(f"        amount base: {b.get('amountBaseUnits')}")
    print(f"        result     : {sig}")
    if not args.submit:
        print("        (build+sign only — not submitted; pass --submit to send)")
    print()
    print("  done. (no mainnet submit; founder-gated)")
    return 0


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
    # ── Kamino-adapter (real klend TS-sidecar) flags ──────────────────────
    ap.add_argument(
        "--cluster",
        choices=["devnet", "mainnet"],
        default="devnet",
        help="cluster for --adapter kamino (devnet has no usable USDC oracle; "
        "mainnet is the real path, build+sign only unless --submit)",
    )
    ap.add_argument("--market", default=None, help="klend lending market pubkey (kamino adapter)")
    ap.add_argument("--reserve", default=None, help="klend USDC reserve pubkey (kamino adapter)")
    ap.add_argument(
        "--submit",
        action="store_true",
        help="actually SEND the signed tx (default: build+sign only). NEVER use "
        "with --cluster mainnet without explicit founder go-ahead.",
    )
    args = ap.parse_args()

    kp_path = Path(args.keypair) if args.keypair else default_keypair_path()
    keypair = load_or_create_keypair(kp_path)
    hurdle = hurdle_from_profile(args.profile)
    principal = Decimal(str(args.principal))
    accrue_seconds = args.accrue_days * 24 * 3600

    # ── Real Kamino adapter (klend TS-sidecar): build -> sign -> submit ───
    if args.adapter == "kamino":
        return _run_kamino(args, keypair, principal)

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
