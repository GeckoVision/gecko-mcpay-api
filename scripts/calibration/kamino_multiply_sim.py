#!/usr/bin/env python3
"""Kamino profit-vault simulator (S42) — local, no real money (Pattern B).

Models the three risk profiles, answers the founder's questions numerically, and
demonstrates the yield-safety monitor: the hurdle rate (beat a CDB or don't
bother) and the Oracle-predicted-downside vs liquidation-buffer rule (10x dies on
a 10% drop; 5x has a 20% margin — watch it like we watch a trade).

    uv run python scripts/calibration/kamino_multiply_sim.py            # doc/anchor rates
    uv run python scripts/calibration/kamino_multiply_sim.py --live     # pull live USDC rates

This is the FALSIFIER. Devnet/mainnet is the final check, never the debug tool.
"""

from __future__ import annotations

import argparse
import os
import sys

_CB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "contest_bot")
if _CB not in sys.path:
    sys.path.insert(0, _CB)

from kamino import monitor as mon  # noqa: E402
from kamino.multiply import LeverageStrategy, time_to_target  # noqa: E402

# Profile presets — realistic rates from the 2026-06-04 defi-engineer live pull + docs.
# (collateral_yield, borrow_rate, leverage, max_ltv, liq_ltv, correlated, source)
PROFILES: dict[str, LeverageStrategy] = {
    "conservative": LeverageStrategy(
        "USDC lend (no leverage)", 0.058, 0.0, 1.0, 0.75, 0.80, True, "stable_spread"
    ),
    "moderate": LeverageStrategy(
        "JitoSOL/SOL loop 4x", 0.070, 0.060, 4.0, 0.90, 0.93, True, "lst_staking"
    ),
    "aggressive": LeverageStrategy(
        "JLP/USDC loop 3.2x", 0.120, 0.060, 3.2, 0.69, 0.73, False, "jlp_fees"
    ),
}


def _row(label: str, s: LeverageStrategy, hurdle: mon.Hurdle, pred_dd: float | None) -> str:
    v = mon.evaluate(s, hurdle=hurdle, predicted_drawdown_pct=pred_dd)
    t = time_to_target(1000.0, s.net_apy, 100.0)
    t_str = f"{t * 12:.1f} mo" if t else "never"
    buf = s.liquidation_drop_pct
    buf_str = f"{buf:.0%}" if not s.correlated else f"{buf:.0%} (depeg; corr.)"
    return (
        f"  {label:<26} net {s.net_apy:+6.2%}  →+$100 on $1k: {t_str:>8}  "
        f"liq-buffer {buf_str:<16} [{v.action}] {v.reason}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="pull live USDC supply/borrow from Kamino")
    ap.add_argument("--profile", default="crypto_only", help="hurdle profile: crypto_only | fiat")
    ap.add_argument("--predict-drawdown", type=float, default=None,
                    help="Oracle-predicted adverse %% move on the volatile leg, e.g. 0.12")
    args = ap.parse_args()

    hurdle = mon.CRYPTO_ONLY if args.profile == "crypto_only" else mon.FIAT_CDB_BR
    print(f"\nHurdle: {hurdle.apy:.0%} ({hurdle.label}) — {hurdle.note}")
    if args.predict_drawdown is not None:
        print(f"Oracle predicted downside on volatile leg: {args.predict_drawdown:.0%}")

    print("\n── Profiles ─────────────────────────────────────────────────────")
    for name, s in PROFILES.items():
        print(_row(f"{name}: {s.name}", s, hurdle, args.predict_drawdown))

    # Demo 1: the dead stable loop (live or the verified 2026-06-04 inverted rates).
    sup, bor = 0.0632, 0.0808
    src = "doc/2026-06-04"
    if args.live:
        try:
            from kamino.apy_cache import KAMINO_USDC_RESERVE, fetch_reserve_rates

            sup, bor = fetch_reserve_rates(KAMINO_USDC_RESERVE)
            src = "LIVE"
        except Exception as exc:
            print(f"\n  (live fetch failed: {type(exc).__name__}: {exc} — using doc rates)")
    dead = LeverageStrategy("USDC/USDC loop 4x", sup, bor, 4.0, 0.85, 0.90, True, "stable_spread")
    print(f"\n── Stable-loop check ({src}: supply {sup:.2%}, borrow {bor:.2%}) ──")
    print(_row("stable loop 4x", dead, hurdle, None))

    # Demo 2: the founder's 10x-vs-5x liquidation margin on a volatile asset.
    # max_ltv 0.90 → max ~10x openable; liq_ltv 0.93 (a realistic eMode haircut).
    # NOTE: the naive "10x dies on a 10% drop" assumes liq_ltv≈100%; with a real
    # 93% threshold the buffer is TIGHTER (10x → ~3%), which only strengthens the
    # case for lower leverage. The buffer is what the Oracle's downside watches.
    print("\n── Leverage vs liquidation buffer (volatile collateral, liq_ltv 0.93) ──")
    base = LeverageStrategy("volatile/USDC", 0.20, 0.06, 1.0, 0.90, 0.93, False, "jlp_fees")
    pred = args.predict_drawdown if args.predict_drawdown is not None else 0.12
    print(f"  (Oracle predicts ~{pred:.0%} downside on the collateral)")
    for lev in (10.0, 5.0, 3.0):
        s = base.with_leverage(lev)
        v = mon.evaluate(s, hurdle=hurdle, predicted_drawdown_pct=pred)
        print(f"  {lev:>4.0f}x  liq on {s.liquidation_drop_pct:>4.0%} drop  net {s.net_apy:+5.1%}  "
              f"[{v.action}] {v.reason}")
    print()


if __name__ == "__main__":
    main()
