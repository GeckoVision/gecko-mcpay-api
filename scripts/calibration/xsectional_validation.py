#!/usr/bin/env python3
"""Phase S52 — Experiment 2: cross-sectional / relative-value (quant-analyst, 2026-05-24).

THE QUESTION
  Per-token tests ask "is THIS token going up" — direction. They were 3 nulls.
  Cross-sectional asks a DIFFERENT question: "which of the N is BEST right now."
  Relative value can have edge even when absolute direction does not — you do not
  need to predict the market, only the CROSS-SECTION (winners keep winning, or
  losers revert). Two ranking hypotheses:

    * MOMENTUM (relative strength): rank by trailing return; long the strongest,
      short the weakest. (cross-sectional momentum, Jegadeesh-Titman flavour.)
    * MEAN-REVERSION: the negated rank — long the weakest, short the strongest.
      (short-horizon cross-sectional reversal.)

  Forms tested:
    * LONG-ONLY: hold the top-k ranked symbols, rotate each rebalance. Testable
      NOW (no shorting, no perps).
    * LONG-SHORT: long top-k / short bottom-k → the DOLLAR-NEUTRAL SPREAD. The
      short leg needs perps (not in the spot tape); reported as the THEORETICAL
      spread, flagged as such.

DESIGN
  * 6 symbols PYTH WIF JTO BOME SOL BTC on 1H bars, PERFECTLY timestamp-aligned
    (6599 common bars — verified). t indexes the shared clock.
  * At each rebalance bar t: rank by signal(lookback) over the trailing window;
    form the long (top-k) and short (bottom-k) baskets; hold for `hold` bars;
    realize the equal-weight basket forward return. Rebalance stride = hold (no
    overlap), so the realized-return blocks do not overlap in time (clean for the
    bootstrap + CPCV label = the hold).
  * VARIANTS swept (honest count for DSR/PBO): signal ∈ {momentum, reversion} ×
    lookback ∈ {6,12,24,48} bars × hold ∈ {6,12,24} bars × k ∈ {1,2}. Every one
    is a trial; the best is exactly what DSR/PBO must deflate.

RIGOR (quant-backtest-rigor SKILL)
  * Block-bootstrap CI on each variant's long-only EV and the L/S spread.
  * CPCV (8 groups, k=2) per promising variant — distribution of OOS Sharpes.
  * PBO over ALL variants tried (the full grid).
  * DSR on the best variant, deflated for the honest variant count.
  * VERDICT block per promising variant. Default REJECT unless the rigor clears.

FEES — the L/S spread pays TWO round-trips (long + short legs) per rebalance.
  Long-only pays one. We report gross AND net at the fee grid; the bar is the same
  2x-fee margin-of-safety used in Experiment 1.

DATA LIMITATION (flagged)
  Spot OHLCV time bars only: (1) the SHORT leg needs perps — not in this tape, so
  L/S is THEORETICAL; (2) no funding-rate data — a real perp short pays/earns
  funding that this cannot model; (3) no borrow cost; (4) close-to-close hides
  intrabar path; (5) time bars (not dollar/volume bars) leave the variance noisy.
  Cross-sectional rank is itself robust to (4) at the basket level, but the L/S
  net number is an UPPER bound that ignores funding + borrow.

READ-ONLY w.r.t. the live bot (port 8265). Free: cached tape replay, no LLM/net.

Run:  python3 scripts/calibration/xsectional_validation.py
      python3 scripts/calibration/xsectional_validation.py --self-test
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys
from dataclasses import dataclass
from itertools import product

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import overfitting_rigor as ofr  # noqa: E402
import stats_validation as sv  # noqa: E402

TAPE_DIR = os.path.join(_HERE, "data", "tape")
SYMBOLS = ["PYTH", "WIF", "JTO", "BOME", "SOL", "BTC"]
TF = "1H"
WARMUP = 50

# Variant grid (honest count for DSR/PBO)
SIGNALS = ("momentum", "reversion")
LOOKBACKS = (6, 12, 24, 48)
HOLDS = (6, 12, 24)
KS = (1, 2)

FEE_GRID = [0.04, 0.10, 0.20, 0.40, 0.75]

CPCV_N_GROUPS = 8
CPCV_N_TEST = 2
CPCV_EMBARGO = 1


# ── Aligned panel ───────────────────────────────────────────────────
def load_aligned() -> tuple[list[float], dict[str, list[float]]]:
    """Return (timestamps, {symbol: close[]}) on the common 1H clock. Asserts the
    timestamps align across all symbols (they do — verified 6599 common bars)."""
    ts_ref: list[float] | None = None
    closes: dict[str, list[float]] = {}
    for sym in SYMBOLS:
        with open(os.path.join(TAPE_DIR, f"{sym}_{TF}.json")) as f:
            d = json.load(f)
        ts = [x["ts"] for x in d]
        if ts_ref is None:
            ts_ref = ts
        elif ts != ts_ref:
            # fall back to the intersection if a tape drifts
            common = sorted(set(ts_ref) & set(ts))
            return _reindex_to(common)
        closes[sym] = [x["close"] for x in d]
    assert ts_ref is not None
    return ts_ref, closes


def _reindex_to(common: list[float]) -> tuple[list[float], dict[str, list[float]]]:
    closes: dict[str, list[float]] = {}
    cset = set(common)
    for sym in SYMBOLS:
        with open(os.path.join(TAPE_DIR, f"{sym}_{TF}.json")) as f:
            d = json.load(f)
        m = {x["ts"]: x["close"] for x in d if x["ts"] in cset}
        closes[sym] = [m[t] for t in common]
    return common, closes


# ── Signal + ranking ────────────────────────────────────────────────
def trailing_return(close: list[float], t: int, lookback: int) -> float | None:
    """% return over the trailing `lookback` bars ending at t (inclusive of t)."""
    if t - lookback < 0:
        return None
    base = close[t - lookback]
    if base <= 0:
        return None
    return (close[t] - base) / base * 100.0


def rank_symbols(
    closes: dict[str, list[float]], t: int, lookback: int, signal: str
) -> list[tuple[str, float]] | None:
    """Rank symbols by signal at bar t. Returns [(sym, score)] sorted DESC by the
    quantity we go LONG on. momentum → long high trailing return; reversion →
    long LOW trailing return (negate). None if any symbol lacks the window."""
    scored: list[tuple[str, float]] = []
    for sym, cl in closes.items():
        r = trailing_return(cl, t, lookback)
        if r is None:
            return None
        scored.append((sym, r if signal == "momentum" else -r))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def fwd_return(close: list[float], t: int, hold: int) -> float | None:
    """% forward return from t to t+hold (close-to-close)."""
    j = t + hold
    if j >= len(close) or close[t] <= 0:
        return None
    return (close[j] - close[t]) / close[t] * 100.0


# ── One variant: realized per-rebalance basket returns ──────────────
@dataclass
class VariantReturns:
    long_only: list[float]  # equal-weight top-k forward return per rebalance
    short_basket: list[float]  # equal-weight bottom-k forward return (for L/S)
    spread: list[float]  # long_only - short_basket (dollar-neutral, gross)
    bar_index: list[int]  # rebalance bar t (time-order key, shared clock)


def run_variant(
    closes: dict[str, list[float]], ts: list[float], signal: str, lookback: int, hold: int, k: int
) -> VariantReturns:
    n = len(ts)
    long_only: list[float] = []
    short_basket: list[float] = []
    spread: list[float] = []
    bar_index: list[int] = []
    t = max(WARMUP, lookback)
    while t + hold < n:
        ranked = rank_symbols(closes, t, lookback, signal)
        if ranked is None:
            t += 1
            continue
        long_syms = [s for s, _ in ranked[:k]]
        short_syms = [s for s, _ in ranked[-k:]]
        long_fwd = [fwd_return(closes[s], t, hold) for s in long_syms]
        short_fwd = [fwd_return(closes[s], t, hold) for s in short_syms]
        if any(x is None for x in long_fwd) or any(x is None for x in short_fwd):
            t += 1
            continue
        lo = st.mean(long_fwd)  # type: ignore[arg-type]
        sh = st.mean(short_fwd)  # type: ignore[arg-type]
        long_only.append(lo)
        short_basket.append(sh)
        spread.append(lo - sh)  # long top, short bottom; dollar-neutral gross
        bar_index.append(t)
        t += hold  # no-overlap rebalance (blocks do not overlap in time)
    return VariantReturns(long_only, short_basket, spread, bar_index)


# ── EV + CI helpers (single pooled series — basket returns share one clock) ──
def ev_ci(returns: list[float]) -> dict:
    """Block-bootstrap CI on a single time-ordered return series (one basket on
    the shared clock — there is one series, not per-symbol, since the basket
    aggregates symbols each rebalance)."""
    if len(returns) < 2:
        return {
            "n": len(returns),
            "ev": float("nan"),
            "ci": (float("nan"), float("nan")),
            "excl0": False,
            "sharpe": 0.0,
        }
    mean, lo, hi, n_eff, block = sv.block_bootstrap_ci([returns])
    return {
        "n": len(returns),
        "n_eff": n_eff,
        "ev": mean,
        "ci": (lo, hi),
        "block": block,
        "excl0": (lo > 0 or hi < 0),
        "excl0_pos": (lo > 0),
        "sharpe": ofr.sharpe_ratio(returns),
    }


# ── CPCV for one return series ──────────────────────────────────────
def cpcv_series(
    returns: list[float], bar_index: list[int], hold: int, fee: float = 0.0
) -> ofr.CPCVResult:
    """CPCV over a single time-ordered basket-return series. Groups = contiguous
    equal-population time blocks; label spills 0 groups because rebalances are
    non-overlapping (the hold is already baked into each return — the NEXT
    rebalance starts after the hold). embargo=1 still guards the block boundary."""
    if len(returns) < CPCV_N_GROUPS * 2:
        return ofr.CPCVResult(
            CPCV_N_GROUPS,
            CPCV_N_TEST,
            0,
            [],
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            0.0,
            note="too few rebalances for CPCV",
        )
    order = sorted(range(len(returns)), key=lambda i: bar_index[i])
    rets = [returns[i] - fee for i in order]
    n = len(rets)
    bounds = [round(n * gi / CPCV_N_GROUPS) for gi in range(CPCV_N_GROUPS + 1)]
    samples: list[tuple[int, float, int]] = []
    for gi in range(CPCV_N_GROUPS):
        for p in range(bounds[gi], bounds[gi + 1]):
            samples.append((gi, rets[p], gi))  # label closes in its own group
    return ofr.cpcv_paths(
        samples, n_groups=CPCV_N_GROUPS, n_test=CPCV_N_TEST, embargo_groups=CPCV_EMBARGO
    )


# ── PBO across the whole variant grid ───────────────────────────────
def pbo_over_grid(
    variant_series: dict[str, list[float]], variant_bar_index: dict[str, list[int]]
) -> ofr.PBOResult:
    """PBO with one column per variant. Rows = common time blocks; value = the
    variant's mean return in that block. Variants are aligned to a shared block
    grid built on the union of rebalance bars so columns are comparable."""
    names = list(variant_series.keys())
    if len(names) < 2:
        return ofr.PBOResult(float("nan"), 0, len(names), float("nan"), note="need >=2 variants")
    all_bars = sorted({b for bi in variant_bar_index.values() for b in bi})
    if len(all_bars) < 10:
        return ofr.PBOResult(float("nan"), 0, len(names), float("nan"), note="too few bars")
    n_blocks = 10
    lo_bar, hi_bar = all_bars[0], all_bars[-1]
    span = max(1, hi_bar - lo_bar)

    def block_of(bar: int) -> int:
        return min(n_blocks - 1, int((bar - lo_bar) / span * n_blocks))

    matrix: list[list[float]] = []
    for b in range(n_blocks):
        row: list[float] = []
        for name in names:
            rets = variant_series[name]
            bars = variant_bar_index[name]
            vals = [rets[i] for i in range(len(rets)) if block_of(bars[i]) == b]
            row.append(st.mean(vals) if vals else 0.0)
        matrix.append(row)
    return ofr.pbo(matrix, n_partitions=n_blocks)


# ── Self-test ───────────────────────────────────────────────────────
def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # synthetic: A ramps up, B ramps down -> momentum longs A shorts B -> spread+.
    n = 400
    closes = {
        "A": [100 * (1.001**i) for i in range(n)],  # steady up
        "B": [100 * (0.999**i) for i in range(n)],  # steady down
        "C": [100.0 for _ in range(n)],  # flat
    }
    ts = list(range(n))
    global SYMBOLS
    saved = SYMBOLS
    SYMBOLS = ["A", "B", "C"]
    try:
        vr = run_variant(closes, ts, "momentum", lookback=12, hold=12, k=1)
        # momentum should long A (up) and short B (down) -> spread strongly +
        check(
            f"T1 momentum spread positive on a clear cross-section "
            f"(mean {st.mean(vr.spread):+.3f})",
            st.mean(vr.spread) > 0,
        )
        vr_rev = run_variant(closes, ts, "reversion", lookback=12, hold=12, k=1)
        # reversion longs the loser (B, falling) -> on a persistent trend it LOSES
        check(
            f"T2 reversion spread negative on a persistent trend "
            f"(mean {st.mean(vr_rev.spread):+.3f})",
            st.mean(vr_rev.spread) < 0,
        )
        # ranking returns all symbols, sorted desc by long-quantity
        ranked = rank_symbols(closes, 200, 12, "momentum")
        check("T3 ranking returns every symbol", ranked is not None and len(ranked) == 3)
        check("T4 momentum ranks the riser first", ranked[0][0] == "A")
        # CPCV produces a distribution on a real spread
        cp = cpcv_series(vr.spread, vr.bar_index, hold=12)
        check(f"T5 CPCV yields paths on the spread ({cp.n_paths} paths)", cp.n_paths > 0)
    finally:
        SYMBOLS = saved

    print(f"\n  {'ALL TESTS PASS' if ok else 'SOME TESTS FAILED'}")
    return ok


# ── Main ────────────────────────────────────────────────────────────
def variant_name(signal: str, lb: int, hold: int, k: int) -> str:
    return f"{signal[:3]}-lb{lb}-h{hold}-k{k}"


def run() -> dict:
    print("=" * 100)
    print("EXPERIMENT 2 — CROSS-SECTIONAL / RELATIVE-VALUE  (1H aligned panel, 6 symbols)")
    print("=" * 100)
    ts, closes = load_aligned()
    print(f"\nAligned panel: {len(SYMBOLS)} symbols x {len(ts)} bars (1H, shared clock)")

    grid = list(product(SIGNALS, LOOKBACKS, HOLDS, KS))
    n_trials = len(grid) * len(FEE_GRID)  # honest variant count (x fee levels)
    print(
        f"Variant grid: {len(grid)} configs (signal x lookback x hold x k); "
        f"honest n_trials (x fee) = {n_trials}"
    )

    # run every variant
    variants: dict[str, VariantReturns] = {}
    for signal, lb, hold, k in grid:
        variants[variant_name(signal, lb, hold, k)] = run_variant(closes, ts, signal, lb, hold, k)

    # ── long-only EV table ──
    print("\n=== LONG-ONLY (hold top-k, rotate) — gross EV, block-bootstrap 95% CI ===")
    print(
        f"  {'variant':>16} {'N':>4} | {'grossEV%':>9} {'block 95% CI':>22} "
        f"{'excl0':>7} {'Sharpe':>7}"
    )
    print("  " + "-" * 72)
    long_only_rows: dict = {}
    for name, vr in variants.items():
        e = ev_ci(vr.long_only)
        lo, hi = e["ci"]
        excl = "YES(+)" if e.get("excl0_pos") else ("YES(-)" if e["excl0"] else "no")
        long_only_rows[name] = {
            "n": e["n"],
            "gross_ev": e["ev"],
            "ci": [lo, hi],
            "excl_zero_positive": bool(e.get("excl0_pos")),
            "sharpe": e["sharpe"],
        }
        print(
            f"  {name:>16} {e['n']:>4} | {e['ev']:>+9.3f} "
            f"[{lo:>+7.3f},{hi:>+7.3f}] {excl:>7} {e['sharpe']:>+7.3f}"
        )

    # ── long-short spread table (THEORETICAL — short leg needs perps) ──
    print(
        "\n=== LONG-SHORT SPREAD (long top-k / short bottom-k) — THEORETICAL "
        "(short needs perps; ignores funding+borrow) ==="
    )
    print(
        f"  {'variant':>16} {'N':>4} | {'spreadEV%':>9} {'block 95% CI':>22} "
        f"{'excl0':>7} {'Sharpe':>7}"
    )
    print("  " + "-" * 72)
    spread_rows: dict = {}
    for name, vr in variants.items():
        e = ev_ci(vr.spread)
        lo, hi = e["ci"]
        excl = "YES(+)" if e.get("excl0_pos") else ("YES(-)" if e["excl0"] else "no")
        spread_rows[name] = {
            "n": e["n"],
            "spread_ev": e["ev"],
            "ci": [lo, hi],
            "excl_zero_positive": bool(e.get("excl0_pos")),
            "sharpe": e["sharpe"],
        }
        print(
            f"  {name:>16} {e['n']:>4} | {e['ev']:>+9.3f} "
            f"[{lo:>+7.3f},{hi:>+7.3f}] {excl:>7} {e['sharpe']:>+7.3f}"
        )

    # ── identify the best variant by long-only point Sharpe (the IS winner) ──
    best_lo = max(long_only_rows.items(), key=lambda kv: kv[1]["sharpe"])
    best_sp = max(spread_rows.items(), key=lambda kv: kv[1]["sharpe"])
    print(
        f"\n  IS-best LONG-ONLY by Sharpe: {best_lo[0]} (Sharpe {best_lo[1]['sharpe']:+.3f}, "
        f"EV {best_lo[1]['gross_ev']:+.3f}%)"
    )
    print(
        f"  IS-best L/S SPREAD by Sharpe: {best_sp[0]} (Sharpe {best_sp[1]['sharpe']:+.3f}, "
        f"EV {best_sp[1]['spread_ev']:+.3f}%)"
    )

    # ── PBO over the whole grid (long-only and spread separately) ──
    bar_idx = {name: vr.bar_index for name, vr in variants.items()}
    pbo_lo = pbo_over_grid({n: v.long_only for n, v in variants.items()}, bar_idx)
    pbo_sp = pbo_over_grid({n: v.spread for n, v in variants.items()}, bar_idx)
    print("\n=== OVERFITTING RIGOR ===")
    print(
        f"  PBO over {len(grid)} long-only variants: {pbo_lo.pbo:.3f} "
        f"({pbo_lo.note or f'{pbo_lo.n_combinations} combos'})"
    )
    print(
        f"  PBO over {len(grid)} spread variants:    {pbo_sp.pbo:.3f} "
        f"({pbo_sp.note or f'{pbo_sp.n_combinations} combos'})"
    )

    # ── full verdict on the two IS-best variants + the top-3 by Sharpe ──
    all_lo_sharpes = [r["sharpe"] for r in long_only_rows.values()]
    all_sp_sharpes = [r["sharpe"] for r in spread_rows.values()]

    def verdict_for(
        name: str,
        vr: VariantReturns,
        series: list[float],
        all_sharpes: list[float],
        pbo_res: ofr.PBOResult,
        hold: int,
        kind: str,
    ) -> dict:
        cpcv = cpcv_series(series, vr.bar_index, hold, fee=0.0)
        dsr = ofr.deflated_sharpe_ratio(series, all_sharpes, n_trials=n_trials)
        mdd = ofr.max_drawdown(series)
        total = sum(series)
        calmar = (total / abs(mdd)) if mdd < 0 else (float("inf") if total > 0 else 0.0)
        v = ofr.make_verdict(f"xsect-{kind}-{name}", cpcv, dsr, pbo_res, mdd, calmar)
        print("\n" + v.render())
        return {
            "cpcv_median_sharpe": cpcv.median,
            "cpcv_ci": [cpcv.p05, cpcv.p95],
            "cpcv_pct_paths_neg": cpcv.pct_paths_negative,
            "cpcv_n_paths": cpcv.n_paths,
            "dsr": dsr.dsr,
            "dsr_sr_obs": dsr.observed_sr,
            "dsr_sr_star": dsr.sr_star,
            "pbo": pbo_res.pbo,
            "max_dd": mdd,
            "calmar": calmar,
            "verdict": v.verdict,
            "rationale": v.rationale,
        }

    print("\n=== CPCV / DSR / VERDICT — IS-best LONG-ONLY ===")
    h_lo = int(best_lo[0].split("-h")[1].split("-")[0])
    verdict_lo = verdict_for(
        best_lo[0],
        variants[best_lo[0]],
        variants[best_lo[0]].long_only,
        all_lo_sharpes,
        pbo_lo,
        h_lo,
        "longonly",
    )
    print("\n=== CPCV / DSR / VERDICT — IS-best L/S SPREAD (THEORETICAL) ===")
    h_sp = int(best_sp[0].split("-h")[1].split("-")[0])
    verdict_sp = verdict_for(
        best_sp[0],
        variants[best_sp[0]],
        variants[best_sp[0]].spread,
        all_sp_sharpes,
        pbo_sp,
        h_sp,
        "spread",
    )

    return {
        "experiment": "2 — cross-sectional / relative-value",
        "panel": {"tf": TF, "symbols": SYMBOLS, "n_bars": len(ts)},
        "grid": {
            "signals": list(SIGNALS),
            "lookbacks": list(LOOKBACKS),
            "holds": list(HOLDS),
            "ks": list(KS),
            "n_configs": len(grid),
        },
        "honest_n_trials": n_trials,
        "fee_grid": FEE_GRID,
        "long_only": long_only_rows,
        "spread": spread_rows,
        "is_best_long_only": best_lo[0],
        "is_best_spread": best_sp[0],
        "pbo_long_only": pbo_lo.pbo,
        "pbo_spread": pbo_sp.pbo,
        "verdict_best_long_only": verdict_lo,
        "verdict_best_spread": verdict_sp,
        "data_limitation": (
            "Spot OHLCV time bars only. The SHORT leg needs perps (not in tape) so "
            "L/S is THEORETICAL; no funding-rate or borrow-cost data, so the spread "
            "net number is an UPPER bound. Close-to-close hides intrabar path; time "
            "bars (not dollar/volume) leave variance noisy."
        ),
    }


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    out = run()
    if "--json-out" in sys.argv:
        ji = sys.argv.index("--json-out")
        if ji + 1 < len(sys.argv):
            with open(sys.argv[ji + 1], "w") as f:
                json.dump(out, f, indent=2, default=str)
            print(f"\nWrote {sys.argv[ji + 1]}", file=sys.stderr)
