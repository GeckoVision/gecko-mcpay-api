#!/usr/bin/env python3
"""Phase 1 de-risk — the STRUCTURE-feature gating-delta falsifier (quant-analyst, 2026-05-22).

THE QUESTION (the $0 de-risk before building Phase 1)
  V.0 (`docs/strategy/2026-05-22-gating-delta.md`) proved the bot's LOCAL gate —
  the chart_analyst momentum-confidence ladder + regime + floor — is
  ANTI-PREDICTIVE on the cached tape (gating delta −1.5% / −1.9%, CI-clean on the
  WRONG side: it selects exhausted tops that mean-revert). The Phase 1 bet is that
  STRUCTURE features — a DECORRELATED axis from momentum-confidence (Pattern D:
  the wedge is rarely the obvious axis) — select better. This script tests that
  bet CHEAPLY on the cached data BEFORE we spend on Phase 1.

  Decorrelated-on-purpose structure features, each a gating arm:
    1. S/R PROXIMITY / ROOM-TO-RUN — distance from entry to nearest swing-high
       resistance ABOVE + nearest swing-low support BELOW (k-bar fractal pivots).
       Thesis: a breakout with overhead ROOM runs; one INTO resistance stalls.
    2. MARKET STRUCTURE — HH/HL (up) vs LH/LL (down) vs range, from swing pivots.
       Thesis: enter only when structure already confirms an uptrend.
    3. MULTI-TF ALIGNMENT — 5m breakout direction vs the 1h regime direction.
       Thesis: a 5m long ALIGNED with a 1h up-trend continues; counter-trend fades.
  Plus a COMBINED arm: room ≥ X% AND 1h-aligned.

  For each arm: gating_delta = netEV(structure-gated) − netEV(ungated) at the
  break-even fee, paired block-bootstrap CI (block=3, seed 1729 — V.0's stack),
  OVERALL and PER REGIME. Compared head-to-head to V.0's momentum-gate delta.

THE ANSWER WE NEED
  * Does ANY simple structure feature show a POSITIVE / clearly positive-leaning
    (CI-aware) gating delta? Which carries it?
  * yes  → Phase 1 build justified.
  * no   → structure won't save it on THIS data; that reshapes Phase 1.

THE LEAKAGE TRAP (the whole point — features computed STRICTLY on candles[:i+1])
  A k-bar fractal pivot at bar j is only CONFIRMABLE once k bars have printed AFTER
  it. At entry i, the most recent confirmable pivot is at index i-k. EVERY feature
  here uses ONLY pivots at indices <= i-k and candle data at indices <= i. The
  multi-TF 1h regime is resampled from 5m bars up to and including i, then the
  LAST (forming) 1h bar is dropped so the regime read is on CLOSED 1h bars only.
  Unit tests below assert no-look-ahead on synthetic data.

REUSE (does NOT rebuild the harness)
  * exit_reconciliation.simulate_exit_real_close — the bot's REAL close-based exit.
  * exit_reconciliation.variance_inflation — Bartlett VIF → N_eff.
  * chart_floor_calibration — candidate detection (breakout/volume-spike), enrich,
    regime_at, has_full_horizon, WARMUP.
  * the V.0 paired-bootstrap gating-delta recipe, generalized to any gate predicate.
  * indicators.compute_regime_1h / adx_full — the live 1h-regime classifier.

HONEST CAVEATS (printed + in the doc)
  * ONE quiet chop-heavy week, two OVERLAPPING windows (W1/W2 share most bars),
    small per-regime N_eff. Directional, not a verdict.
  * a DETERMINISTIC SUBSET of the eventual Phase 1 feature set (3 simple proxies,
    not the full S/R + swing + MTF engine).
  * leakage-checked via candles[:i+1] + the 1h closed-bar drop + unit tests.

READ-ONLY w.r.t. the live bot (port 8265 — never touched). Free: cached candles.

Usage:
    python3 scripts/calibration/structure_gating_delta.py \
        --w1 /tmp/cal_candles_d1.json --w2 /tmp/cal_candles.json \
        --json-out /tmp/structure_gating_delta.json
    python3 scripts/calibration/structure_gating_delta.py --self-test   # unit tests only
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

import chart_floor_calibration as cf  # noqa: E402  candidate detection + enrich + regime
import exit_reconciliation as er  # noqa: E402  real-exit stack + VIF
import indicators as ind  # noqa: E402  compute_regime_1h (live 1h classifier)

# ── Config (inherits V.0's bootstrap params verbatim) ───────────────
N_BOOTSTRAP = er.N_BOOTSTRAP  # 5000
RNG_SEED = er.RNG_SEED  # 1729
BLOCK_LEN = er.BLOCK_LEN  # 3
BREAKEVEN_FEE = 0.10  # conservative break-even read (matches V.0)
BREAKEVEN_FEE_LOW = 0.04  # Jupiter RFQ optimistic read (matches V.0)

# Fractal pivot half-width. k=2 → a 5-bar fractal (j is the extreme of [j-2, j+2]).
# Small k keeps enough pivots on a 299-bar window while still being a real swing.
PIVOT_K = 2

# Structure-arm thresholds (deliberately simple; swept-light, not tuned).
ROOM_MIN_PCT = 1.5  # "room-to-run": overhead resistance must be >= this far above
# (1.5% = one breakout-confirm-pct of clear air to the next swing high)


# ── Fractal swing pivots (point-in-time, leakage-safe) ──────────────
def confirmed_pivots(
    highs: list[float], lows: list[float], i: int, k: int = PIVOT_K
) -> tuple[list[int], list[int]]:
    """Return (pivot_high_indices, pivot_low_indices) that are CONFIRMED as of
    bar i — i.e. usable without look-ahead.

    A k-bar fractal pivot-high at index j requires high[j] to be the strict-enough
    maximum of the window [j-k, j+k]: high[j] >= all neighbors AND strictly greater
    than at least one neighbor on EACH side (rejects flat plateaus / ties as pivots).
    It is CONFIRMED only once k bars have printed after it, i.e. j+k <= i. So we scan
    candidate centers j in [k, i-k]. All data read is at indices <= i (in fact <= i,
    with the furthest-right read at j+k <= i). NO look-ahead past i.
    """
    pivot_hi: list[int] = []
    pivot_lo: list[int] = []
    last = i - k  # furthest center whose right wing (j+k) still lands <= i
    for j in range(k, last + 1):
        wh = highs[j - k : j + k + 1]
        wl = lows[j - k : j + k + 1]
        cj_h, cj_l = highs[j], lows[j]
        # pivot-high: center is the max, strictly above >=1 neighbor each side
        left_h = wh[:k]
        right_h = wh[k + 1 :]
        if cj_h >= max(wh) and any(cj_h > x for x in left_h) and any(cj_h > x for x in right_h):
            pivot_hi.append(j)
        # pivot-low: center is the min, strictly below >=1 neighbor each side
        left_l = wl[:k]
        right_l = wl[k + 1 :]
        if cj_l <= min(wl) and any(cj_l < x for x in left_l) and any(cj_l < x for x in right_l):
            pivot_lo.append(j)
    return pivot_hi, pivot_lo


# ── Feature 1: S/R proximity / room-to-run ──────────────────────────
def room_to_run(c: dict, i: int, k: int = PIVOT_K) -> tuple[float | None, float | None]:
    """(room_up_pct, support_dist_pct) at entry bar i, from CONFIRMED fractal pivots.

    room_up_pct      = % distance from entry close UP to the NEAREST confirmed
                       swing-high strictly ABOVE the close (the next resistance the
                       breakout must clear). None if no confirmed pivot-high sits
                       above the close (open sky overhead → unbounded room).
    support_dist_pct = % distance from entry close DOWN to the NEAREST confirmed
                       swing-low strictly BELOW the close (the support cushion).
                       None if none below.

    The "room-to-run" thesis: a breakout entered with ample overhead room (large
    room_up_pct, or open sky = None) has room to continue; a breakout entered just
    UNDER a heavy swing-high resistance gets sold. We treat open-sky (None) as the
    MOST room (a fresh high above all prior swings)."""
    px = c["close"][i]
    if px <= 0:
        return None, None
    pivot_hi, pivot_lo = confirmed_pivots(c["high"], c["low"], i, k)
    highs_above = [c["high"][j] for j in pivot_hi if c["high"][j] > px]
    lows_below = [c["low"][j] for j in pivot_lo if c["low"][j] < px]
    room_up = (min(highs_above) - px) / px * 100 if highs_above else None  # None = open sky
    sup_dist = (px - max(lows_below)) / px * 100 if lows_below else None
    return room_up, sup_dist


def has_room(room_up_pct: float | None, min_pct: float = ROOM_MIN_PCT) -> bool:
    """Room-to-run gate passes when overhead room is open sky (None) OR >= min_pct.
    A breakout with < min_pct to the next swing-high resistance is REJECTED (it is
    breaking out straight into a ceiling)."""
    return room_up_pct is None or room_up_pct >= min_pct


# ── Feature 2: market structure (HH/HL vs LH/LL vs range) ───────────
def market_structure(c: dict, i: int, k: int = PIVOT_K) -> str:
    """Classify the swing structure as of bar i from CONFIRMED pivots:
       UP    : last two confirmed swing-highs are higher-highs AND last two
               confirmed swing-lows are higher-lows (HH + HL).
       DOWN  : last two swing-highs lower-highs AND last two swing-lows lower-lows.
       RANGE : anything else (mixed / insufficient pivots).
    Uses only confirmed pivots (indices <= i-k) → no look-ahead."""
    pivot_hi, pivot_lo = confirmed_pivots(c["high"], c["low"], i, k)
    if len(pivot_hi) < 2 or len(pivot_lo) < 2:
        return "RANGE"
    h2 = [c["high"][j] for j in pivot_hi[-2:]]
    l2 = [c["low"][j] for j in pivot_lo[-2:]]
    hh = h2[-1] > h2[-2]
    hl = l2[-1] > l2[-2]
    lh = h2[-1] < h2[-2]
    ll = l2[-1] < l2[-2]
    if hh and hl:
        return "UP"
    if lh and ll:
        return "DOWN"
    return "RANGE"


def structure_up(struct: str) -> bool:
    """Structure gate: enter only when swing structure already confirms an uptrend."""
    return struct == "UP"


# ── Feature 3: multi-TF alignment (5m breakout vs 1h regime) ────────
def resample_1h_closed(c: dict, i: int) -> list[dict]:
    """Resample 5m candles[:i+1] into 1h OHLCV bars, returning ONLY CLOSED 1h bars
    (the last, still-forming hour is DROPPED — that is the leakage guard for the
    multi-TF read: we never let the in-progress hour, which contains the entry bar's
    own breakout move, leak into the regime classification).

    Bucketing is by floor(ts_ms / 3_600_000). A bucket is 'closed' if a LATER bucket
    has started (i.e. it is not the max bucket present in [:i+1])."""
    ts = c["ts"][: i + 1]
    op = c["open"][: i + 1]
    hi = c["high"][: i + 1]
    lo = c["low"][: i + 1]
    cl = c["close"][: i + 1]
    vol = c["volume"][: i + 1]
    buckets: dict[int, list[int]] = {}
    for idx, t in enumerate(ts):
        b = int(t // 3_600_000)
        buckets.setdefault(b, []).append(idx)
    if not buckets:
        return []
    max_b = max(buckets)  # the still-forming hour → drop
    out: list[dict] = []
    for b in sorted(buckets):
        if b == max_b:
            continue  # drop the in-progress hour (no look-ahead)
        members = buckets[b]
        out.append(
            {
                "ts": ts[members[0]],
                "open": op[members[0]],
                "high": max(hi[m] for m in members),
                "low": min(lo[m] for m in members),
                "close": cl[members[-1]],
                "volume": sum(vol[m] for m in members),
            }
        )
    return out


def tf_alignment(c: dict, i: int) -> str:
    """The 1h regime label (TREND-UP / TREND-DOWN / CHOP) from CLOSED 1h bars as of
    bar i, via the LIVE classifier indicators.compute_regime_1h. The 5m breakout is
    always a LONG (up) entry, so:
       ALIGNED      = TREND-UP   (5m long with the 1h up-trend)
       COUNTER      = TREND-DOWN (5m long against the 1h down-trend)
       NEUTRAL/CHOP = CHOP       (no 1h trend to align with)."""
    bars_1h = resample_1h_closed(c, i)
    regime = ind.compute_regime_1h(bars_1h)  # "TREND-UP" | "TREND-DOWN" | "CHOP"
    if regime == "TREND-UP":
        return "ALIGNED"
    if regime == "TREND-DOWN":
        return "COUNTER"
    return "NEUTRAL"


def tf_aligned(align: str) -> bool:
    """Multi-TF gate: enter only when the 5m long is aligned with a 1h up-trend."""
    return align == "ALIGNED"


# ── Candidate with structure features attached (real-exit gross pnl) ─
@dataclass
class SCand:
    sym: str
    idx: int
    pnl_real: float  # realized gross pnl%, REAL close-based exit stack (V.0's model)
    regime_5m: str  # ADX-based 5m regime (the partition axis, = V.0's regime_at)
    room_up: float | None
    support_dist: float | None
    structure: str  # UP / DOWN / RANGE
    align: str  # ALIGNED / COUNTER / NEUTRAL

    # ── arm predicates (each a structure gate) ──
    def gate_room(self) -> bool:
        return has_room(self.room_up)

    def gate_structure(self) -> bool:
        return structure_up(self.structure)

    def gate_align(self) -> bool:
        return tf_aligned(self.align)

    def gate_combined(self) -> bool:
        # "room >= X% AND 1h-aligned" — the brief's combined arm
        return has_room(self.room_up) and tf_aligned(self.align)


ARMS: list[tuple[str, str]] = [
    ("room", "room-to-run (overhead room open-sky OR >= 1.5%)"),
    ("structure", "market structure = UP (HH+HL)"),
    ("align", "multi-TF: 5m long ALIGNED with 1h TREND-UP"),
    ("combined", "room>=1.5% AND 1h-aligned"),
]


def gate_for(cand: SCand, arm: str) -> bool:
    return {
        "room": cand.gate_room,
        "structure": cand.gate_structure,
        "align": cand.gate_align,
        "combined": cand.gate_combined,
    }[arm]()


def collect(data: dict[str, dict]) -> list[SCand]:
    """Time-ordered within each symbol (block bootstrap needs within-symbol order).
    Same candidate universe as V.0 (breakout OR volume-spike, full-horizon)."""
    out: list[SCand] = []
    for sym, c in data.items():
        n = len(c["close"])
        i = cf.WARMUP
        while i < n:
            if (cf.breakout_fires(c, i) or cf.volume_spike_fires(c, i)) and cf.has_full_horizon(
                c, i
            ):
                room_up, sup_dist = room_to_run(c, i)
                out.append(
                    SCand(
                        sym=sym,
                        idx=i,
                        pnl_real=er.simulate_exit_real_close(c, i),
                        regime_5m=cf.regime_at(c, i),
                        room_up=room_up,
                        support_dist=sup_dist,
                        structure=market_structure(c, i),
                        align=tf_alignment(c, i),
                    )
                )
                i += 6  # no-overlap, mirrors V.0 / backtest run_symbol
            else:
                i += 1
    return out


# ── Per-arm net-EV + paired gating-delta bootstrap ──────────────────
def arm_describe(cands: list[SCand], arm: str | None, fee: float) -> dict:
    """net-EV%, block-bootstrap 95% CI, N, N_eff for an arm (None = ungated/ALL)."""
    by_sym: dict[str, list[float]] = {}
    by_sym_gross: dict[str, list[float]] = {}
    for cand in cands:
        if arm is not None and not gate_for(cand, arm):
            continue
        by_sym.setdefault(cand.sym, []).append(cand.pnl_real - fee)
        by_sym_gross.setdefault(cand.sym, []).append(cand.pnl_real)
    series = list(by_sym.values())
    flat = [v for s in series for v in s]
    if not flat:
        return {"n": 0, "n_eff": 0.0, "net_ev": float("nan"), "ci": (float("nan"),) * 2}
    vif = er.variance_inflation(list(by_sym_gross.values()))
    pt, lo, hi = er.block_bootstrap_ci(series)
    return {
        "n": len(flat),
        "n_eff": len(flat) / vif if vif else len(flat),
        "net_ev": pt,
        "ci": (lo, hi),
        "excl0": (lo > 0 or hi < 0),
    }


def gating_delta_ci(cands: list[SCand], arm: str, fee: float, regime: str | None = None) -> dict:
    """Paired block-bootstrap CI on netEV(arm-gated) − netEV(ungated).

    Generalizes V.0's gating_delta_ci to ANY gate predicate. The gated arm is a
    SUBSET of the ungated arm, so we resample the UNDERLYING candidates ONCE per
    iteration (moving blocks within symbol), recompute BOTH arm means on the SAME
    resample, take the difference — preserving the dependence. Fee cancels in the
    difference (fee-invariant); passed only for the explicit net level. `regime`
    restricts the WHOLE comparison to one 5m regime partition (per-regime delta).
    """
    pool = [c for c in cands if (regime is None or c.regime_5m == regime)]
    by_sym: dict[str, list[tuple[float, bool]]] = {}
    for cand in pool:
        by_sym.setdefault(cand.sym, []).append((cand.pnl_real, gate_for(cand, arm)))
    symbols = [s for s in by_sym.values() if s]
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

    def arm_means(resample: list[tuple[float, bool]]) -> tuple[float, float] | None:
        off = [g - fee for (g, _p) in resample]
        on = [g - fee for (g, p) in resample if p]
        if not off or not on:
            return None
        return st.mean(on), st.mean(off)

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
    if not boots:
        return {
            "delta": point_delta,
            "ci": (float("nan"),) * 2,
            "n_on": len(on_pt),
            "n_off": len(off_pt),
            "net_on": st.mean(on_pt),
            "net_off": st.mean(off_pt),
            "excl0": False,
        }
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
def _excl_tag(d: dict) -> str:
    lo, _hi = d["ci"]
    if not d.get("excl0"):
        return "no"
    return "YES(+)" if lo > 0 else "YES(-)"


def print_feature_dist(label: str, cands: list[SCand]) -> dict:
    """Distribution of each structure feature across the candidate tape."""
    print(f"\n  --- structure-feature distribution — WINDOW {label} (N={len(cands)}) ---")
    n = len(cands) or 1
    n_room = sum(1 for c in cands if c.gate_room())
    n_open_sky = sum(1 for c in cands if c.room_up is None)
    struct_mix = {s: sum(1 for c in cands if c.structure == s) for s in ("UP", "DOWN", "RANGE")}
    align_mix = {
        a: sum(1 for c in cands if c.align == a) for a in ("ALIGNED", "COUNTER", "NEUTRAL")
    }
    n_comb = sum(1 for c in cands if c.gate_combined())
    rooms = [c.room_up for c in cands if c.room_up is not None]
    print(
        f"    room-to-run pass: {n_room}/{n} ({100 * n_room / n:.0f}%)  "
        f"[open-sky overhead: {n_open_sky}]  "
        f"median room_up%={st.median(rooms):.2f}"
        if rooms
        else f"    room-to-run pass: {n_room}/{n} ({100 * n_room / n:.0f}%) [open-sky overhead: {n_open_sky}]"
    )
    print(f"    structure: {struct_mix}  (UP passes the structure gate)")
    print(f"    1h-align : {align_mix}  (ALIGNED passes the align gate)")
    print(f"    combined (room AND aligned) pass: {n_comb}/{n} ({100 * n_comb / n:.0f}%)")
    return {
        "n_total": len(cands),
        "n_room_pass": n_room,
        "n_open_sky": n_open_sky,
        "structure_mix": struct_mix,
        "align_mix": align_mix,
        "n_combined_pass": n_comb,
    }


def print_arm_table(label: str, cands: list[SCand]) -> dict:
    print(
        f"\n  === STRUCTURE GATING DELTA = netEV(gated) - netEV(ungated), paired "
        f"block-bootstrap CI (block={BLOCK_LEN}, n_boot={N_BOOTSTRAP}, seed={RNG_SEED}) "
        f"— WINDOW {label} ==="
    )
    print("    (delta is fee-invariant; shown at break-even fee 0.10%. Ungated = ALL candidates.)")
    hdr = (
        f"  {'arm':>10} {'N_on':>5} {'N_off':>5} | {'netEV(on)%':>10} {'netEV(off)%':>11} | "
        f"{'Δ%':>8} {'paired 95% CI':>20} {'CI':>7}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    out: dict = {}
    for arm, _desc in ARMS:
        g = gating_delta_ci(cands, arm, BREAKEVEN_FEE)
        lo, hi = g["ci"]
        tag = _excl_tag(g)
        print(
            f"  {arm:>10} {g['n_on']:>5} {g['n_off']:>5} | "
            f"{g['net_on']:>+10.3f} {g['net_off']:>+11.3f} | "
            f"{g['delta']:>+8.3f} [{lo:>+6.3f},{hi:>+6.3f}] {tag:>7}"
        )
        out[arm] = {
            "n_on": g["n_on"],
            "n_off": g["n_off"],
            "net_on": g["net_on"],
            "net_off": g["net_off"],
            "delta": g["delta"],
            "ci": [lo, hi],
            "excl_zero": g["excl0"],
            "excl_zero_positive": bool(g["excl0"] and lo > 0),
            "delta_point_positive": g["delta"] > 0,
        }
    return out


def print_per_regime(label: str, cands: list[SCand]) -> dict:
    """Per-5m-regime gating delta for each arm (the chop-vs-trend partition)."""
    regimes = ["trend", "transitional", "chop"]
    print(f"\n  --- per-5m-regime structure gating delta (break-even fee) — WINDOW {label} ---")
    out: dict = {}
    for rg in regimes:
        n_rg = sum(1 for c in cands if c.regime_5m == rg)
        print(f"    [{rg.upper()}] N={n_rg}")
        out[rg] = {}
        for arm, _desc in ARMS:
            g = gating_delta_ci(cands, arm, BREAKEVEN_FEE, regime=rg)
            lo, hi = g["ci"]
            tag = _excl_tag(g)
            dval = f"{g['delta']:+.3f}" if g["delta"] == g["delta"] else "  n/a"
            ci = f"[{lo:+.3f},{hi:+.3f}]" if (lo == lo and hi == hi) else "[   n/a ]"
            print(f"        {arm:>10}: N_on={g['n_on']:>3}  Δ={dval:>8}  {ci:>18}  {tag}")
            out[rg][arm] = {
                "n_on": g["n_on"],
                "n_off": g["n_off"],
                "delta": g["delta"],
                "ci": [lo, hi],
                "excl_zero": g["excl0"],
                "excl_zero_positive": bool(g["excl0"] and lo > 0),
            }
    return out


def momentum_baseline(cands_data: dict[str, dict]) -> dict:
    """Recompute V.0's momentum-gate delta on the SAME enriched windows, via the
    V.0 module, so the comparison row is apples-to-apples (same data, same stack)."""
    import fee_sensitivity_gating_delta as v0

    mcands = v0.collect(cands_data)
    g_lo = v0.gating_delta_ci(mcands, BREAKEVEN_FEE_LOW)
    g_hi = v0.gating_delta_ci(mcands, BREAKEVEN_FEE)
    return {
        "n_on": g_hi["n_on"],
        "n_off": g_hi["n_off"],
        "delta": g_hi["delta"],
        "ci": list(g_hi["ci"]),
        "excl_zero": g_hi["excl0"],
        "net_on": g_hi["net_on"],
        "net_off": g_hi["net_off"],
        "delta_low_fee": g_lo["delta"],
    }


def run_window(label: str, raw: dict) -> dict:
    data = {sym: cf.enrich(cs) for sym, cs in raw.items() if len(cs) >= 60}
    cands = collect(data)
    print(f"\n{'#' * 100}\n#  WINDOW {label}\n{'#' * 100}")
    cf.print_window_summary(data)
    print(f"\n  candidates: {len(cands)} (ungated baseline = ALL)")
    feat = print_feature_dist(label, cands)
    arm_tbl = print_arm_table(label, cands)
    per_rg = print_per_regime(label, cands)
    mbase = momentum_baseline(data)
    mlo, mhi = mbase["ci"]
    print(
        f"\n  >>> MOMENTUM BASELINE (V.0, same window): Δ={mbase['delta']:+.3f}%  "
        f"CI[{mlo:+.3f},{mhi:+.3f}]  (N_on={mbase['n_on']})  "
        f"— the number every structure arm must BEAT (less negative / positive)"
    )
    return {
        "n_candidates": len(cands),
        "feature_distribution": feat,
        "arm_gating_delta": arm_tbl,
        "per_regime": per_rg,
        "momentum_baseline": mbase,
    }


# ── Unit tests (synthetic — the leakage trap is asserted here) ──────
def _approx(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol


def self_test() -> bool:
    """Synthetic, deterministic tests of the structure features + the leakage guard."""
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # --- T1: fractal pivot detection on a hand-built zig-zag (k=2) ---
    # highs:  index 4 is a clear peak (10), index 8 a clear peak (12).
    #         lows:  index 2 a clear trough, index 6 a clear trough.
    H = [1.0, 2, 3, 4, 10, 4, 3, 5, 12, 6, 5, 4, 3]
    L = [1.0, 1, 0, 2, 3, 2, 0, 3, 5, 4, 2, 1, 0]
    # confirm at i large enough that both peaks are confirmable (i >= 8+2=10)
    ph, pl = confirmed_pivots(H, L, i=12, k=2)
    check("T1a pivot-highs at {4,8}", ph == [4, 8])
    # lows: index 2 (val 0) and index 6 (val 0) are troughs; index 12 unconfirmed
    check("T1b pivot-lows include 2 and 6", 2 in pl and 6 in pl and 12 not in pl)

    # --- T2: LEAKAGE — a peak at index j is NOT confirmable before j+k ---
    # At i = j+k-1 the peak must be ABSENT; at i = j+k it must APPEAR.
    ph_before, _ = confirmed_pivots(H, L, i=4 + 2 - 1, k=2)  # i=5, peak@4 not yet
    ph_at, _ = confirmed_pivots(H, L, i=4 + 2, k=2)  # i=6, peak@4 now confirmed
    check("T2a peak@4 NOT seen at i=5 (no look-ahead)", 4 not in ph_before)
    check("T2b peak@4 seen exactly at i=6 (j+k)", 4 in ph_at)

    # --- T3: room-to-run direction ---
    # Build a series where the entry close sits BELOW a known swing-high resistance.
    c = {
        "high": [5, 6, 9, 6, 5, 7, 7, 7],  # swing-high (9) at index 2
        "low": [4, 4, 7, 4, 3, 5, 5, 5],  # swing-low (3) at index 4
        "close": [4.5, 5.5, 8.5, 5.5, 4.0, 6.0, 6.0, 6.0],
        "volume": [1] * 8,
        "open": [4] * 8,
        "ts": [i * 300000 for i in range(8)],
    }
    # entry at i=6, close=6.0 → resistance@9 (index2) above → room_up=(9-6)/6*100=50%
    #   support@3 (index4) below → support_dist=(6-3)/6*100=50%
    ru, sd = room_to_run(c, 6, k=2)
    check("T3a room_up = 50% to swing-high resistance", _approx(ru, 50.0))
    check("T3b support_dist = 50% to swing-low support", _approx(sd, 50.0))
    # open-sky: entry above all confirmed swing-highs → room_up is None (most room)
    c2 = {
        "high": [5, 9, 5, 4, 5, 20, 20, 20],  # only confirmed swing-high is 9@idx1
        "low": [4, 7, 3, 2, 3, 18, 18, 18],
        "close": [4.5, 8.5, 4.0, 3.0, 4.0, 19, 19, 19],  # entry@i6 close=19 > 9
        "volume": [1] * 8,
        "open": [4] * 8,
        "ts": [i * 300000 for i in range(8)],
    }
    ru2, _ = room_to_run(c2, 6, k=2)
    check("T3c open-sky overhead → room_up is None", ru2 is None)
    check("T3d has_room(None) is True (open sky = max room)", has_room(None) is True)
    check("T3e has_room(0.5%) is False (< 1.5% ceiling)", has_room(0.5) is False)

    # --- T4: market structure HH/HL vs LH/LL ---
    # Build a clean alternating zig-zag from explicit pivots with linear ramps
    # between them, so each pivot is a strict local extreme of its 5-bar window.
    def _zigzag(pivots: list[tuple[str, int, float]]) -> dict:
        # pivots: list of (kind 'H'|'L', bar_index, level), bar_index ascending.
        xs = [p[1] for p in pivots]
        ys = [p[2] for p in pivots]
        n = xs[-1] + 1
        mid = [0.0] * n
        for s in range(len(xs) - 1):
            x0, x1, y0, y1 = xs[s], xs[s + 1], ys[s], ys[s + 1]
            for x in range(x0, x1 + 1):
                mid[x] = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        hi = [m + 0.3 for m in mid]
        lo = [m - 0.3 for m in mid]
        for kind, idx, _lvl in pivots:
            if kind == "H":
                hi[idx] = mid[idx] + 0.6  # strict local high
            else:
                lo[idx] = mid[idx] - 0.6  # strict local low
        return {
            "high": hi,
            "low": lo,
            "close": mid,
            "open": mid,
            "volume": [1.0] * n,
            "ts": [i * 300000 for i in range(n)],
        }

    # UP-trend: peaks 7->10->13 (HH), troughs 4->5->6 (HL)
    up = _zigzag(
        [
            ("L", 0, 3),
            ("H", 4, 7),
            ("L", 8, 4),
            ("H", 12, 10),
            ("L", 16, 5),
            ("H", 20, 13),
            ("L", 24, 6),
        ]
    )
    check("T4a ascending zig-zag → UP (HH+HL)", market_structure(up, 24, k=2) == "UP")
    # DOWN-trend: peaks 13->10->7 (LH), troughs 8->5->2 (LL)
    dn = _zigzag(
        [
            ("L", 0, 16),
            ("H", 4, 13),
            ("L", 8, 8),
            ("H", 12, 10),
            ("L", 16, 5),
            ("H", 20, 7),
            ("L", 24, 2),
        ]
    )
    check("T4b descending zig-zag → DOWN (LH+LL)", market_structure(dn, 24, k=2) == "DOWN")
    # mixed (HH but LL) → RANGE
    rng_fix = _zigzag(
        [
            ("L", 0, 5),
            ("H", 4, 7),
            ("L", 8, 2),
            ("H", 12, 10),
            ("L", 16, 1),
            ("H", 20, 13),
            ("L", 24, 0),
        ]
    )
    check("T4c HH-but-LL → RANGE", market_structure(rng_fix, 24, k=2) == "RANGE")

    # --- T5: multi-TF closed-bar resample drops the forming hour ---
    # 5m bars across 2.5 hours (30 bars). Buckets: hour0(0-11), hour1(12-23),
    # hour2(24-29, FORMING). resample_1h_closed must return 2 bars (hour0,hour1).
    n = 30
    tf = {
        "ts": [i * 300000 for i in range(n)],  # 5m = 300000 ms
        "open": [10.0] * n,
        "high": [10.0 + i for i in range(n)],
        "low": [10.0] * n,
        "close": [10.0] * n,
        "volume": [1.0] * n,
    }
    bars = resample_1h_closed(tf, n - 1)
    check("T5a closed-1h count drops forming hour (2 of 3)", len(bars) == 2)
    # hour1 high must be max of indices 12..23 = 10+23 = 33 (NOT touching 24..29)
    check("T5b last closed-1h high excludes forming hour", _approx(bars[-1]["high"], 33.0))

    print(f"\n  {'ALL TESTS PASS' if ok else 'SOME TESTS FAILED'}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w1", default="/tmp/cal_candles_d1.json")
    ap.add_argument("--w2", default="/tmp/cal_candles.json")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--self-test", action="store_true", help="run unit tests only")
    args = ap.parse_args()

    print("=" * 100)
    print("PHASE 1 DE-RISK — STRUCTURE-FEATURE GATING-DELTA FALSIFIER (LOCAL, deterministic, $0)")
    print("=" * 100)
    print("  Self-test (synthetic leakage + feature checks):")
    tests_ok = self_test()
    if args.self_test:
        sys.exit(0 if tests_ok else 1)
    if not tests_ok:
        print(
            "\nABORT: self-test failed — features are wrong, do not trust the table.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        "\nCAVEAT: LOCAL deterministic structure proxy, NOT the live Gecko Oracle. "
        "One quiet chop-heavy week, two overlapping windows, deterministic SUBSET of "
        "the eventual Phase 1 feature set, small per-regime N_eff. Directional, not a verdict."
    )

    results: dict = {
        "generated": "2026-05-22",
        "phase": "Phase 1 de-risk — structure-feature gating-delta",
        "caveat": "LOCAL deterministic structure proxy (3 simple features), NOT the live "
        "Gecko Oracle. One quiet chop-heavy week, two overlapping windows, deterministic "
        "SUBSET of the eventual Phase 1 feature set, small per-regime N_eff. Leakage-checked "
        "via candles[:i+1] + closed-1h drop + unit tests. Directional, not a verdict.",
        "block_len": BLOCK_LEN,
        "n_bootstrap": N_BOOTSTRAP,
        "rng_seed": RNG_SEED,
        "breakeven_fee": BREAKEVEN_FEE,
        "pivot_k": PIVOT_K,
        "room_min_pct": ROOM_MIN_PCT,
        "arms": {a: d for a, d in ARMS},
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
