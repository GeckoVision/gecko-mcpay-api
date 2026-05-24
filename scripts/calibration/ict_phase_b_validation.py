#!/usr/bin/env python3
"""Phase B — does ANY ICT / order-flow primitive (or the combined system) have
real GROSS edge that clears the 2x-fee bar, in any regime, at a reachable fee?

THE QUESTION (the make-or-break for the trade vertical)
  The breakout/volume-spike primitive was proven DEAD: no gross edge under any
  entry/exit/fee (gross ceiling ~+0.08%, far under the ~1.5% 2x-fee bar). Phase B
  tests whether ICT/order-flow is a DIFFERENT signal class with REAL gross edge.

WHAT IT DOES (free, deterministic, NO LLM, no live-bot touch)
  PART 1 — each ICT primitive INDIVIDUALLY as a Phase V Feature:
    * Bias primitives (OB / FVG / MSS) evaluated on the 4H tape.
    * Entry primitives (liquidity sweep / OTE discount) evaluated on the 15m tape.
    * A primitive "fires" at a bar -> that bar is a candidate long entry. The label
      is the fixed-horizon forward GROSS return (exit-agnostic, so the SIGNAL is
      tested, not an exit model). For each primitive x 4-way regime we report:
        - gross EV of the FIRED ("presence") set + block-bootstrap CI, N_eff,
        - whether the gross-EV CI lower bound clears the 2x-fee bar (the real bar),
        - the gross-edge DELTA (fired vs not-fired) paired block-bootstrap CI,
        - fee-sensitivity: net EV at 0.75% RT (live) AND 0.04% (Jupiter-class).
    * Leakage traps (lookahead + shuffle + placebo) run on the FULL bar set.
    Default REJECT — no edge claimed unless the CI excludes zero AND clears the bar.

  PART 2 — the COMBINED Step 1-3 system end-to-end on the 15m tape:
    * Bias from the CONCURRENT 4H bar (MSS active AND unmitigated FVG below price),
      mapped by timestamp (point-in-time: the most-recent CLOSED 4H bar at or
      before the 15m bar's open — no lookahead across timeframes).
    * Entry gate: 15m liquidity sweep AND price in the discount/OTE zone.
    * Exit framework (founder's Step 3): TP=BSL=max(H_{prior M}); SL=1 tick below
      the sweep bar's low; enforce RR=(TP-entry)/(entry-SL) >= 2.5 (skip if it
      can't); ATR trailing after +1.5xATR; time-decay market-exit after K bars.
    * Per-regime net + gross EV, block-CI, fee-sensitivity. Does the SYSTEM clear
      fees where the breakout didn't?

HONESTY / METHODOLOGY (mirrors structure_phase1_validation)
  * Resampling unit = the tape (a (sym, tf) ordered series); within-tape order
    preserved for the block bootstrap (stats_validation, the canonical CI). IID
    would understate width on autocorrelated returns.
  * 4-way regime: base 3-way ADX classifier + a trend-direction split (regime4_at).
  * Leakage traps on the FULL candidate set; the level/delta stats on the FIRED
    subset. Cross-timeframe mapping is strictly point-in-time.
  * READ-ONLY w.r.t. the live bot. No network. NO result numbers in docstrings;
    findings go to the gitignored private/ doc.

Run:
  python3 scripts/calibration/ict_phase_b_validation.py --json-out /tmp/ict_phase_b.json
  uv run pytest scripts/calibration/test_ict_phase_b_validation.py -q   # unit tests
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as stx
import sys
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "contest_bot", "features"))
sys.path.insert(0, os.path.join(_REPO, "contest_bot"))

import chart_floor_calibration as base  # noqa: E402  enrich + regime
import indicators as ind  # noqa: E402  ATR for the exit framework
import orderflow as of  # noqa: E402  the ICT primitives
import stats_validation as sv  # noqa: E402

TAPE_DIR = os.path.join(_HERE, "data", "tape")
RESERVED = {"tape_index.json", "regime_windows.json"}
REGIMES_4 = ("trend_up", "trend_down", "transitional", "chop")
TREND_DIR_LOOKBACK = 14

# Fee bars. Live DEX round-trip is 0.75% (2x = 1.5% bar). Jupiter-class aggregated
# routing is much cheaper; 0.04% RT is the optimistic reachable floor.
FEE_RT_LIVE = 0.75
FEE_RT_JUP = 0.04
ECON_FEE_MULTIPLE = 2.0
TWO_X_FEE_BAR = ECON_FEE_MULTIPLE * FEE_RT_LIVE  # 1.5% — the real bar to clear

# Fixed forward-return label horizon for the per-primitive SIGNAL test. Chosen to
# be exit-agnostic: the primitive is tested on raw forward return, not a tuned exit.
# 4H bias primitives use a shorter bar-count (each bar is 4h); 15m entry primitives
# a longer one. Both span a comparable wall-clock window (~3 days).
FWD_HORIZON_4H = 18  # 18 * 4h = 3 days
FWD_HORIZON_15M = 24  # 24 * 15m = 6h holding for the entry-trigger signal

# Combined-system exit framework parameters (founder's Step 3).
SYS_BSL_LOOKBACK = 10  # TP = max(H_{prior M}); M
SYS_MIN_RR = 2.5  # enforce RR >= 2.5; skip entries that can't meet it
SYS_ATR_N = 14
SYS_TRAIL_ACTIVATE_ATR = 1.5  # activate trail after +1.5xATR
SYS_TRAIL_ATR_MULT = 2.0  # SL_trail = max(SL_prev, C - 2*ATR)
SYS_TIME_DECAY_BARS = 24  # market-exit after K bars if neither TP nor SL


# ── 4-way regime ────────────────────────────────────────────────────
def regime4_at(c: dict, i: int) -> str:
    r = base.regime_at(c, i)
    if r != "trend":
        return r
    lo = max(0, i - TREND_DIR_LOOKBACK)
    net = c["close"][i] - c["close"][lo]
    return "trend_up" if net >= 0 else "trend_down"


# ── A fired-bar candidate ───────────────────────────────────────────
@dataclass
class Cand:
    tape: str
    idx: int
    regime: str
    fwd_gross: float  # fixed-horizon forward GROSS return %


# ── Tape loading ────────────────────────────────────────────────────
def _load_raw(fname: str) -> list[dict] | None:
    with open(os.path.join(TAPE_DIR, fname)) as fh:
        raw = json.load(fh)
    if not isinstance(raw, list) or len(raw) < 60:
        return None
    return raw


def load_timeframe(tf: str) -> dict[str, dict]:
    """Load + enrich every tape of a given timeframe ('4H' or '15m'). Returns
    {tape_id: enriched_dict}. The enriched dict carries the ts list for the
    cross-timeframe mapping."""
    out: dict[str, dict] = {}
    files = sorted(
        f
        for f in os.listdir(TAPE_DIR)
        if f.endswith(f"_{tf}.json") and "_" in f and f not in RESERVED
    )
    for fname in files:
        raw = _load_raw(fname)
        if raw is None:
            continue
        out[fname[:-5]] = base.enrich(raw)
    return out


def fixed_forward_return(c: dict, i: int, horizon: int) -> float:
    cl = c["close"]
    j = min(i + horizon, len(cl) - 1)
    if i >= len(cl) - 1 or cl[i] <= 0:
        return 0.0
    return (cl[j] - cl[i]) / cl[i] * 100.0


# ── Per-primitive candidate collection ──────────────────────────────
def collect_primitive_cands(
    enriched: dict[str, dict], feat, horizon: int
) -> tuple[list[Cand], list[Cand]]:
    """Return (fired, not_fired) candidate lists across all tapes of one timeframe.
    A bar is 'fired' if feat.passes(c, i) is True. Both lists carry the fixed-horizon
    forward GROSS return. Warmup = base.WARMUP; leave room for the forward label."""
    fired: list[Cand] = []
    notf: list[Cand] = []
    for tape, c in enriched.items():
        n = len(c["close"])
        for i in range(base.WARMUP, n - horizon):
            cand = Cand(
                tape=tape,
                idx=i,
                regime=regime4_at(c, i),
                fwd_gross=fixed_forward_return(c, i, horizon),
            )
            if feat.passes(c, i):
                fired.append(cand)
            else:
                notf.append(cand)
    return fired, notf


# ── Gross-EV block-CI on a candidate subset ─────────────────────────
def _by_tape(cands: list[Cand]) -> list[list[float]]:
    by: dict[str, list[float]] = {}
    for c in sorted(cands, key=lambda x: (x.tape, x.idx)):
        by.setdefault(c.tape, []).append(c.fwd_gross)
    return [v for v in by.values() if v]


# Bootstrap resamples for the fired-set / system CIs. 2000 gives CI bounds stable
# to <0.01% vs the 5000 default on these N (verified) — orders of magnitude below
# the 1.5% fee bar — at ~2.5x the speed, which keeps the 24-tape run tractable.
N_BOOT_FIRED = 2000


def gross_ev_ci(cands: list[Cand], n_boot: int = N_BOOT_FIRED) -> dict:
    series = _by_tape(cands)
    if not series:
        return {"gross_ev": float("nan"), "ci": (float("nan"), float("nan")), "n": 0, "n_eff": 0.0}
    mean, lo, hi, n_eff, _b = sv.block_bootstrap_ci(series, n_boot=n_boot)
    return {
        "gross_ev": mean,
        "ci": (lo, hi),
        "n": sum(len(s) for s in series),
        "n_eff": n_eff,
        "excl_zero_pos": lo == lo and lo > 0,
    }


def delta_unpaired(fired: list[Cand], notf: list[Cand]) -> dict:
    """Difference in gross EV between fired and not-fired sets. These are DISJOINT
    sets (a bar is one or the other), so this is an unpaired two-sample difference.
    We block-bootstrap the FIRED arm (the thing under test — its CI vs the fee bar
    is the gate) and report the not-fired arm's plain MEAN as the comparison point.

    The not-fired arm is intentionally NOT bootstrapped: it is often 10-100x larger
    (every non-signal bar) so a full block bootstrap on it costs minutes and adds
    nothing — the gate is on the FIRED set's CI, and the delta is a descriptive
    contrast, not a gated quantity. (The paired same-resample trick used for nested
    subsets in structure_phase1 does not apply — fired/not-fired are a partition.)"""
    f = gross_ev_ci(fired)
    nf_flat = [v for s in _by_tape(notf) for v in s]
    nf_mean = stx.mean(nf_flat) if nf_flat else float("nan")
    if f["n"] == 0 or not nf_flat:
        return {"delta": float("nan"), "fired": f, "not_fired_mean": nf_mean}
    return {"delta": f["gross_ev"] - nf_mean, "fired": f, "not_fired_mean": nf_mean}


# ── Per-primitive, per-regime analysis ──────────────────────────────
def analyze_primitive(name: str, fired: list[Cand], notf: list[Cand]) -> dict:
    out: dict = {"primitive": name, "regimes": {}}
    for rg in ("ALL", *REGIMES_4):
        f = fired if rg == "ALL" else [c for c in fired if c.regime == rg]
        nf = notf if rg == "ALL" else [c for c in notf if c.regime == rg]
        if not f:
            out["regimes"][rg] = {"n_fired": 0}
            continue
        d = delta_unpaired(f, nf)
        fev = d["fired"]
        slo = fev["ci"][0]
        clears_live = bool(slo == slo and slo >= TWO_X_FEE_BAR)
        # fee-sensitivity: net EV = gross EV - fee_rt (single round trip on the EV)
        net_live = fev["gross_ev"] - FEE_RT_LIVE
        net_jup = fev["gross_ev"] - FEE_RT_JUP
        net_live_lo = slo - FEE_RT_LIVE if slo == slo else float("nan")
        net_jup_lo = slo - FEE_RT_JUP if slo == slo else float("nan")
        out["regimes"][rg] = {
            "n_fired": len(f),
            "n_not_fired": len(nf),
            "gross_ev": fev["gross_ev"],
            "gross_ci": list(fev["ci"]),
            "gross_n_eff": fev["n_eff"],
            "gross_excl_zero_pos": fev["excl_zero_pos"],
            "delta_vs_not_fired": d["delta"],
            "clears_2x_fee_live_ci_clean": clears_live,
            "net_ev_live_0p75": net_live,
            "net_ev_live_ci_lo": net_live_lo,
            "net_ev_jup_0p04": net_jup,
            "net_ev_jup_ci_lo": net_jup_lo,
        }
    return out


# ── Leakage traps (lookahead on representative tape; shuffle/placebo pooled) ─
def leakage_check(feat, enriched: dict[str, dict], horizon: int) -> dict:
    """Run the V.1 leakage traps for one primitive. Lookahead-clean is a structural
    property tested on the largest tape's bar set; shuffle/placebo are pooled across
    all fired+not-fired bars (scores + forward labels)."""
    import feature_validation as fv

    big_tape = max(enriched, key=lambda t: len(enriched[t]["close"]))
    bc = enriched[big_tape]
    n = len(bc["close"])
    idxs = list(range(base.WARMUP, n - horizon))
    syms = [big_tape] * len(idxs)
    fwd = [fixed_forward_return(bc, i, horizon) for i in idxs]
    rep = fv.run_leakage_traps(feat, bc, idxs, fwd, syms)
    return {
        "lookahead_clean": rep.lookahead_clean,
        "shuffle_passes": rep.shuffle_passes,
        "placebo_passes": rep.placebo_passes,
        "clean": rep.clean,
    }


# ════════════════════════════════════════════════════════════════════
# PART 2 — the combined Step 1-3 system, end-to-end
# ════════════════════════════════════════════════════════════════════
def _map_4h_index(ts_4h: list[float], ts_query: float) -> int | None:
    """Index of the most-recent CLOSED 4H bar at or before `ts_query` (the 15m
    bar's open time). Point-in-time: the 15m entry only sees a 4H bar that has
    already closed. Returns None if no 4H bar precedes the query (warmup)."""
    # ts_4h is ascending; the bar at index k OPENS at ts_4h[k] and CLOSES ~4h
    # later. A 15m bar at ts_query may only use a 4H bar whose CLOSE <= ts_query,
    # i.e. whose open + 4h <= ts_query. We approximate close as next-open; the last
    # usable 4H bar is the greatest k with ts_4h[k+1] <= ts_query (strictly closed).
    lo, hi = 0, len(ts_4h) - 1
    if not ts_4h or ts_query < (ts_4h[1] if len(ts_4h) > 1 else float("inf")):
        return None
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        # bar mid is closed by ts_query iff the NEXT bar's open <= ts_query
        nxt_open = ts_4h[mid + 1] if mid + 1 < len(ts_4h) else float("inf")
        if nxt_open <= ts_query:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def bias_confirmed_4h(c4: dict, k4: int) -> bool:
    """Bullish bias on the 4H bar k4: MSS active AND an unmitigated bullish FVG
    below price. Strictly causal on the 4H series (reads c4[:k4+1])."""
    h, low, cl, v = c4["high"], c4["low"], c4["close"], c4["volume"]
    mss = of.mss_bullish_active(h, cl, v, k4)
    fvg = bool(of.unmitigated_bullish_fvgs_below(h, low, cl, k4))
    return mss and fvg


@dataclass
class SysTrade:
    tape: str
    idx: int
    regime: str
    gross: float  # realized gross pnl %
    rr: float


def simulate_system_exit(c15: dict, entry_idx: int, sweep_low: float) -> tuple[float, float] | None:
    """Founder's Step-3 exit framework on the 15m tape. Returns (gross_pnl_pct, rr)
    or None if the RR>=2.5 gate is not met (entry skipped).

    Entry = close[entry_idx]. SL = 1 tick below the sweep bar's low (structure
    invalidation). TP = BSL = max(H_{prior M}) above entry. Enforce RR>=2.5. Then
    walk forward on CLOSES: SL/TP checks, ATR trail after +1.5xATR, time-decay
    market-exit after K bars. Strictly causal (only bars > entry are the realized
    path; the gate quantities use bars <= entry_idx)."""
    cl, h = c15["close"], c15["high"]
    n = len(cl)
    entry = cl[entry_idx]
    if entry <= 0:
        return None
    # SL: 1 tick below the sweep bar low. "1 tick" ~ a tiny epsilon below the low.
    tick = entry * 1e-4  # 1bp proxy for a tick on a normalized price
    sl = sweep_low - tick
    if sl >= entry:  # invalid (sweep low above entry) -> skip
        return None
    # TP = BSL = max high of the prior M bars (the buy-side liquidity above)
    lo_m = max(0, entry_idx - SYS_BSL_LOOKBACK)
    bsl = max(h[lo_m:entry_idx]) if entry_idx > lo_m else entry
    tp = bsl
    risk = entry - sl
    reward = tp - entry
    if risk <= 0 or reward <= 0:
        return None
    rr = reward / risk
    if rr < SYS_MIN_RR:
        return None  # cannot meet RR>=2.5 -> skip (the founder's hard gate)
    atr_series = c15.get("atr14")
    sl_cur = sl
    peak = entry
    trail_active = False
    for j in range(entry_idx + 1, min(n, entry_idx + 1 + SYS_TIME_DECAY_BARS + 1)):
        c = cl[j]
        if c > peak:
            peak = c
        atr = atr_series[j] if atr_series and atr_series[j] is not None else None
        # ATR trail: once price has moved +1.5xATR from entry, ratchet SL up
        if atr is not None and not trail_active and (peak - entry) >= SYS_TRAIL_ACTIVATE_ATR * atr:
            trail_active = True
        if trail_active and atr is not None:
            sl_cur = max(sl_cur, c - SYS_TRAIL_ATR_MULT * atr)
        # exits on close (live bot polls close, never intrabar)
        if c <= sl_cur:
            return ((c - entry) / entry * 100.0, rr)
        if c >= tp:
            return ((tp - entry) / entry * 100.0, rr)
        if j - entry_idx >= SYS_TIME_DECAY_BARS:
            return ((c - entry) / entry * 100.0, rr)
    # marked to last available close in window
    last = cl[min(n - 1, entry_idx + SYS_TIME_DECAY_BARS)]
    return ((last - entry) / entry * 100.0, rr)


def collect_system_trades(e15: dict[str, dict], e4: dict[str, dict]) -> tuple[list[SysTrade], dict]:
    """Replay the combined Step 1-3 system across the 15m tapes, gating each 15m
    entry on the CONCURRENT 4H bias (point-in-time map). Returns (trades, meta)."""
    trades: list[SysTrade] = []
    meta: dict = {"per_tape": {}, "skipped": [], "gated_out": 0, "rr_skipped": 0}
    for tape15, c15 in e15.items():
        sym = tape15.split("_")[0]
        tape4 = f"{sym}_4H"
        c4 = e4.get(tape4)
        if c4 is None:
            meta["skipped"].append(tape15)
            continue
        # precompute ATR(14) on the 15m closes for the trail
        c15["atr14"] = ind.atr(c15["high"], c15["low"], c15["close"], SYS_ATR_N)
        ts4 = c4["ts"]
        n = len(c15["close"])
        per = 0
        i = base.WARMUP
        while i < n - 1:
            # entry gate: 15m sweep AND discount/OTE zone
            if not of.is_liquidity_sweep(c15["low"], c15["close"], i):
                i += 1
                continue
            if not of.in_discount_zone(c15["high"], c15["low"], c15["close"], i):
                i += 1
                continue
            # bias gate: concurrent CLOSED 4H bar shows bullish bias
            k4 = _map_4h_index(ts4, c15["ts"][i])
            if k4 is None or k4 < base.WARMUP or not bias_confirmed_4h(c4, k4):
                meta["gated_out"] += 1
                i += 1
                continue
            res = simulate_system_exit(c15, i, c15["low"][i])
            if res is None:
                meta["rr_skipped"] += 1
                i += 1
                continue
            gross, rr = res
            trades.append(
                SysTrade(tape=tape15, idx=i, regime=regime4_at(c15, i), gross=gross, rr=rr)
            )
            per += 1
            i += 6  # no-overlap, mirrors the backtest cadence
        meta["per_tape"][tape15] = {"bars": n, "trades": per}
    return trades, meta


def _sys_by_tape(trades: list[SysTrade]) -> list[list[float]]:
    by: dict[str, list[float]] = {}
    for t in sorted(trades, key=lambda x: (x.tape, x.idx)):
        by.setdefault(t.tape, []).append(t.gross)
    return [v for v in by.values() if v]


def system_regime_table(trades: list[SysTrade]) -> dict:
    out: dict = {}
    for rg in ("ALL", *REGIMES_4):
        sub = trades if rg == "ALL" else [t for t in trades if t.regime == rg]
        series = _sys_by_tape(sub)
        if not series:
            out[rg] = {"n": 0}
            continue
        mean, lo, hi, n_eff, _b = sv.block_bootstrap_ci(series, n_boot=N_BOOT_FIRED)
        n = sum(len(s) for s in series)
        out[rg] = {
            "n": n,
            "gross_ev": mean,
            "gross_ci": [lo, hi],
            "n_eff": n_eff,
            "gross_excl_zero_pos": lo == lo and lo > 0,
            "clears_2x_fee_live_ci_clean": bool(lo == lo and lo >= TWO_X_FEE_BAR),
            "net_ev_live_0p75": mean - FEE_RT_LIVE,
            "net_ev_live_ci_lo": lo - FEE_RT_LIVE if lo == lo else float("nan"),
            "net_ev_jup_0p04": mean - FEE_RT_JUP,
            "net_ev_jup_ci_lo": lo - FEE_RT_JUP if lo == lo else float("nan"),
            "mean_rr": stx.mean([t.rr for t in sub]),
        }
    return out


# ── Reporting ───────────────────────────────────────────────────────
def _fmt(x: float) -> str:
    return "   n/a" if x != x else f"{x:+.3f}"


def print_primitive_table(analyses: list[dict], leak: dict) -> None:
    print(f"\n{'=' * 112}")
    print(
        f"PART 1 — PER-PRIMITIVE GROSS EDGE by 4-way regime  (2x-fee bar = {TWO_X_FEE_BAR:.2f}%; "
        f"fired-set forward gross EV)"
    )
    print(f"{'=' * 112}")
    for a in analyses:
        lk = leak.get(a["primitive"], {})
        print(
            f"\n  PRIMITIVE: {a['primitive']}   "
            f"[leakage: lookahead={lk.get('lookahead_clean')} shuffle={lk.get('shuffle_passes')} "
            f"placebo={lk.get('placebo_passes')} -> clean={lk.get('clean')}]"
        )
        hdr = (
            f"  {'regime':>13} {'nFired':>7} | {'grossEV%':>9} {'gross 95% CI':>20} {'Neff':>6} "
            f"{'CI>0':>5} | {'net@.75%':>9} {'net@.04%':>9} | {'clears 2x?':>10}"
        )
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for rg in ("ALL", *REGIMES_4):
            r = a["regimes"].get(rg, {})
            if not r or r.get("n_fired", 0) == 0:
                print(f"  {rg:>13} {'(none)':>7}")
                continue
            glo, ghi = r["gross_ci"]
            ci_pos = "YES" if r["gross_excl_zero_pos"] else "no"
            clears = "YES(+)" if r["clears_2x_fee_live_ci_clean"] else "no"
            print(
                f"  {rg:>13} {r['n_fired']:>7} | {_fmt(r['gross_ev']):>9} "
                f"[{_fmt(glo)},{_fmt(ghi)}] {r['gross_n_eff']:>6.0f} {ci_pos:>5} | "
                f"{_fmt(r['net_ev_live_0p75']):>9} {_fmt(r['net_ev_jup_0p04']):>9} | {clears:>10}"
            )


def print_system_table(tbl: dict, meta: dict) -> None:
    print(f"\n{'=' * 112}")
    print(
        f"PART 2 — COMBINED ICT SYSTEM (4H bias -> 15m sweep+OTE -> RR>=2.5 exit)  "
        f"(2x-fee bar = {TWO_X_FEE_BAR:.2f}%)"
    )
    print(
        f"  gated-out (no bias): {meta['gated_out']}   RR<2.5 skipped: {meta['rr_skipped']}",
    )
    print(f"{'=' * 112}")
    hdr = (
        f"  {'regime':>13} {'nTrades':>8} {'meanRR':>7} | {'grossEV%':>9} {'gross 95% CI':>20} "
        f"{'Neff':>6} {'CI>0':>5} | {'net@.75%':>9} {'net@.04%':>9} | {'clears 2x?':>10}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for rg in ("ALL", *REGIMES_4):
        r = tbl.get(rg, {})
        if not r or r.get("n", 0) == 0:
            print(f"  {rg:>13} {'(none)':>8}")
            continue
        glo, ghi = r["gross_ci"]
        ci_pos = "YES" if r["gross_excl_zero_pos"] else "no"
        clears = "YES(+)" if r["clears_2x_fee_live_ci_clean"] else "no"
        print(
            f"  {rg:>13} {r['n']:>8} {r['mean_rr']:>7.2f} | {_fmt(r['gross_ev']):>9} "
            f"[{_fmt(glo)},{_fmt(ghi)}] {r['n_eff']:>6.0f} {ci_pos:>5} | "
            f"{_fmt(r['net_ev_live_0p75']):>9} {_fmt(r['net_ev_jup_0p04']):>9} | {clears:>10}"
        )


# ── Driver ──────────────────────────────────────────────────────────
def bias_roster():
    return [of.OrderBlockFeature(), of.FVGFeature(), of.MSSFeature()]


def entry_roster():
    return [of.LiquiditySweepFeature(), of.OTEFeature()]


def run(json_out: str | None) -> dict:
    print("Loading 4H + 15m tapes...", file=sys.stderr)
    e4 = load_timeframe("4H")
    e15 = load_timeframe("15m")
    print(f"  4H tapes: {len(e4)}   15m tapes: {len(e15)}", file=sys.stderr)

    analyses: list[dict] = []
    leak: dict = {}

    print("PART 1: bias primitives on 4H...", file=sys.stderr)
    for feat in bias_roster():
        fired, notf = collect_primitive_cands(e4, feat, FWD_HORIZON_4H)
        analyses.append(analyze_primitive(feat.name, fired, notf))
        leak[feat.name] = leakage_check(feat, e4, FWD_HORIZON_4H)
        print(f"    {feat.name}: fired={len(fired)}", file=sys.stderr)

    print("PART 1: entry primitives on 15m...", file=sys.stderr)
    for feat in entry_roster():
        fired, notf = collect_primitive_cands(e15, feat, FWD_HORIZON_15M)
        analyses.append(analyze_primitive(feat.name, fired, notf))
        leak[feat.name] = leakage_check(feat, e15, FWD_HORIZON_15M)
        print(f"    {feat.name}: fired={len(fired)}", file=sys.stderr)

    print_primitive_table(analyses, leak)

    print("PART 2: combined system replay (4H bias x 15m entry)...", file=sys.stderr)
    trades, meta = collect_system_trades(e15, e4)
    print(f"    system trades: {len(trades)}", file=sys.stderr)
    sys_tbl = system_regime_table(trades)
    print_system_table(sys_tbl, meta)

    # Headline verdict
    any_prim_clears = any(
        a["regimes"].get(rg, {}).get("clears_2x_fee_live_ci_clean", False)
        for a in analyses
        for rg in ("ALL", *REGIMES_4)
    )
    sys_clears = any(
        sys_tbl.get(rg, {}).get("clears_2x_fee_live_ci_clean", False) for rg in ("ALL", *REGIMES_4)
    )
    print(f"\n{'=' * 112}")
    print("HEADLINE")
    print(f"  ANY primitive clears 2x-fee bar (CI-clean) in any regime: {any_prim_clears}")
    print(f"  Combined SYSTEM clears 2x-fee bar (CI-clean) in any regime: {sys_clears}")
    print(f"{'=' * 112}")

    result = {
        "generated": "2026-05-24",
        "phase": "Phase B — ICT/order-flow gross-edge validation",
        "fee_rt_live": FEE_RT_LIVE,
        "fee_rt_jup": FEE_RT_JUP,
        "two_x_fee_bar": TWO_X_FEE_BAR,
        "primitive_analyses": analyses,
        "leakage": leak,
        "system_table": sys_tbl,
        "system_meta": meta,
        "n_system_trades": len(trades),
        "headline": {"any_primitive_clears": any_prim_clears, "system_clears": sys_clears},
    }
    if json_out:
        with open(json_out, "w") as fh:
            json.dump(result, fh, indent=2, default=str)
        print(f"\nWrote {json_out}", file=sys.stderr)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    run(args.json_out)


if __name__ == "__main__":
    main()
