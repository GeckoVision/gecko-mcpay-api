#!/usr/bin/env python3
"""Phase V.0 — the fee×gating direction-falsifier (quant-analyst, 2026-05-22).

THE QUESTION (the highest-value next measurement, per the fee/venue package
`docs/strategy/2026-05-22-fee-venue-decision.md`, committed 69325b8):

  The bot is a $0 PROOF ARTIFACT; the Oracle is the product. So the proof bar is
  NOT absolute PnL — it is the GATING DELTA:

      gating_delta = netEV(gating=on) − netEV(gating=off)

  Do the trades the gate LETS THROUGH outperform the trades it would have
  VETOED, with a clean CI? Two questions to settle for free, before any build:

    Q1. Does ANY reachable fee make a net-EV CI exclude zero on the +side, for
        either arm (on / off)? (If not even at 0% → the EDGE, not the venue, is
        the blocker; structure work is mandatory first.)
    Q2. Is the gating delta POSITIVE + CI-clean at break-even fee (~0.04–0.10%)?
        Does the gate ADD selection value, or — as the floor sweep + the −0.64%
        entry-gate hint — is it flat / anti-predictive on this window?
    Q3. If the gate doesn't discriminate: chop-window artifact (state the regime
        mix) or a real "the wedge needs work" signal?

WHAT THIS DOES (reuses the existing harness — does NOT rebuild)
  * exit_reconciliation.simulate_exit_real_close  — the bot's REAL close-based
    exit stack (the model that reconciles to the live N=7), per candidate.
  * exit_reconciliation.block_bootstrap_ci / variance_inflation — moving-block
    bootstrap (block=3, 5000 resamples, seed 1729), N_eff via Bartlett VIF.
  * chart_floor_calibration — candidate detection (breakout/volume-spike),
    chart_confidence_proxy, chart_verdict_bullish, regime_at, enrich.

  For each cached window:
    1. Generate breakout/volume-spike candidates (the deterministic gate), with
       the REAL-exit gross pnl% and the chart proxies attached.
    2. Split into two arms:
         gating=OFF = ALL candidates (no panel filter — the raw breakout tape).
         gating=ON  = candidates that pass the LOCAL ENTRY-GATE PROXY of the
                      live coordinator (coordinator_rules.coordinator):
                        proxy_conf >= 0.85 (the live _CHART_MIN_CONFIDENCE)
                        AND chart_bullish (live Rule 2: chart.verdict=="bullish")
                        AND direction-aware regime pass: the 5m regime is NOT
                            adverse — i.e. NOT (TREND-DOWN or CHOP). This mirrors
                            the live coordinator's effect: in an adverse regime
                            the chart floor is RAISED to 0.92, so a 0.885-proxy
                            candidate is DECLINED. Direction comes from +DI/-DI
                            (compute_regime_1h's exact up/down rule) computed on
                            the 5m series the proxy has (no 1h tape is cached).
    3. Cross fee ∈ {0.75, 0.50, 0.20, 0.10, 0.04, 0.0}% × gating ∈ {on, off}.
       Per cell: net-EV%, block-bootstrap 95% CI, payoff, N, N_eff, kept-count.
    4. HEADLINE: gating_delta = netEV(on) − netEV(off) with a block-bootstrap CI
       on the PAIRED pooled difference, at break-even fee (~0.04–0.10%). Because
       net-EV is gross − fee for BOTH arms, the delta is FEE-INVARIANT (the fee
       cancels) — but we report it at break-even to make the framing explicit and
       to show the absolute net level of each arm there.

HONEST CAVEATS (also printed + in the findings doc)
  * This is the LOCAL DETERMINISTIC GATE PROXY, NOT the live Gecko Oracle
    (gecko_trade_research). The Oracle can't be cheaply backtested on historical
    candles (it needs recorded verdicts). V.0 measures the LOCAL panel's
    discrimination as the replayable proxy; the Oracle's true gating delta is a
    separate, later eval.
  * One quiet chop-heavy week, two OVERLAPPING windows, small per-regime N_eff.
    Directional, not precise.

READ-ONLY w.r.t. the live bot (port 8265 — never touched). Free: cached candles.

Usage:
    python3 scripts/calibration/fee_sensitivity_gating_delta.py \
        --w1 /tmp/cal_candles_d1.json --w2 /tmp/cal_candles.json \
        --json-out /tmp/gating_delta.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics as st
import sys
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import chart_floor_calibration as cf  # noqa: E402  candidate detection + proxies
import exit_reconciliation as er  # noqa: E402  real-exit stack + block bootstrap

# Reuse the live indicators for the direction-aware (+DI/-DI) 5m regime — the
# exact rule from compute_regime_1h, applied to the 5m series we have cached.
import indicators as ind  # noqa: E402

# ── Sweep config ────────────────────────────────────────────────────
FEE_SWEEP = [0.75, 0.50, 0.20, 0.10, 0.04, 0.0]
# Break-even band: the fee where the central gross edge (≈+0.09–0.17%) nets ~0.
# The fee/venue doc pins it at ~0.04–0.10% (Jupiter RFQ ~0.04, the 0.10 step).
BREAKEVEN_FEE = 0.10  # the conservative break-even read used for the headline
BREAKEVEN_FEE_LOW = 0.04  # Jupiter RFQ — the optimistic break-even read

# Live gate constants (single source of truth = coordinator_rules.py; copied so
# this script never imports the live bot's main module).
LIVE_CHART_MIN_CONFIDENCE = 0.85  # _CHART_MIN_CONFIDENCE (2026-05-20)

N_BOOTSTRAP = er.N_BOOTSTRAP  # 5000
RNG_SEED = er.RNG_SEED  # 1729
BLOCK_LEN = er.BLOCK_LEN  # 3


# ── Direction-aware 5m regime (mirrors compute_regime_1h on the 5m tape) ──
def regime_directional_adverse(c: dict, i: int) -> bool:
    """True when the 5m regime at bar i is ADVERSE for a long entry — i.e.
    TREND-DOWN or CHOP under compute_regime_1h's classification rule, applied to
    the 5m series (no 1h tape is cached; the 5m series is the faithful proxy the
    data permits).

    compute_regime_1h rule (CODE, never in a prompt):
        ADX >= 25 AND +DI > -DI  → TREND-UP    (favorable)
        ADX >= 25 AND -DI > +DI  → TREND-DOWN  (ADVERSE)
        ADX <= 18 OR CHOP >= 61.8 → CHOP       (ADVERSE)
        else (transitional)       → CHOP       (ADVERSE, conservative default)

    We compute ADX/+DI/-DI/CHOP from the candles up to and including bar i using
    the SAME indicator functions the live bot uses. The window is the leading
    slice [0:i+1] so the read is point-in-time (no look-ahead)."""
    hi = c["high"][: i + 1]
    lo = c["low"][: i + 1]
    cl = c["close"][: i + 1]
    if len(cl) < 28:  # compute_regime_1h's warm-up guard → conservative CHOP
        return True
    adx_s, pdi_s, mdi_s = ind.adx_full(hi, lo, cl, 14)
    chop_s = ind.chop(hi, lo, cl, 14)

    def _last(series: list) -> float | None:
        return next((v for v in reversed(series) if v is not None), None)

    adx_v = _last(adx_s)
    pdi_v = _last(pdi_s)
    mdi_v = _last(mdi_s)
    chop_v = _last(chop_s)
    if adx_v is None:
        return True  # conservative
    if adx_v >= 25:
        if pdi_v is not None and mdi_v is not None:
            return mdi_v >= pdi_v  # TREND-DOWN is adverse; TREND-UP is not
        return False  # trending, direction indeterminate → mild favorable
    # ADX < 25
    if adx_v <= 18 or (chop_v is not None and chop_v >= 61.8):
        return True  # CHOP
    return True  # transitional → conservative CHOP (adverse), per the live rule


def regime_1h_label(c: dict, i: int) -> str:
    """The TREND-UP / TREND-DOWN / CHOP label (for the regime-mix report)."""
    hi, lo, cl = c["high"][: i + 1], c["low"][: i + 1], c["close"][: i + 1]
    if len(cl) < 28:
        return "CHOP"
    adx_s, pdi_s, mdi_s = ind.adx_full(hi, lo, cl, 14)
    chop_s = ind.chop(hi, lo, cl, 14)

    def _last(series: list) -> float | None:
        return next((v for v in reversed(series) if v is not None), None)

    adx_v, pdi_v, mdi_v, chop_v = (
        _last(adx_s),
        _last(pdi_s),
        _last(mdi_s),
        _last(chop_s),
    )
    if adx_v is None:
        return "CHOP"
    if adx_v >= 25:
        if pdi_v is not None and mdi_v is not None:
            return "TREND-UP" if pdi_v > mdi_v else "TREND-DOWN"
        return "TREND-UP"
    if adx_v <= 18 or (chop_v is not None and chop_v >= 61.8):
        return "CHOP"
    return "CHOP"


# ── Candidate (real-exit gross + the proxies the gate needs) ─────────
@dataclass
class GCand:
    sym: str
    idx: int
    pnl_real: float  # realized gross pnl%, REAL close-based exit stack
    proxy_conf: float
    chart_bullish: bool
    regime_5m: str  # ADX-based trend/chop/transitional (the base study's regime)
    regime_1h_dir: str  # TREND-UP/TREND-DOWN/CHOP (direction-aware)
    adverse: bool  # direction-aware adverse-regime flag (the live gate's effect)

    def passes_gate(self) -> bool:
        """The LOCAL entry-gate proxy of the live coordinator.

        Live coordinator (coordinator_rules.coordinator) for a long entry:
          Rule 2  : chart.verdict == "bullish"           → chart_bullish
          Rule 3  : chart.confidence >= floor, where floor is RAISED to 0.92 in
                    an adverse regime (1h TREND-DOWN/CHOP or 5m chop), else 0.85.
        We model the raised-floor effect directly: in an adverse regime the
        effective floor is 0.92 (which the 0.885-cap proxy can NEVER clear), so an
        adverse-regime candidate is DECLINED. In a favorable regime the floor is
        0.85.  (Risk veto + memory-contradict are LLM voices with no deterministic
        proxy; they only ever ADD declines, so omitting them makes gating=ON a
        STRICT SUPERSET of the live ON arm — a conservative, gate-friendly proxy.)
        """
        if not self.chart_bullish:
            return False
        if self.adverse:
            return self.proxy_conf >= cf.CHART_FLOOR_CHOP  # 0.92 — unreachable cap
        return self.proxy_conf >= LIVE_CHART_MIN_CONFIDENCE  # 0.85


def collect(data: dict[str, dict]) -> list[GCand]:
    """Time-ordered within each symbol (block bootstrap needs within-symbol order)."""
    out: list[GCand] = []
    for sym, c in data.items():
        n = len(c["close"])
        i = cf.WARMUP
        while i < n:
            if (cf.breakout_fires(c, i) or cf.volume_spike_fires(c, i)) and cf.has_full_horizon(
                c, i
            ):
                out.append(
                    GCand(
                        sym=sym,
                        idx=i,
                        pnl_real=er.simulate_exit_real_close(c, i),
                        proxy_conf=cf.chart_confidence_proxy(c, i),
                        chart_bullish=cf.chart_verdict_bullish(c, i),
                        regime_5m=cf.regime_at(c, i),
                        regime_1h_dir=regime_1h_label(c, i),
                        adverse=regime_directional_adverse(c, i),
                    )
                )
                i += 6
            else:
                i += 1
    return out


# ── Net-of-fee per-symbol ordered series for one arm ────────────────
def arm_series(cands: list[GCand], gating_on: bool, fee: float) -> list[list[float]]:
    """Per-symbol ordered list of (gross_real − fee) for the chosen arm."""
    by_sym: dict[str, list[float]] = {}
    for cand in cands:
        if gating_on and not cand.passes_gate():
            continue
        by_sym.setdefault(cand.sym, []).append(cand.pnl_real - fee)
    return list(by_sym.values())


def describe_arm(cands: list[GCand], gating_on: bool, fee: float) -> dict:
    series = arm_series(cands, gating_on, fee)
    flat = [v for s in series for v in s]
    if not flat:
        return {
            "n": 0,
            "n_eff": 0.0,
            "net_ev": float("nan"),
            "ci": (float("nan"),) * 2,
            "payoff": float("nan"),
            "excl0": False,
        }
    gross_series = [[v + fee for v in s] for s in series]  # gross for VIF
    vif = er.variance_inflation(gross_series)
    n = len(flat)
    pt, lo, hi = er.block_bootstrap_ci(series)
    wins = [x for x in flat if x > 0]
    losses = [x for x in flat if x < 0]
    payoff = (st.mean(wins) / abs(st.mean(losses))) if (wins and losses) else float("nan")
    return {
        "n": n,
        "n_eff": n / vif if vif else n,
        "net_ev": pt,
        "ci": (lo, hi),
        "payoff": payoff,
        "win_rate": len(wins) / n,
        "excl0": (lo > 0 or hi < 0),
    }


# ── Paired gating-delta bootstrap ───────────────────────────────────
def gating_delta_ci(cands: list[GCand], fee: float) -> dict:
    """Block-bootstrap CI on the PAIRED difference netEV(on) − netEV(off).

    The two arms are NOT independent samples: gating=ON ⊂ gating=OFF (the ON
    candidates are a subset of the OFF candidates). A naive two-sample compare
    would mishandle that overlap. The correct paired statistic resamples the
    UNDERLYING candidates ONCE per bootstrap iteration (moving blocks, within
    symbol), then recomputes BOTH arm means on the SAME resample and takes their
    difference — so the shared candidates move together and the dependence is
    preserved. The fee is a pure location shift that cancels in the difference,
    so delta is fee-invariant; we still pass `fee` for an explicit net level.

    Returns point delta + 95% CI + the two arm point net-EVs at this fee.
    """
    # per-symbol ordered (gross_real, passes_gate) tuples
    by_sym: dict[str, list[tuple[float, bool]]] = {}
    for cand in cands:
        by_sym.setdefault(cand.sym, []).append((cand.pnl_real, cand.passes_gate()))
    symbols = [s for s in by_sym.values() if s]

    def arm_means(resample: list[tuple[float, bool]]) -> tuple[float, float] | None:
        off = [g - fee for (g, _p) in resample]
        on = [g - fee for (g, p) in resample if p]
        if not off or not on:
            return None
        return st.mean(on), st.mean(off)

    flat_all = [t for s in symbols for t in s]
    on_pt = [g - fee for (g, p) in flat_all if p]
    off_pt = [g - fee for (g, _p) in flat_all]
    if not on_pt or not off_pt:
        return {
            "delta": float("nan"),
            "ci": (float("nan"),) * 2,
            "n_on": len(on_pt),
            "n_off": len(off_pt),
            "net_on": float("nan"),
            "net_off": float("nan"),
            "excl0": False,
        }
    point_delta = st.mean(on_pt) - st.mean(off_pt)

    rng = random.Random(RNG_SEED)
    total = sum(len(s) for s in symbols)
    weights = [len(s) for s in symbols]
    boots: list[float] = []
    for _ in range(N_BOOTSTRAP):
        sample: list[tuple[float, bool]] = []
        while len(sample) < total:
            s = rng.choices(symbols, weights=weights, k=1)[0]
            b = min(BLOCK_LEN, len(s))
            start = rng.randrange(0, len(s) - b + 1)
            sample.extend(s[start : start + b])
        sample = sample[:total]
        m = arm_means(sample)
        if m is None:
            continue
        boots.append(m[0] - m[1])
    boots.sort()
    lo = boots[int(0.025 * len(boots))]
    hi = boots[int(0.975 * len(boots))]
    return {
        "delta": point_delta,
        "ci": (lo, hi),
        "n_on": len(on_pt),
        "n_off": len(off_pt),
        "net_on": st.mean(on_pt),
        "net_off": st.mean(off_pt),
        "excl0": (lo > 0 or hi < 0),
    }


# ── Reporting ───────────────────────────────────────────────────────
def print_window_header(label: str, data: dict, cands: list[GCand]) -> None:
    print(f"\n{'#' * 100}")
    print(f"#  WINDOW {label}")
    print(f"{'#' * 100}")
    cf.print_window_summary(data)
    n_on = sum(1 for c in cands if c.passes_gate())
    print(
        f"\n  candidates: {len(cands)} total (gating=OFF) | {n_on} pass the gate (gating=ON) "
        f"| keep-rate {100 * n_on / len(cands) if cands else 0:.0f}%"
    )


def print_regime_mix(label: str, cands: list[GCand]) -> dict:
    """Direction-aware (1h-rule) regime mix of the candidate tape — answers Q3."""
    print(
        f"\n  --- regime mix (direction-aware, compute_regime_1h rule on 5m) — WINDOW {label} ---"
    )
    mix: dict[str, int] = {}
    mix_on: dict[str, int] = {}
    for c in cands:
        mix[c.regime_1h_dir] = mix.get(c.regime_1h_dir, 0) + 1
        if c.passes_gate():
            mix_on[c.regime_1h_dir] = mix_on.get(c.regime_1h_dir, 0) + 1
    for rg in ("TREND-UP", "TREND-DOWN", "CHOP"):
        tot = mix.get(rg, 0)
        on = mix_on.get(rg, 0)
        pct = 100 * tot / len(cands) if cands else 0
        print(f"    {rg:>11}: {tot:>3} candidates ({pct:>4.0f}%)  |  {on:>3} pass gate")
    # the base study's 5m ADX regime, for cross-reference
    mix5: dict[str, int] = {}
    for c in cands:
        mix5[c.regime_5m] = mix5.get(c.regime_5m, 0) + 1
    print(f"    [5m ADX regime cross-ref: {dict(sorted(mix5.items()))}]")
    return {"directional": mix, "directional_on": mix_on, "adx_5m": mix5}


def print_fee_gate_table(label: str, cands: list[GCand]) -> dict:
    print(
        f"\n  === FEE x GATING — net-EV%, block-bootstrap 95% CI (block={BLOCK_LEN}, "
        f"n_boot={N_BOOTSTRAP}, seed={RNG_SEED}) — WINDOW {label} ==="
    )
    hdr = (
        f"  {'fee%':>5} {'arm':>4} {'N':>4} {'Neff':>5} | "
        f"{'netEV%':>8} {'block 95% CI':>20} {'excl0':>6} {'payoff':>7}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    out: dict = {}
    for fee in FEE_SWEEP:
        out[f"{fee}"] = {}
        for gating_on, arm in ((False, "OFF"), (True, "ON")):
            d = describe_arm(cands, gating_on, fee)
            lo, hi = d["ci"]
            excl = "YES(+)" if (d["excl0"] and lo > 0) else ("YES(-)" if d["excl0"] else "no")
            print(
                f"  {fee:>5.2f} {arm:>4} {d['n']:>4} {d['n_eff']:>5.0f} | "
                f"{d['net_ev']:>+8.3f} [{lo:>+6.3f},{hi:>+6.3f}] {excl:>6} {d['payoff']:>7.2f}"
            )
            out[f"{fee}"][arm] = {
                "n": d["n"],
                "n_eff": d["n_eff"],
                "net_ev": d["net_ev"],
                "ci": [lo, hi],
                "excl_zero": d["excl0"],
                "excl_zero_positive": bool(d["excl0"] and lo > 0),
                "payoff": d["payoff"],
            }
        print("  " + "·" * (len(hdr) - 2))
    return out


def print_gating_delta(label: str, cands: list[GCand]) -> dict:
    print(
        f"\n  === GATING DELTA = netEV(ON) - netEV(OFF), paired block-bootstrap CI — WINDOW {label} ==="
    )
    print(
        "    (delta is fee-invariant — fee cancels in the difference — shown at each break-even read)"
    )
    out: dict = {}
    for fee in (BREAKEVEN_FEE_LOW, BREAKEVEN_FEE):
        g = gating_delta_ci(cands, fee)
        lo, hi = g["ci"]
        excl = "YES(+)" if (g["excl0"] and lo > 0) else ("YES(-)" if g["excl0"] else "no")
        print(
            f"    fee={fee:>4.2f}% | netEV(ON)={g['net_on']:>+7.3f}% (N={g['n_on']})  "
            f"netEV(OFF)={g['net_off']:>+7.3f}% (N={g['n_off']})  "
            f"| Δ={g['delta']:>+7.3f}%  95% CI [{lo:>+6.3f},{hi:>+6.3f}]  CI-clean: {excl}"
        )
        out[f"{fee}"] = {
            "delta": g["delta"],
            "ci": [lo, hi],
            "excl_zero": g["excl0"],
            "excl_zero_positive": bool(g["excl0"] and lo > 0),
            "net_on": g["net_on"],
            "net_off": g["net_off"],
            "n_on": g["n_on"],
            "n_off": g["n_off"],
        }
    return out


def answer_questions(label: str, fee_tbl: dict, delta: dict) -> dict:
    """Q1/Q2/Q3 verdicts, computed from the tables (no hand-waving)."""
    # Q1: any reachable fee where a net-EV CI excludes 0 on the +side, either arm?
    q1_hits = []
    for fee, arms in fee_tbl.items():
        for arm, cell in arms.items():
            if cell["excl_zero_positive"]:
                q1_hits.append((fee, arm, cell["net_ev"], cell["ci"]))
    q1 = bool(q1_hits)
    # Q2: gating delta positive + CI-clean at break-even fee?
    be = delta[f"{BREAKEVEN_FEE}"]
    q2_clean_pos = be["excl_zero_positive"]
    q2_point_pos = be["delta"] > 0
    print(f"\n  === ANSWERS — WINDOW {label} ===")
    print(
        f"    Q1 (any reachable fee → net-EV CI excludes 0 on +side, either arm): "
        f"{'YES' if q1 else 'NO'}"
    )
    if q1_hits:
        for fee, arm, ev, ci in q1_hits:
            print(f"        ↳ fee={fee}% arm={arm}: netEV={ev:+.3f}% CI[{ci[0]:+.3f},{ci[1]:+.3f}]")
    print(
        f"    Q2 (gating Δ positive + CI-clean at break-even fee {BREAKEVEN_FEE}%): "
        f"{'YES — gate adds CI-clean selection value' if q2_clean_pos else ('point-positive but CI straddles 0' if q2_point_pos else 'NO — Δ point ≤ 0 (flat / anti-predictive)')}"
    )
    print(f"        ↳ Δ={be['delta']:+.3f}%  CI[{be['ci'][0]:+.3f},{be['ci'][1]:+.3f}]")
    return {
        "q1_any_fee_positive_ci": q1,
        "q1_hits": [{"fee": f, "arm": a, "net_ev": e, "ci": c} for (f, a, e, c) in q1_hits],
        "q2_gating_delta_ci_clean_positive": q2_clean_pos,
        "q2_gating_delta_point_positive": q2_point_pos,
        "q2_breakeven_fee": BREAKEVEN_FEE,
        "q2_delta": be["delta"],
        "q2_ci": be["ci"],
    }


def run_window(label: str, raw: dict) -> dict:
    data = {sym: cf.enrich(cs) for sym, cs in raw.items() if len(cs) >= 60}
    cands = collect(data)
    print_window_header(label, data, cands)
    regime_mix = print_regime_mix(label, cands)
    fee_tbl = print_fee_gate_table(label, cands)
    delta = print_gating_delta(label, cands)
    answers = answer_questions(label, fee_tbl, delta)
    return {
        "n_candidates": len(cands),
        "n_pass_gate": sum(1 for c in cands if c.passes_gate()),
        "regime_mix": regime_mix,
        "fee_gating_table": fee_tbl,
        "gating_delta": delta,
        "answers": answers,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w1", default="/tmp/cal_candles_d1.json", help="window 1 cached candles")
    ap.add_argument("--w2", default="/tmp/cal_candles.json", help="window 2 cached candles")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    print("=" * 100)
    print("PHASE V.0 — FEE x GATING DIRECTION-FALSIFIER  (LOCAL deterministic gate proxy)")
    print("=" * 100)
    print(
        "CAVEAT: this is the LOCAL panel proxy, NOT the live Gecko Oracle (gecko_trade_research)."
    )
    print(
        "        The Oracle's true gating delta is a separate, later eval (needs recorded verdicts)."
    )
    print(
        f"        Fee sweep: {FEE_SWEEP}  | break-even reads: {BREAKEVEN_FEE_LOW}% (RFQ), {BREAKEVEN_FEE}%"
    )

    results: dict = {
        "generated": "2026-05-22",
        "phase": "V.0 — fee x gating direction-falsifier",
        "caveat": "LOCAL deterministic gate proxy, NOT the live Gecko Oracle. "
        "One quiet chop-heavy week, two overlapping windows, small per-regime N_eff. "
        "Directional, not precise.",
        "fee_sweep": FEE_SWEEP,
        "breakeven_fee": BREAKEVEN_FEE,
        "breakeven_fee_low": BREAKEVEN_FEE_LOW,
        "block_len": BLOCK_LEN,
        "n_bootstrap": N_BOOTSTRAP,
        "rng_seed": RNG_SEED,
        "gate_proxy": {
            "chart_min_confidence": LIVE_CHART_MIN_CONFIDENCE,
            "adverse_regime_floor": cf.CHART_FLOOR_CHOP,
            "rule": "chart_bullish AND proxy_conf>=0.85 (favorable) / >=0.92 (adverse=TREND-DOWN|CHOP)",
        },
        "windows": {},
    }
    for label, path in (("W1", args.w1), ("W2", args.w2)):
        with open(path) as f:
            raw = json.load(f)
        print(f"\nLoaded {label} from {path}", file=sys.stderr)
        results["windows"][label] = run_window(label, raw)

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nWrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
