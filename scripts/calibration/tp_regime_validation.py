#!/usr/bin/env python3
"""TP-level x regime calibration validation (s41, 2026-05-22).

Extends `chart_floor_calibration.py` to answer the two open questions the base
study left:

  D1.a  PER-REGIME EV: in the TREND subset, is there ANY chart floor whose EV
        confidence interval EXCLUDES zero? (The base study mixed regimes and
        found 0% would-have-won overall. This re-asks the question conditioned
        on trend, where momentum *should* have an edge if it has one at all.)

  D1.b  TP2 vs TP3 vs TP4 vs TP5, NET OF FEES, per regime:
          - break-even win-rate at each TP target, for a round-trip fee band
          - the realized would-have-won rate at each TP target
          - net EV per trade (gross realized pnl minus round-trip fee)
        This settles whether lowering TP 4 -> 2 (live, s41) helped or hurt, and
        whether a regime-conditional TP rule (TP4-5 when ADX>=25 AND 24h range
        >=4%, else TP2-3) is supported by the data.

This script REUSES the base module's faithful machinery (candidate detection,
chart-confidence proxy, regime, enrichment, bootstrap) and ONLY swaps the exit
simulation to be TP-parameterised. Read-only w.r.t. the live bot.

Usage:
    python3 scripts/calibration/tp_regime_validation.py --cached /tmp/cal_candles_d1.json
    python3 scripts/calibration/tp_regime_validation.py            # fetches live
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import chart_floor_calibration as base  # noqa: E402  the faithful base study

# ── Fee model ───────────────────────────────────────────────────────
# Founder spec: realistic round-trip ~0.5-1%. S40 grid plan cited ~0.6%/leg DEX
# fees on thin memes. We report a band: optimistic 0.5%, central 0.75%, thin 1.0%.
FEE_RT_BAND = [0.5, 0.75, 1.0]  # round-trip %, applied to realized gross pnl
FEE_RT_CENTRAL = 0.75

# ── TP targets to settle ────────────────────────────────────────────
TP_TARGETS = [2.0, 3.0, 4.0, 5.0]
SL_PCT = base.SL_PCT  # 3.0, unchanged across the study

# Regime-conditional TP rule candidate (founder's proposed rule):
#   TP4-5 when ADX>=25 AND 24h range >=4%, else TP2-3.
RULE_HI_TP = 4.0
RULE_LO_TP = 2.0
RULE_ADX = 25.0
RULE_RANGE_PCT = 4.0


# ── TP-parameterised exit sim (forks base.simulate_exit, TP injectable) ──
def simulate_exit_tp(c: dict, entry_idx: int, tp_pct: float) -> float:
    """Identical to base.simulate_exit but with an injectable TP target.

    All other exits (SL, trail, stall_green, flat_stall, time-stop) are byte-
    faithful to the base/live logic. Conservative SL-before-TP on straddle bars.
    """
    ep = c["close"][entry_idx]
    if ep <= 0:
        return 0.0
    peak = ep
    last_new_high_bar = entry_idx
    n = len(c["close"])
    for j in range(entry_idx + 1, n):
        hi, lo, cl = c["high"][j], c["low"][j], c["close"][j]
        age = j - entry_idx
        if hi > peak:
            peak = hi
            last_new_high_bar = j
        pnl = (cl - ep) / ep * 100
        peak_pct = (peak - ep) / ep * 100
        no_new_high = j - last_new_high_bar
        if (lo - ep) / ep * 100 <= -SL_PCT:
            return -SL_PCT
        if (hi - ep) / ep * 100 >= tp_pct:
            return tp_pct
        if peak_pct >= base.TRAIL_ACTIVATE_PCT:
            if (peak - cl) / peak * 100 >= base.TRAIL_STOP_PCT:
                return pnl
        if age >= base.STALL_GREEN_AGE_BARS and pnl >= base.STALL_GREEN_MIN_PCT:
            return pnl
        if (
            age >= base.FLAT_STALL_AGE_BARS
            and base.FLAT_STALL_LO <= pnl <= base.FLAT_STALL_HI
            and no_new_high >= base.FLAT_STALL_NO_NEW_HIGH_BARS
        ):
            return pnl
        if age >= base.TIME_STOP_BARS:
            return pnl
    return (c["close"][-1] - ep) / ep * 100


def range_24h_pct(c: dict, i: int) -> float:
    lo = max(0, i - 287)
    hh = max(c["high"][lo : i + 1])
    ll = min(c["low"][lo : i + 1])
    return (hh - ll) / ll * 100.0 if ll > 0 else 0.0


def adx_at(c: dict, i: int) -> float | None:
    return c["adx"][i]


# ── Candidate w/ multi-TP outcomes ──────────────────────────────────
@dataclass
class TPCand:
    sym: str
    idx: int
    regime: str
    adx: float | None
    rng24: float
    proxy_conf: float
    chart_bullish: bool
    pnl: dict[float, float]  # tp_pct -> realized gross pnl%


def collect(data: dict[str, dict]) -> list[TPCand]:
    out: list[TPCand] = []
    for sym, c in data.items():
        n = len(c["close"])
        i = base.WARMUP
        while i < n:
            fires = base.breakout_fires(c, i) or base.volume_spike_fires(c, i)
            if fires and base.has_full_horizon(c, i):
                pnl = {tp: simulate_exit_tp(c, i, tp) for tp in TP_TARGETS}
                out.append(
                    TPCand(
                        sym=sym,
                        idx=i,
                        regime=base.regime_at(c, i),
                        adx=adx_at(c, i),
                        rng24=range_24h_pct(c, i),
                        proxy_conf=base.chart_confidence_proxy(c, i),
                        chart_bullish=base.chart_verdict_bullish(c, i),
                        pnl=pnl,
                    )
                )
                i += 6
            else:
                i += 1
    return out


# ── Stats helpers ───────────────────────────────────────────────────
def breakeven_winrate(tp_pct: float, fee_rt: float) -> float:
    """Win-rate p* such that EV=0 for a binary TP/SL outcome NET of fees.
    A win nets (tp - fee); a loss nets (-SL - fee). EV = p*(tp-fee) +
    (1-p)*(-SL-fee) = 0  =>  p* = (SL+fee) / (tp + SL)."""
    return (SL_PCT + fee_rt) / (tp_pct + SL_PCT)


def net_pnls(cands: list[TPCand], tp: float, fee_rt: float) -> list[float]:
    return [cand.pnl[tp] - fee_rt for cand in cands]


def won_at(cand: TPCand, tp: float) -> bool:
    return cand.pnl[tp] >= tp


def summarize(cands: list[TPCand], label: str) -> None:
    print(f"\n{'=' * 76}\n{label}  (N={len(cands)})\n{'=' * 76}")
    if not cands:
        print("  (no candidates in this cell — cannot conclude)")
        return
    # would-have-won + gross/net EV per TP
    print(
        f"  {'TP':>4} | {'wouldWin':>9} {'win 95%CI':>16} | "
        f"{'grossEV%':>9} | {'netEV%@.75':>11} {'netEV 95%CI':>18} | {'BEwin@.75':>9}"
    )
    for tp in TP_TARGETS:
        wins = [1.0 if won_at(cand, tp) else 0.0 for cand in cands]
        wr, wlo, whi = base.bootstrap_ci(wins)
        gross = [cand.pnl[tp] for cand in cands]
        gev, _, _ = base.bootstrap_ci(gross)
        net = net_pnls(cands, tp, FEE_RT_CENTRAL)
        nev, nlo, nhi = base.bootstrap_ci(net)
        be = breakeven_winrate(tp, FEE_RT_CENTRAL)
        wci = f"[{wlo * 100:.0f}%,{whi * 100:.0f}%]"
        nci = f"[{nlo:+.2f},{nhi:+.2f}]"
        print(
            f"  {tp:>4.0f} | {wr * 100:>7.1f}% {wci:>16} | "
            f"{gev:>+8.2f}% | {nev:>+10.2f}% {nci:>18} | {be * 100:>7.1f}%"
        )
    # realized win-rate vs break-even gap (the settle)
    print("\n  break-even win-rate by fee band (need realized >= this to be +EV):")
    print(f"    {'TP':>4} | {'fee0.5%':>9} {'fee0.75%':>9} {'fee1.0%':>9} | {'realizedWin':>11}")
    for tp in TP_TARGETS:
        wins = [1.0 if won_at(cand, tp) else 0.0 for cand in cands]
        realized = statistics.mean(wins)
        bes = " ".join(f"{breakeven_winrate(tp, f) * 100:>8.1f}%" for f in FEE_RT_BAND)
        print(f"    {tp:>4.0f} | {bes} | {realized * 100:>10.1f}%")


def regime_conditional_rule(cands: list[TPCand], fee_rt: float) -> None:
    """Apply the founder's proposed regime-conditional TP rule and compare its
    net EV to fixed-TP2 and fixed-TP4 over the SAME candidate set."""
    print(f"\n{'=' * 76}\nREGIME-CONDITIONAL TP RULE vs FIXED TP2 / FIXED TP4\n{'=' * 76}")
    print(
        f"  Rule: TP{RULE_HI_TP:.0f} when ADX>={RULE_ADX:.0f} AND 24h range>={RULE_RANGE_PCT:.0f}%, "
        f"else TP{RULE_LO_TP:.0f}.  fee_rt={fee_rt}% round-trip.\n"
    )
    rule_net, tp2_net, tp4_net = [], [], []
    n_hi = 0
    for cand in cands:
        use_hi = cand.adx is not None and cand.adx >= RULE_ADX and cand.rng24 >= RULE_RANGE_PCT
        if use_hi:
            n_hi += 1
        tp_rule = RULE_HI_TP if use_hi else RULE_LO_TP
        rule_net.append(cand.pnl[tp_rule] - fee_rt)
        tp2_net.append(cand.pnl[2.0] - fee_rt)
        tp4_net.append(cand.pnl[4.0] - fee_rt)
    for label, vals in [("regime-rule", rule_net), ("fixed TP2", tp2_net), ("fixed TP4", tp4_net)]:
        ev, lo, hi = base.bootstrap_ci(vals)
        print(f"  {label:>12}: netEV={ev:+.3f}%  95%CI=[{lo:+.3f},{hi:+.3f}]  (N={len(vals)})")
    print(
        f"\n  candidates routed to high-TP by the rule (ADX>={RULE_ADX:.0f} & range>={RULE_RANGE_PCT:.0f}%): "
        f"{n_hi}/{len(cands)}"
    )


def trend_floor_sweep(cands: list[TPCand]) -> None:
    """D1.a: in the TREND subset, is there ANY chart floor whose net-EV CI
    excludes zero, at the live TP2? Also report TP4 for contrast."""
    trend = [cand for cand in cands if cand.regime == "trend"]
    print(f"\n{'=' * 76}\nD1.a TREND-ONLY FLOOR SWEEP — net EV CI vs zero\n{'=' * 76}")
    print(f"  trend candidates: {len(trend)}  (chart_bullish-eligible only enter)\n")
    for tp in (2.0, 4.0):
        print(f"  --- TP{tp:.0f}, fee {FEE_RT_CENTRAL}% round-trip ---")
        print(f"    {'floor':>6} {'N':>4} | {'wouldWin':>9} | {'netEV%':>8} {'95% CI':>18} | excl0?")
        for floor in base.FLOOR_SWEEP:
            ent = [cand for cand in trend if cand.chart_bullish and cand.proxy_conf >= floor]
            n = len(ent)
            if n == 0:
                print(f"    {floor:>6.2f} {n:>4} |        — |       — {'—':>18} |   —")
                continue
            wins = [1.0 if won_at(cand, tp) else 0.0 for cand in ent]
            wr = statistics.mean(wins)
            net = net_pnls(ent, tp, FEE_RT_CENTRAL)
            ev, lo, hi = base.bootstrap_ci(net)
            excl = "YES" if (lo > 0 or hi < 0) else "no"
            print(
                f"    {floor:>6.2f} {n:>4} | {wr * 100:>7.0f}% | "
                f"{ev:>+7.2f}% [{lo:>+6.2f},{hi:>+6.2f}] |  {excl}"
            )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", help="load raw candles from JSON")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    if args.cached:
        with open(args.cached) as f:
            raw = json.load(f)
        print(f"Loaded cached candles from {args.cached}", file=sys.stderr)
    else:
        raw = base.fetch_candles()

    data = {sym: base.enrich(cs) for sym, cs in raw.items() if len(cs) >= 60}
    base.print_window_summary(data)
    cands = collect(data)

    print(f"\nTotal candidates (deterministic gate, full-horizon): {len(cands)}")
    by_reg: dict[str, list[TPCand]] = {}
    for cand in cands:
        by_reg.setdefault(cand.regime, []).append(cand)

    # D1.b — per regime, all TP targets
    summarize(cands, "ALL REGIMES — TP settlement")
    for rg in ("trend", "transitional", "chop"):
        summarize(by_reg.get(rg, []), f"REGIME = {rg.upper()} — TP settlement")

    # bullish-eligible entry set (what the bot would actually take), all regimes
    entered = [cand for cand in cands if cand.chart_bullish and cand.proxy_conf >= 0.85]
    summarize(entered, "LIVE ENTRY SET (chart_bullish & proxy>=0.85) — TP settlement")

    # D1.a — trend-only floor sweep, net EV vs zero
    trend_floor_sweep(cands)

    # regime-conditional rule comparison
    regime_conditional_rule(cands, FEE_RT_CENTRAL)

    if args.json_out:
        out = {
            "generated": "2026-05-22",
            "fee_band": FEE_RT_BAND,
            "fee_central": FEE_RT_CENTRAL,
            "tp_targets": TP_TARGETS,
            "sl_pct": SL_PCT,
            "n_candidates": len(cands),
            "by_regime_n": {rg: len(lst) for rg, lst in by_reg.items()},
            "breakeven_winrate": {
                str(tp): {str(f): breakeven_winrate(tp, f) for f in FEE_RT_BAND}
                for tp in TP_TARGETS
            },
            "regime_tp_settlement": {
                rg: {
                    str(tp): {
                        "would_win_rate": statistics.mean(
                            [1.0 if won_at(cand, tp) else 0.0 for cand in lst]
                        )
                        if lst
                        else None,
                        "net_ev_central": base.bootstrap_ci(net_pnls(lst, tp, FEE_RT_CENTRAL))
                        if lst
                        else None,
                    }
                    for tp in TP_TARGETS
                }
                for rg, lst in {**by_reg, "ALL": cands}.items()
            },
        }
        with open(args.json_out, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\nWrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
