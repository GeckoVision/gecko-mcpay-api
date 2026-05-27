#!/usr/bin/env python3
"""UNIVERSE-EXPANSION cross-sectional carry — Binance 50-coin × weekly, realistic basis.

Sprint 4 deliverable per private/strategy/2026-05-26-carry-universe-prereg.md.
Extends carry_realistic_validation.py from the HL 10-coin universe to the
Binance USDT-perp 50-coin universe frozen at ingest-time (data/binance_universe.json).

The single hypothesis (verbatim from the pre-reg):
    On a 50-perp Binance universe with realistic basis tracking, the same
    weekly cross-sectional carry (K=3 short top funding / K=3 long bottom
    funding, weekly rebalance, 0.20%/flip cost) clears the default-REJECT
    bar (CI excludes 0, DSR>=0.95, PBO<0.20, %paths<0<25%, Calmar>0) net
    of costs.

What's different from the HL realistic harness:
  - Universe: 50 Binance perps (loaded from binance_universe.json, frozen
    once at ingest-time per pre-reg's survivorship-bias caveat) vs HL 10.
  - Funding cadence: Binance native 8h (3 events/day) vs HL hourly.
    -> EVENTS_YR = 3 * 365 = 1095 (vs HL 8760).
    -> W (trailing window + rebalance) = 21 8h-events = 1 week (vs HL 168).
  - Basis hedge: real Binance USDT-spot OHLCV at funding-event ts (vs HL's
    spot = perp_close / (1 + premium) approximation). Same forward-fill
    pattern (leakage-safe: only fully-CLOSED 4h bars).
  - n_trials for DSR remains 1 per the pre-reg: K=3, weekly cadence, 0.20%
    cost are REUSED VERBATIM from the HL realistic pre-reg (locked
    parameters, not re-searched). The only new degree of freedom is
    universe-size=50 on Binance, which IS the single pre-registered
    widening. Meta-count of universe-size experiments across pre-regs is 2
    (10-HL realistic + 50-Binance universe); flagged in the verdict block
    for transparency but does NOT inflate n_trials for this harness.

Run:
  uv run python scripts/calibration/carry_universe_validation.py
                                              [--k 3] [--flip-cost 0.002]
                                              [--coins SYM1,SYM2,...]
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import carry_xsectional_validation as cx  # noqa: E402  reuse block_ci/cpcv_on/pbo_by_coin
import overfitting_rigor as ofr  # noqa: E402

# ── Layout ──────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(_HERE, "data")
UNIVERSE_PATH = os.path.join(DATA_DIR, "binance_universe.json")
FUND_DIR = os.path.join(DATA_DIR, "funding", "binance")
PERP_DIR = os.path.join(DATA_DIR, "perp", "binance")
SPOT_DIR = os.path.join(DATA_DIR, "spot", "binance")

# ── Strategy constants ──────────────────────────────────────────────────
DEFAULT_K = 3
DEFAULT_FLIP_COST = 0.002
EVENTS_YR = 3 * 365  # Binance funding cadence is 8h => 3 events/day
W = 21  # 21 8h-events = 1 week (trailing window + rebalance period)
KAMINO_BENCHMARK_APY_PCT = 6.5  # the §7 Checkpoint D gate 6 floor


# ── Universe loading ────────────────────────────────────────────────────
def load_universe(coin_filter: list[str] | None = None) -> list[dict]:
    """Load the frozen Binance universe. Filter to ``coin_filter`` if given
    (subset for testing); does NOT mutate the cached universe file."""
    if not os.path.exists(UNIVERSE_PATH):
        raise FileNotFoundError(
            f"frozen universe missing at {UNIVERSE_PATH}; "
            "run `uv run python scripts/calibration/ccxt_spine.py --pick-universe --n 50` first"
        )
    with open(UNIVERSE_PATH) as f:
        u = json.load(f)
    ranking = u.get("ranking") or []
    if coin_filter is not None:
        filt = {c.strip().upper() for c in coin_filter}
        ranking = [e for e in ranking if e.get("symbol") in filt]
    return ranking


# ── Leakage-safe forward-fill ───────────────────────────────────────────
def _bar_at(
    ts_sorted: list[int], bar_dict: dict[int, float], interval_ms: int, t: int
) -> float | None:
    """Return the close of the bar whose [open, open + interval_ms] window
    has CLOSED by ts ``t``. Leakage-safe: never peeks at an unclosed bar.
    O(log n) via bisect."""
    target = t - interval_ms  # last bar_open with close <= t
    idx = bisect.bisect_right(ts_sorted, target) - 1
    if idx < 0:
        return None
    return bar_dict[ts_sorted[idx]]


# ── Per-coin leg input loader ───────────────────────────────────────────
def load_leg_inputs(
    coin_filter: list[str] | None = None,
) -> tuple[dict[str, dict[int, tuple[float, float, float]]], list[dict]]:
    """For each coin in the universe with all three data files present:
    return ``{ts: (funding, perp_ret, spot_ret)}`` on the funding-event grid.

    perp_ret + spot_ret are forward-filled from the most recently CLOSED 4h
    candle on each leg (perp and spot use INDEPENDENT close-windows; Binance
    USDT-perp and Binance USDT-spot trade continuously but candle boundaries
    can drift modulo venue-side aggregation).

    Returns (legs, available_universe) where available_universe is the
    subset of the frozen universe that has all three files on disk.
    """
    available: list[dict] = []
    out: dict[str, dict[int, tuple[float, float, float]]] = {}
    for entry in load_universe(coin_filter):
        sym = entry["symbol"]
        fp = os.path.join(FUND_DIR, f"{sym}_funding.json")
        pp = os.path.join(PERP_DIR, f"{sym}_perp.json")
        sp = os.path.join(SPOT_DIR, f"{sym}_spot.json")
        if not (os.path.exists(fp) and os.path.exists(pp) and os.path.exists(sp)):
            continue
        with open(fp) as f:
            fund_rows = json.load(f)
        with open(pp) as f:
            perp_rows = json.load(f)
        with open(sp) as f:
            spot_rows = json.load(f)
        fund = {int(r["ts"]): float(r["fundingRate"]) for r in fund_rows}
        perp = {int(r["ts"]): float(r["close"]) for r in perp_rows if r.get("close")}
        spot = {int(r["ts"]): float(r["close"]) for r in spot_rows if r.get("close")}
        if len(fund) < W or len(perp) < 3 or len(spot) < 3:
            continue
        perp_ts = sorted(perp)
        spot_ts = sorted(spot)
        # Infer interval from median spacing (handles 1h / 4h candles).
        def _infer_interval(ts_sorted: list[int]) -> int:
            gaps = sorted(
                ts_sorted[i] - ts_sorted[i - 1]
                for i in range(1, min(50, len(ts_sorted)))
            )
            mid = gaps[len(gaps) // 2] if gaps else 0
            return int(mid) or 4 * 3_600_000
        perp_iv = _infer_interval(perp_ts)
        spot_iv = _infer_interval(spot_ts)
        # Intersect funding times that have a valid forward-filled bar on BOTH legs
        # at the current ts AND the prior funding ts (we need a prior close to
        # compute a return).
        fund_ts_sorted = sorted(
            t
            for t in fund
            if t >= max(perp_ts[0], spot_ts[0]) + 2 * max(perp_iv, spot_iv)
        )
        rec: dict[int, tuple[float, float, float]] = {}
        for i in range(1, len(fund_ts_sorted)):
            t, tp = fund_ts_sorted[i], fund_ts_sorted[i - 1]
            pc = _bar_at(perp_ts, perp, perp_iv, t)
            pc_prev = _bar_at(perp_ts, perp, perp_iv, tp)
            sc = _bar_at(spot_ts, spot, spot_iv, t)
            sc_prev = _bar_at(spot_ts, spot, spot_iv, tp)
            if not all(x and x > 0 for x in (pc, pc_prev, sc, sc_prev)):
                continue
            perp_ret = (pc - pc_prev) / pc_prev
            spot_ret = (sc - sc_prev) / sc_prev
            rec[t] = (fund[t], perp_ret, spot_ret)
        if not rec:
            continue
        out[sym] = rec
        available.append(entry)
    return out, available


# ── Cross-sectional weekly book ─────────────────────────────────────────
def build(
    legs: dict[str, dict[int, tuple[float, float, float]]],
    k: int,
    flip_cost: float,
) -> tuple[list[float], dict[str, list[tuple[int, float]]]]:
    """Same shape as carry_realistic_validation.build but generalised to the
    50-coin Binance universe + 8h event grid (W=21 instead of HL's 168)."""
    all_ts = sorted({t for d in legs.values() for t in d})
    port: list[float] = []
    per_coin: dict[str, list[tuple[int, float]]] = {c: [] for c in legs}
    prev_book: dict[str, int] = {}
    i = W
    while i < len(all_ts):
        wk_ts = all_ts[i : i + W]
        prior = list(all_ts[max(0, i - W) : i])
        means: dict[str, float] = {}
        for c, d in legs.items():
            vals = [d[t][0] for t in prior if t in d]
            if len(vals) >= W // 2:
                means[c] = st.mean(vals)
        ranked = sorted(means.items(), key=lambda kv: kv[1])
        if len(ranked) < 2 * k:
            i += W
            continue
        book: dict[str, int] = {}
        for c, _ in ranked[-k:]:
            book[c] = +1  # short top positive funding
        for c, _ in ranked[:k]:
            book[c] = -1  # long bottom (negative) funding
        for h_idx, t in enumerate(wk_ts):
            leg_rets: list[float] = []
            for c, mult in book.items():
                if t not in legs[c]:
                    continue
                fr, perp_ret, spot_ret = legs[c][t]
                r = mult * (fr - (perp_ret - spot_ret))
                if h_idx == 0 and (c not in prev_book or prev_book[c] != mult):
                    r -= flip_cost
                leg_rets.append(r)
                per_coin[c].append((t, r))
            if leg_rets:
                port.append(st.mean(leg_rets))
        prev_book = book
        i += W
    return port, per_coin


# ── PBO partition-strategy sweep (Sprint 4.5) ──────────────────────────
# Pre-commit interpretation lives at
# private/strategy/2026-05-26-carry-universe-pbo-finer-partition-precommit.md
# — names DEPLOY/PAPER ONLY/REJECT actions per branch BEFORE any variant runs.
#
# All four strategies share the same partition AXIS (contiguous time blocks);
# the only thing that varies is the number of bins. Per the pre-commit, NO
# OTHER STRATEGIES may be added after seeing the results — that's the textbook
# overfitting move the rigor stack is designed to catch.
PBO_PARTITION_STRATEGIES: dict[str, int] = {
    "time_10": 10,  # current default — baseline
    "time_20": 20,  # finer — tests week-to-week consistency
    "time_5": 5,    # coarser sanity check — floor
    "walk_forward_2": 2,  # extreme — pure walk-forward (1st year IS vs 2nd year OOS)
}


def pbo_sweep(per_coin: dict[str, list[tuple[int, float]]]) -> dict[str, dict]:
    """Run pbo_by_coin under each strategy in PBO_PARTITION_STRATEGIES; return
    ``{name: {pbo, n_combinations, n_variants, median_logit, note}}``. Used by
    render_verdict so the verdict block can show all four side-by-side.

    Progressive print on each variant completion (stdout flushed) so the
    operator sees partial results before the slow variants land. The
    GECKO_PBO_SKIP_SLOW=1 env flag skips variants whose n_bins >= 16 (i.e.
    `time_20`) — for fast iteration when only the cheaper variants are
    needed. The skipped variant lands as a skip entry in the output dict.
    """
    import time as _time
    skip_slow = os.environ.get("GECKO_PBO_SKIP_SLOW", "").strip().lower() in ("1", "true", "yes")
    out: dict[str, dict] = {}
    for name, n_bins in PBO_PARTITION_STRATEGIES.items():
        if skip_slow and n_bins >= 16:
            print(f"  [pbo_sweep] {name:18s} n_bins={n_bins:3d} SKIPPED (GECKO_PBO_SKIP_SLOW=1)", flush=True)
            out[name] = {
                "pbo": float("nan"),
                "n_combinations": 0,
                "n_variants": 0,
                "median_logit": float("nan"),
                "note": "skipped (GECKO_PBO_SKIP_SLOW=1)",
                "n_bins": n_bins,
            }
            continue
        print(f"  [pbo_sweep] {name:18s} n_bins={n_bins:3d} running...", flush=True)
        t0 = _time.time()
        try:
            res = cx.pbo_by_coin(per_coin, n_bins=n_bins)
        except Exception as exc:
            elapsed = _time.time() - t0
            print(f"  [pbo_sweep] {name:18s} ERR after {elapsed:.1f}s: {type(exc).__name__}: {exc}", flush=True)
            out[name] = {
                "pbo": float("nan"),
                "n_combinations": 0,
                "n_variants": 0,
                "median_logit": float("nan"),
                "note": f"err: {type(exc).__name__}: {exc}",
                "n_bins": n_bins,
            }
            continue
        elapsed = _time.time() - t0
        print(
            f"  [pbo_sweep] {name:18s} n_bins={n_bins:3d} PBO={res.pbo:.4f} "
            f"(n_combos={res.n_combinations:>6d}) in {elapsed:.1f}s",
            flush=True,
        )
        out[name] = {
            "pbo": res.pbo,
            "n_combinations": res.n_combinations,
            "n_variants": res.n_variants,
            "median_logit": res.median_logit,
            "note": res.note,
            "n_bins": n_bins,
        }
    return out


def pbo_branch(pbo_sweep_result: dict[str, dict], threshold: float = 0.20) -> str:
    """Classify the sweep against the pre-committed branches A/B/C.

    Returns one of:
      - "A_all_pass" — every variant cleared < threshold → upgrade to DEPLOY
      - "B_mixed_b1_walkforward_only_fails" — only walk_forward_2 fails
      - "B_mixed_b2_time20_only_fails" — only time_20 fails
      - "B_mixed_b3_time5_only_fails" — only time_5 fails (anomalous)
      - "B_mixed_other" — some other mixed pattern (PAPER ONLY + investigate)
      - "C_all_fail" — every variant ≥ threshold → close lane
    """
    def passes(name: str) -> bool:
        v = pbo_sweep_result.get(name, {}).get("pbo")
        return isinstance(v, (int, float)) and v == v and v < threshold

    pass_set = {n for n in PBO_PARTITION_STRATEGIES if passes(n)}
    fail_set = set(PBO_PARTITION_STRATEGIES) - pass_set
    if len(pass_set) == len(PBO_PARTITION_STRATEGIES):
        return "A_all_pass"
    if len(fail_set) == len(PBO_PARTITION_STRATEGIES):
        return "C_all_fail"
    if fail_set == {"walk_forward_2"}:
        return "B_mixed_b1_walkforward_only_fails"
    if fail_set == {"time_20"}:
        return "B_mixed_b2_time20_only_fails"
    if fail_set == {"time_5"}:
        return "B_mixed_b3_time5_only_fails"
    return "B_mixed_other"


# ── Verdict block ───────────────────────────────────────────────────────
def render_verdict(
    *,
    k: int,
    flip_cost: float,
    universe: list[dict],
    available: list[dict],
    port: list[float],
    per_coin: dict[str, list[tuple[int, float]]],
) -> dict:
    """Compute the structured verdict per quant-backtest-rigor §6. Returns a
    dict suitable for JSON output + a `text` field with the human-readable
    block."""
    if len(port) < 2:
        return {
            "verdict": "REJECT",
            "rationale": "insufficient_data (port_n < 2)",
            "text": "  insufficient data — REJECT",
        }
    mean_e, lo_e, hi_e = cx.block_ci(port)
    # Annualize per-event mean by EVENTS_YR (3 * 365 = 1095) instead of HL's
    # HOURS_YR (8760). Same conversion math — different cadence.
    ann_pct = mean_e * EVENTS_YR * 100
    ann_lo_pct = lo_e * EVENTS_YR * 100
    ann_hi_pct = hi_e * EVENTS_YR * 100
    sd = st.pstdev(port)
    shp = (mean_e / sd * math.sqrt(EVENTS_YR)) if sd > 0 else 0.0
    mdd = ofr.max_drawdown(port)
    cum = sum(port)
    calmar = (cum / abs(mdd)) if mdd < 0 else float("inf")
    cpcv = cx.cpcv_on(port)
    dsr = ofr.deflated_sharpe_ratio(port, [ofr.sharpe_ratio(port)], n_trials=1)
    pbo = cx.pbo_by_coin(per_coin)
    # Sprint 4.5: sweep PBO under 4 partition-granularity variants. The default
    # `pbo` above stays as the headline gate; the sweep adds the granularity
    # sensitivity analysis. Per pre-commit interpretation (Op-1), branch
    # classification follows the verbatim rules in
    # private/strategy/2026-05-26-carry-universe-pbo-finer-partition-precommit.md
    pbo_sweep_result = pbo_sweep(per_coin)
    pbo_branch_label = pbo_branch(pbo_sweep_result, threshold=0.20)

    gates = {
        "net carry CI excludes 0 (lower bound > 0)": lo_e > 0,
        "DSR >= 0.95": dsr.dsr >= 0.95,
        "PBO < 0.20": (pbo.pbo == pbo.pbo) and pbo.pbo < 0.20,
        "%CPCV-paths Sharpe<0 < 25%": cpcv.pct_paths_negative < 0.25,
        "tail OK (Calmar > 0 AND maxDD < 0)": mdd < 0 and calmar > 0,
        f"net APY beats Kamino {KAMINO_BENCHMARK_APY_PCT}% floor": ann_pct > KAMINO_BENCHMARK_APY_PCT,
    }
    all_rigor_pass = all(v for k_, v in gates.items() if k_ != f"net APY beats Kamino {KAMINO_BENCHMARK_APY_PCT}% floor")
    beats_kamino = ann_pct > KAMINO_BENCHMARK_APY_PCT
    if all_rigor_pass and beats_kamino:
        verdict = "DEPLOY"
    elif ann_pct > 0 and lo_e > 0:
        verdict = "PAPER ONLY"
    else:
        verdict = "REJECT"

    rationale_parts: list[str] = []
    for gname, gpass in gates.items():
        if not gpass:
            rationale_parts.append(f"FAIL: {gname}")
    if not rationale_parts:
        rationale_parts.append("ALL gates pass")

    text_lines: list[str] = []
    text_lines.append("=" * 96)
    text_lines.append(
        f"UNIVERSE-EXPANSION CARRY (Binance USDT-perp, K={k} short-top/long-bottom, "
        f"weekly, realistic basis, flip={flip_cost * 100:.2f}%)"
    )
    text_lines.append(
        f"  universe frozen: {len(universe)} coins;  with all 3 data files: "
        f"{len(available)} coins;  portfolio events: {len(port)}"
    )
    text_lines.append("=" * 96)
    text_lines.append("")
    text_lines.append("PRIMARY METRICS:")
    text_lines.append(
        f"  net carry annualized:      {ann_pct:+.3f}%  "
        f"95% CI [{ann_lo_pct:+.3f}%, {ann_hi_pct:+.3f}%]  excludes 0 (+): {lo_e > 0}"
    )
    text_lines.append(f"  annualized Sharpe:         {shp:+.3f}")
    text_lines.append(
        f"  CPCV median Sharpe:        {cpcv.median:+.3f}  "
        f"%paths<0={cpcv.pct_paths_negative:.1%}"
    )
    text_lines.append(f"  Deflated Sharpe Ratio:     {dsr.dsr:.3f}  (threshold >= 0.95)")
    text_lines.append(
        f"  PBO:                       {pbo.pbo:.3f}  (threshold < 0.20)"
    )
    text_lines.append(f"  PBO sweep (Sprint 4.5, finer-partition):")
    for sweep_name, sweep_r in pbo_sweep_result.items():
        v = sweep_r["pbo"]
        status = (
            "PASS" if (isinstance(v, (int, float)) and v == v and v < 0.20)
            else "FAIL" if (isinstance(v, (int, float)) and v == v and v >= 0.20)
            else "NaN"
        )
        bins = sweep_r["n_bins"]
        combos = sweep_r["n_combinations"]
        v_str = f"{v:.3f}" if (isinstance(v, (int, float)) and v == v) else "nan"
        text_lines.append(
            f"    {sweep_name:18s} (n_bins={bins:3d}, combos={combos:>6d}) → PBO={v_str}  [{status}]"
        )
    text_lines.append(f"  pre-commit branch classification: {pbo_branch_label}")
    text_lines.append(
        f"  Max DD (cumulative):       {mdd * 100:+.3f}%   Calmar: {calmar:+.3f}"
    )
    text_lines.append(
        f"  Kamino benchmark:          modeled net APY {ann_pct:+.2f}% vs ~{KAMINO_BENCHMARK_APY_PCT}% Kamino floor "
        f"({'BEATS' if beats_kamino else 'DOES NOT BEAT'})"
    )
    text_lines.append("")
    text_lines.append(f"GATES (default-REJECT):")
    for gname, gpass in gates.items():
        text_lines.append(f"  [{'PASS' if gpass else 'FAIL'}] {gname}")
    text_lines.append("")
    text_lines.append(f"VERDICT: {verdict}")
    text_lines.append(f"RATIONALE: {'; '.join(rationale_parts)}")
    text_lines.append("")
    text_lines.append(
        f"  meta n_trials note: this pre-reg uses n_trials=1 honestly (K/cadence/cost "
        f"REUSED verbatim from the HL realistic pre-reg). The meta-count of "
        f"universe-size experiments across pre-regs is 2 (HL-10 + Binance-50); "
        f"if the founder wants a more conservative DSR for the meta-test, re-run with "
        f"n_trials=2 in deflated_sharpe_ratio(...). For this pre-reg the answer to "
        f"'is THIS configuration's edge real on THIS universe' is n_trials=1."
    )
    text_lines.append("=" * 96)

    return {
        "verdict": verdict,
        "rationale": "; ".join(rationale_parts),
        "k": k,
        "flip_cost": flip_cost,
        "universe_frozen_n": len(universe),
        "universe_with_data_n": len(available),
        "portfolio_events": len(port),
        "mean_per_event": mean_e,
        "annualized_pct": ann_pct,
        "annualized_ci_pct": [ann_lo_pct, ann_hi_pct],
        "annualized_sharpe": shp,
        "pbo_sweep": pbo_sweep_result,
        "pbo_branch": pbo_branch_label,
        "cpcv_median_sharpe": cpcv.median,
        "cpcv_pct_paths_negative": cpcv.pct_paths_negative,
        "dsr": dsr.dsr,
        "dsr_n_trials": 1,
        "pbo": pbo.pbo,
        "max_drawdown_cum": mdd,
        "calmar": calmar,
        "kamino_benchmark_apy_pct": KAMINO_BENCHMARK_APY_PCT,
        "kamino_benchmark_beaten": beats_kamino,
        "gates": gates,
        "text": "\n".join(text_lines),
    }


# ── Run ─────────────────────────────────────────────────────────────────
def run(
    k: int, flip_cost: float, coin_filter: list[str] | None, out_json: str | None
) -> dict:
    legs, available = load_leg_inputs(coin_filter)
    universe = load_universe(coin_filter)
    port, per_coin = build(legs, k, flip_cost)
    verdict = render_verdict(
        k=k,
        flip_cost=flip_cost,
        universe=universe,
        available=available,
        port=port,
        per_coin=per_coin,
    )
    print(verdict["text"])
    if out_json:
        os.makedirs(os.path.dirname(out_json), exist_ok=True)
        with open(out_json, "w") as f:
            json.dump({k: v for k, v in verdict.items() if k != "text"}, f, indent=2, default=str)
        print(f"\nJSON written to {out_json}")
    return verdict


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--flip-cost", type=float, default=DEFAULT_FLIP_COST)
    ap.add_argument("--coins", default=None, help="Comma-separated subset for testing")
    ap.add_argument(
        "--out",
        default=os.path.join(_HERE, "..", "..", "private", "strategy", "carry_universe_report.json"),
        help="Path to write the JSON verdict",
    )
    a = ap.parse_args()
    coin_filter = [c.strip().upper() for c in a.coins.split(",")] if a.coins else None
    run(a.k, a.flip_cost, coin_filter, a.out)


if __name__ == "__main__":
    _cli()
