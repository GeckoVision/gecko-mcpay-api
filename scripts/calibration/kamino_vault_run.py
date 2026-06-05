#!/usr/bin/env python3
"""A6 — "set a strategy → go": the gated real-money profit-vault flow as one command.

Pipeline: profile + amount → SAFETY GATE (vault_gate, fed the live market-temp
downside) → if approved → KaminoLiveExecutor (DRY by default; real submit only with
--live --confirm). This is the proven 2026-06-05 mainnet flow (deposit/withdraw via
OKX TEE), wrapped so it always passes the gate first.

    # dry (build + gate, NEVER submits):
    uv run python scripts/calibration/kamino_vault_run.py --owner <pubkey> --usd 10 --action deposit
    # LIVE (real money — both flags required, founder-gated):
    uv run python scripts/calibration/kamino_vault_run.py --owner <pubkey> --usd 10 --action deposit --live --confirm
"""

from __future__ import annotations

import argparse
import os
import sys

_CB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "contest_bot")
if _CB not in sys.path:
    sys.path.insert(0, _CB)

import market_temp as mt  # noqa: E402
from kamino import vault_gate as vg  # noqa: E402
from kamino import vault_orchestrator as vo  # noqa: E402
from kamino.live_executor import KaminoLiveExecutor  # noqa: E402
from kamino.monitor import hurdle_for  # noqa: E402
from kamino.multiply import LeverageStrategy  # noqa: E402

# Conservative tier = plain USDC lend (no leverage, no liquidation surface).
_LEND = LeverageStrategy("USDC lend", 0.058, 0.0, 1.0, 0.75, 0.80, True, "stable_spread")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True, help="wallet pubkey (OKX Agentic Wallet)")
    ap.add_argument("--usd", type=float, required=True)
    ap.add_argument("--action", choices=["deposit", "withdraw"], default="deposit")
    ap.add_argument("--profile", default="crypto_only")
    ap.add_argument("--live", action="store_true", help="arm real submit (still needs --confirm)")
    ap.add_argument("--confirm", action="store_true", help="confirm the real submit")
    args = ap.parse_args()

    hurdle = hurdle_for(args.profile)

    # 1. SAFETY GATE (only deposits are gated on strategy health; withdraw always allowed)
    if args.action == "deposit":
        try:
            snap = mt.load_snapshot()
        except Exception:
            snap = {}
        dd = vo.predicted_drawdown_from_market_temp(snap)
        gate = vg.vault_check(
            vg.DEPOSIT, args.usd,
            vg.VaultPolicy(max_allocation_usd=10_000.0, hurdle=hurdle),
            strategy=_LEND, predicted_drawdown_pct=dd,
        )
        print(f"GATE: allow={gate.allow} monitor={gate.monitor_action} reasons={gate.reasons}")
        if not gate.allow:
            print("BLOCKED by safety gate — not executing.")
            return

    # 2. EXECUTE (dry unless --live AND --confirm)
    ex = KaminoLiveExecutor(args.owner, dry_run=not args.live)
    fn = ex.deposit if args.action == "deposit" else ex.withdraw
    out = fn(args.usd, confirm=args.confirm)
    print(f"\n{args.action.upper()} ${args.usd}")
    print(f"  ok={out.ok} submitted={out.submitted}")
    print(f"  {out.detail}")
    if out.tx_hash:
        print(f"  txHash: {out.tx_hash}")
        print("  ⚠ txHash is for tracking only — verify on-chain confirmation.")
    if not out.submitted and out.ok:
        print("  (dry run — add --live --confirm to submit real money)")


if __name__ == "__main__":
    main()
