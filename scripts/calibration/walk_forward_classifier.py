#!/usr/bin/env python3
"""Sprint 10 #7 — Walk-forward symbol×pattern classifier.

Per the 2026-05-27 swing-window finding: each symbol responds best to a
DIFFERENT pattern (trend-confluence vs oversold-bounce vs no-trade). The
per-symbol classification is data-derived but suffers selection bias if we
just pick the best-on-the-whole-window pattern.

Walk-forward defense:
  1. Split each symbol's 60d history into TRAIN (first 30d) and TEST (last 30d).
  2. On TRAIN: backtest each pattern; pick the best (by sum_pct, with min N=1).
  3. Apply that pick to TEST: measure the pattern's PnL on the held-out window.
  4. Compare TRAIN-picked-pattern vs TEST-realized: did the classification HOLD?

PRE-COMMIT INTERPRETATION (Op-1, written BEFORE running):
  - Router is SHIP-WORTHY iff:
    * Aggregate test-period sum (using train-picked patterns) ≥ 50% of
      train-period sum (i.e., degradation ≤ 50%)
    * Per-symbol: ≥ 60% of trained-positive symbols stay positive in test
    * The router universe (sum across both windows of picked patterns) ≥
      flat-pattern universe (trend_baseline alone) on the FULL window
  - Router is PROMISING iff one of the three holds
  - Router is REJECT if 0/3 hold (random-pick equivalent)

OUTPUT:
  - Per-symbol pick × train-sum × test-realized × delta
  - Aggregate train-sum vs test-realized
  - Comparison to flat universe-wide best pattern
  - Verdict block
"""
from __future__ import annotations

import datetime as dt
import json
import statistics as st
from dataclasses import dataclass
from pathlib import Path

import sys
sys.path.insert(0, "scripts/calibration")
from swing_window_validation import (
    ConfluenceParams,
    backtest_symbol,
    load_universe,
    Trade,
)

# 60-day window split at the midpoint
TRAIN_DAYS = 30
TEST_DAYS = 30


def slice_rows_by_window(rows: list[dict], start_ts_ms: int, end_ts_ms: int) -> list[dict]:
    return [r for r in rows if start_ts_ms <= r["ts"] < end_ts_ms]


@dataclass
class SymbolPick:
    symbol: str
    train_pattern: str
    train_n: int
    train_sum: float
    train_mean: float
    test_n: int
    test_sum: float
    test_mean: float
    delta_sum: float


