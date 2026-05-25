#!/usr/bin/env python3
"""Premise check for variable/regime-adaptive TP (founder idea, 2026-05-25).

Direction is unpredictable (6 nulls). But is *move MAGNITUDE* predictable from the
regime at entry? If high-ADX (trend) bars reach a given favorable move far more often
than low-ADX (chop) bars, then: (a) scale TP to the regime, and (b) VETO entries whose
regime rarely clears 2xfee. This validates that premise BEFORE building an adaptive TP.

Method (leakage-clean): at each bar i (post-warmup, with K forward bars), classify the
regime from data up to i (base.regime_at uses ADX[i]); measure the STRICTLY-forward
favorable/adverse excursion over i+1..i+K:
  MFE = (max high[i+1..i+K] - close[i]) / close[i] * 100   (best-case favorable move)
  MAE = (min low  - close[i]) / close[i] * 100             (worst-case adverse)
Report, per regime: n, mean/median MFE, mean MAE, and P(MFE >= level) for level in
{2xfee, 0.5%, 1%, 2%} — i.e. how often that regime can clear fees / hit a TP.

NOT a strategy + NOT a backtest — a feature-predictiveness check on existing tapes.
Run: uv run python scripts/calibration/regime_move_predictiveness.py [--tf 5m] [--k 18]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import chart_floor_calibration as base  # noqa: E402  enrich + regime_at + WARMUP

TAPE_DIR = os.path.join(_HERE, "data", "tape")
SYMBOLS = ["WIF", "PYTH", "JTO", "BOME"]  # deep 5m tapes
TP_LEVELS = [0.08, 0.5, 1.0, 2.0]  # %; 0.08 = 2x Jupiter fee (the clear-fees bar)


def load(sym: str, tf: str) -> dict | None:
    path = os.path.join(TAPE_DIR, f"{sym}_{tf}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return base.enrich(json.load(f))


def excursions(c: dict, k: int) -> list[tuple[str, float, float]]:
    """[(regime, mfe%, mae%)] for each bar with a full K-bar forward window."""
    out: list[tuple[str, float, float]] = []
    n = len(c["close"])
    hi, lo, cl = c["high"], c["low"], c["close"]
    for i in range(base.WARMUP, n - k):
        if c["adx"][i] is None or cl[i] <= 0:
            continue
        fwd_hi = max(hi[i + 1 : i + 1 + k])
        fwd_lo = min(lo[i + 1 : i + 1 + k])
        mfe = (fwd_hi - cl[i]) / cl[i] * 100.0
        mae = (fwd_lo - cl[i]) / cl[i] * 100.0
        out.append((base.regime_at(c, i), mfe, mae))
    return out


def run(tf: str, k: int) -> dict:
    rows: list[tuple[str, float, float]] = []
    for sym in SYMBOLS:
        c = load(sym, tf)
        if c:
            rows.extend(excursions(c, k))
    print("=" * 96)
    print(f"REGIME → FORWARD-MOVE PREDICTIVENESS  (tf={tf}, K={k} bars fwd, {len(rows)} bars, {SYMBOLS})")
    print("  premise for variable TP: does the entry regime predict the achievable favorable move?")
    print("=" * 96)
    header = f"  {'regime':<13} {'n':>6}  {'meanMFE':>8} {'medMFE':>7} {'meanMAE':>8}  " + "  ".join(
        f"P(MFE>={lv}%)" for lv in TP_LEVELS
    )
    print(header)
    out: dict = {"tf": tf, "k": k, "n": len(rows), "by_regime": {}}
    for reg in ("trend", "transitional", "chop"):
        sub = [(m, a) for r, m, a in rows if r == reg]
        if not sub:
            continue
        mfes = [m for m, _ in sub]
        maes = [a for _, a in sub]
        probs = {lv: sum(1 for m in mfes if m >= lv) / len(mfes) for lv in TP_LEVELS}
        print(
            f"  {reg:<13} {len(sub):>6}  {st.mean(mfes):>+7.3f} {st.median(mfes):>+6.3f} "
            f"{st.mean(maes):>+7.3f}  "
            + "  ".join(f"{probs[lv]:>9.1%}" for lv in TP_LEVELS)
        )
        out["by_regime"][reg] = {
            "n": len(sub),
            "mean_mfe": st.mean(mfes),
            "median_mfe": st.median(mfes),
            "mean_mae": st.mean(maes),
            "p_mfe_ge": {str(lv): probs[lv] for lv in TP_LEVELS},
        }
    # headline read
    br = out["by_regime"]
    if "trend" in br and "chop" in br:
        lift = br["trend"]["mean_mfe"] - br["chop"]["mean_mfe"]
        print(
            f"\n  READ: trend mean-MFE - chop mean-MFE = {lift:+.3f}%  "
            f"(P(hit 2%): trend {br['trend']['p_mfe_ge']['2.0']:.0%} vs chop {br['chop']['p_mfe_ge']['2.0']:.0%}). "
            + (
                "Regime DOES separate achievable move → adaptive-TP/veto premise holds."
                if lift > 0.1
                else "Regime barely separates move → adaptive TP unlikely to help."
            )
        )
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--k", type=int, default=18)
    a = ap.parse_args()
    run(a.tf, a.k)