def main() -> int:
    universe = load_universe()
    if not universe:
        print("No data. Run ingest_coingecko_solana_4h.py first.")
        return 1

    # Determine the 30/30 split anchored on each symbol's data end
    # (handles symbols with slightly different end times)
    patterns = {
        "trend": ConfluenceParams(name="trend", pattern="trend"),
        "trend_strict": ConfluenceParams(name="trend_strict", pattern="trend", adx_cross_up=30),
        "bounce": ConfluenceParams(name="bounce", pattern="bounce"),
        "no_trade": None,  # explicit no-trade option
    }

    print("=" * 110)
    print("WALK-FORWARD SYMBOL×PATTERN CLASSIFIER")
    print("=" * 110)
    print(f"Train: first {TRAIN_DAYS}d · Test: last {TEST_DAYS}d · Universe: {len(universe)} symbols")
    print()

    picks: list[SymbolPick] = []
    no_trade_syms: list[str] = []

    print(f"{'symbol':<10s} | {'train':<26s} | {'pick':<12s} | {'test (held-out)':<26s} | Δsum")
    print("-" * 110)

    train_picked_test_trades: dict[str, list[Trade]] = {}
    train_picked_train_trades: dict[str, list[Trade]] = {}

    for sym in sorted(universe.keys()):
        rows = universe[sym]
        if not rows:
            continue
        ts_start = rows[0]["ts"]
        ts_end = rows[-1]["ts"]
        full_days = (ts_end - ts_start) / 86400_000
        if full_days < 45:
            continue
        mid_ts = ts_start + int(86400_000 * TRAIN_DAYS)
        train_rows = slice_rows_by_window(rows, ts_start, mid_ts)
        test_rows = slice_rows_by_window(rows, mid_ts, ts_end + 1)
        if len(train_rows) < 40 or len(test_rows) < 40:
            continue

        # Score every pattern on TRAIN
        train_results = {}
        for pname, p in patterns.items():
            if p is None:
                train_results[pname] = ([], 0.0, 0.0)  # no_trade = 0
                continue
            ts_list = backtest_symbol(sym, train_rows, p)
            nets = [t.net_ret * 100 for t in ts_list]
            train_results[pname] = (ts_list, st.mean(nets) if nets else 0.0, sum(nets))

        # Pick best by train sum (no_trade = 0; never picked unless all negative)
        best_pname = max(train_results.keys(), key=lambda k: train_results[k][2])
        # If best is no_trade or even the best traded is negative, mark no_trade
        all_traded_negative = all(train_results[k][2] <= 0 for k in patterns if patterns[k] is not None)
        if all_traded_negative:
            best_pname = "no_trade"

        train_trades, train_mean, train_sum = train_results[best_pname]

        # Apply picked pattern to TEST
        if best_pname == "no_trade":
            test_trades, test_mean, test_sum = [], 0.0, 0.0
            no_trade_syms.append(sym)
        else:
            test_trades_list = backtest_symbol(sym, test_rows, patterns[best_pname])
            test_nets = [t.net_ret * 100 for t in test_trades_list]
            test_trades = test_trades_list
            test_mean = st.mean(test_nets) if test_nets else 0.0
            test_sum = sum(test_nets)

        delta = test_sum - train_sum

        # Format train + test cells
        tr_cell = (
            f"n={len(train_trades):>2d} mean={train_mean:>+5.2f}% sum={train_sum:>+6.2f}%"
            if best_pname != "no_trade"
            else "all-patterns-negative"
        )
        te_cell = (
            f"n={len(test_trades):>2d} mean={test_mean:>+5.2f}% sum={test_sum:>+6.2f}%"
            if best_pname != "no_trade"
            else "(none — no trades by design)"
        )

        print(f"{sym:<10s} | {tr_cell:<26s} | {best_pname:<12s} | {te_cell:<26s} | {delta:>+6.2f}pp")

        if best_pname != "no_trade":
            train_picked_train_trades[sym] = train_trades
            train_picked_test_trades[sym] = test_trades

        picks.append(SymbolPick(
            symbol=sym,
            train_pattern=best_pname,
            train_n=len(train_trades),
            train_sum=train_sum,
            train_mean=train_mean,
            test_n=len(test_trades),
            test_sum=test_sum,
            test_mean=test_mean,
            delta_sum=delta,
        ))

    print()
    # ── Aggregate router performance ──
    print("=" * 110)
    print("AGGREGATE ROUTER PERFORMANCE")
    print("=" * 110)
    traded_picks = [p for p in picks if p.train_pattern != "no_trade"]
    router_train_sum = sum(p.train_sum for p in traded_picks)
    router_test_sum = sum(p.test_sum for p in traded_picks)
    train_positive_syms = [p for p in traded_picks if p.train_sum > 0]
    test_positive_after_pick = [p for p in train_positive_syms if p.test_sum > 0]
    print(f"  Symbols routed (non-no_trade): {len(traded_picks)} of {len(picks)}")
    print(f"  Symbols routed to no_trade:    {len(no_trade_syms)}  → {no_trade_syms}")
    print(f"  Router TRAIN sum:              {router_train_sum:+.2f}%")
    print(f"  Router TEST sum (held-out):    {router_test_sum:+.2f}%")
    if router_train_sum > 0:
        degradation = 100 * (router_train_sum - router_test_sum) / router_train_sum
        print(f"  Degradation TRAIN→TEST:        {degradation:+.0f}% (positive = lost EV out-of-sample)")
    train_n = sum(p.train_n for p in traded_picks)
    test_n = sum(p.test_n for p in traded_picks)
    print(f"  Total trades:                  train={train_n}, test={test_n}")
    print(f"  Train-positive symbols:        {len(train_positive_syms)}")
    print(f"  ...that stayed positive in test: {len(test_positive_after_pick)}  "
          f"({100*len(test_positive_after_pick)/max(len(train_positive_syms),1):.0f}%)")
    print()

    # ── Comparison: router vs flat best (trend_baseline applied to all) ──
    print("=" * 110)
    print("ROUTER vs FLAT (trend on all symbols, test window only)")
    print("=" * 110)
    flat_test_sum = 0.0
    flat_test_n = 0
    for sym, rows in universe.items():
        ts_start = rows[0]["ts"]
        ts_end = rows[-1]["ts"]
        full_days = (ts_end - ts_start) / 86400_000
        if full_days < 45:
            continue
        mid_ts = ts_start + int(86400_000 * TRAIN_DAYS)
        test_rows = slice_rows_by_window(rows, mid_ts, ts_end + 1)
        if len(test_rows) < 40:
            continue
        ts_list = backtest_symbol(sym, test_rows, patterns["trend"])
        flat_test_sum += sum(t.net_ret * 100 for t in ts_list)
        flat_test_n += len(ts_list)
    print(f"  ROUTER test sum:               {router_test_sum:+.2f}%  (n={test_n})")
    print(f"  FLAT (trend all) test sum:     {flat_test_sum:+.2f}%  (n={flat_test_n})")
    print(f"  Router edge over flat:         {router_test_sum - flat_test_sum:+.2f}pp")
    print()

    # ── Per-symbol stability table ──
    print("=" * 110)
    print("PER-SYMBOL STABILITY")
    print("=" * 110)
    stable = 0
    flipped = 0
    for p in traded_picks:
        if p.train_sum > 0 and p.test_sum > 0:
            tag = "STABLE+"
            stable += 1
        elif p.train_sum > 0 and p.test_sum < 0:
            tag = "FLIPPED-"
            flipped += 1
        elif p.train_sum < 0 and p.test_sum > 0:
            tag = "FLIPPED+"
            flipped += 1
        else:
            tag = "STABLE-"
            stable += 1
        # only print non-trivial
        if abs(p.train_sum) >= 0.5 or abs(p.test_sum) >= 0.5:
            print(f"  {p.symbol:<10s} pick={p.train_pattern:<12s}  train {p.train_sum:>+6.2f}%  test {p.test_sum:>+6.2f}%  {tag}")
    print(f"\n  STABLE: {stable} symbols | FLIPPED: {flipped}")
    print()

    # ── Verdict ──
    print("=" * 110)
    print("VERDICT (per pre-commit interpretation)")
    print("=" * 110)
    gate1_pass = router_test_sum >= router_train_sum * 0.5 if router_train_sum > 0 else False
    gate2_pass = len(test_positive_after_pick) >= 0.6 * len(train_positive_syms) if train_positive_syms else False
    gate3_pass = router_test_sum > flat_test_sum
    gates = [
        ("test_sum ≥ 50% of train_sum (degradation ≤ 50%)", gate1_pass),
        ("≥ 60% of train-positive symbols stay positive in test", gate2_pass),
        ("router test_sum > flat-pattern (trend_baseline) test_sum", gate3_pass),
    ]
    for desc, ok in gates:
        print(f"  [{('PASS' if ok else 'FAIL')}]  {desc}")
    n_pass = sum(1 for _, ok in gates if ok)
    if n_pass == 3:
        verdict = "SHIP-WORTHY (router validated walk-forward; proceed to paper A/B)"
    elif n_pass == 2:
        verdict = "PROMISING — refine cut on edges before live"
    elif n_pass == 1:
        verdict = "WEAK — only 1 gate; selection bias likely dominates"
    else:
        verdict = "REJECT — picks degrade out-of-sample; classification is overfitting"
    print(f"\n  → VERDICT: {verdict}")

    # Save artifacts
    out_dir = Path("analysis/data/walk_forward")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "picks.json").write_text(json.dumps([
        {
            "symbol": p.symbol,
            "train_pattern": p.train_pattern,
            "train_n": p.train_n,
            "train_sum": p.train_sum,
            "train_mean": p.train_mean,
            "test_n": p.test_n,
            "test_sum": p.test_sum,
            "test_mean": p.test_mean,
            "delta_sum": p.delta_sum,
        }
        for p in picks
    ], indent=2))
    print(f"\nSaved → {out_dir}/picks.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
