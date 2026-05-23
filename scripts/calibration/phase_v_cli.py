#!/usr/bin/env python3
"""Phase V — validation-spine CLI + real-data smoke run (quant-analyst, 2026-05-23).

Runs the FULL V.1/V.2 pipeline end-to-end on the SAME cached windows the V.0
fee-sensitivity script uses, for a trivial demo feature, and prints the
AcceptanceVerdict. This confirms the spine runs on REAL cached data, not only on
synthetic unit tests.

PIPELINE (per window)
  1. enrich each symbol's candles (chart_floor_calibration.enrich) — adds the
     indicator columns the regime classifier needs.
  2. for every full-horizon bar, build a Sample: feature score (computed STRICTLY
     on candles[:i+1]), realized forward return via the bot's REAL close-based
     exit stack (exit_reconciliation.simulate_exit_real_close), and the regime
     (chart_floor_calibration.regime_at — the existing classifier).
  3. select the "act" trades (top-tercile feature score) and compute net/gross.
  4. register the hypothesis in the pre-registration ledger, then run
     acceptance_gate.evaluate_feature with the full leakage-trap sample set, the
     selected-trade returns, and the per-symbol walk-forward samples.
  5. print the per-gate verdict (default REJECT).

The demo feature is the leakage-CLEAN MomentumFeature (trailing 3-bar return).
On this quiet chop-heavy tape it is EXPECTED to be REJECTED (the roadmap's whole
finding is that momentum is anti-predictive here) — a real demonstration that the
skeptic harness does its job, not a rigged accept.

READ-ONLY w.r.t. the live bot (port 8265 — never touched). Free: cached candles.

Usage:
    python3 scripts/calibration/phase_v_cli.py \
        --w1 /tmp/cal_candles_d1.json --w2 /tmp/cal_candles.json \
        --regime trend --json-out /tmp/phase_v_smoke.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import acceptance_gate as ag
import chart_floor_calibration as cf
import exit_reconciliation as er
import feature_validation as fv
import walkforward_validation as wfv

FEE_RT = ag.DEFAULT_FEE_RT  # 0.5% round trip (Phoenix/Jupiter-band default)


def build_samples(raw: dict, feature: fv.Feature) -> dict:
    """From raw {sym: [candle,...]}, build the aligned arrays the evaluator needs.

    Returns a dict with: candles (the LAST symbol's enriched dict, used only as
    the trap-recompute target — traps run per-symbol below), and per-symbol
    sample streams pooled into flat aligned lists. To keep the leakage trap
    causal-recompute correct we run it per symbol and AND the results."""
    data = {sym: cf.enrich(cs) for sym, cs in raw.items() if len(cs) >= 60}
    # per-symbol candidate streams (every full-horizon bar from WARMUP on)
    per_symbol: dict[str, dict] = {}
    all_samples: list[wfv.Sample] = []
    for sym, c in data.items():
        n = len(c["close"])
        idxs, fwd, scores, regimes = [], [], [], []
        for i in range(cf.WARMUP, n):
            if not cf.has_full_horizon(c, i):
                continue
            idxs.append(i)
            ret = er.simulate_exit_real_close(c, i)  # realized gross % (REAL exit)
            fwd.append(ret)
            scores.append(feature.compute(c, i))
            rg = cf.regime_at(c, i)
            regimes.append(rg)
            all_samples.append(wfv.Sample(sym, i, feature.compute(c, i), ret, rg))
        per_symbol[sym] = {
            "candles": c,
            "idxs": idxs,
            "fwd": fwd,
            "scores": scores,
            "regimes": regimes,
        }
    return {"data": data, "per_symbol": per_symbol, "all_samples": all_samples}


def leakage_clean_all_symbols(feature: fv.Feature, per_symbol: dict) -> bool:
    """Run the structural lookahead trap per symbol (each symbol is its own causal
    series) and AND the results — a single forward-peek anywhere fails it."""
    return all(fv.lookahead_clean(feature, ps["candles"], ps["idxs"]) for ps in per_symbol.values())


def run_window(label: str, raw: dict, declared_regime: str, ledger: ag.PreRegistrationLedger):
    feature = fv.MomentumFeature(k=3)  # the trivial, leakage-CLEAN demo feature
    built = build_samples(raw, feature)
    per_symbol = built["per_symbol"]
    all_samples = built["all_samples"]

    # restrict to the declared regime for the EV / OOS gates
    regime_samples = [s for s in all_samples if s.regime == declared_regime]

    # build the FULL trap-aligned arrays (pool all symbols; trap is per-symbol but
    # the evaluator's trap call needs one candles dict — we pass the largest symbol
    # and ALSO short-circuit via leakage_clean_all_symbols for the structural check).
    # To keep the evaluator's single-candles trap meaningful we run on each symbol.
    look_clean = leakage_clean_all_symbols(feature, per_symbol)

    # selected ("act") trades in the declared regime: top-tercile feature score
    reg_scores = [s.score for s in regime_samples]
    if len(set(reg_scores)) >= 3:
        hi_cut = sorted(reg_scores)[(2 * len(reg_scores)) // 3]
    else:
        hi_cut = float("inf")
    sel_idx, sel_sym, sel_net, sel_gross = [], [], [], []
    for s in regime_samples:
        if s.score >= hi_cut:
            sel_idx.append(s.idx)
            sel_sym.append(s.sym)
            sel_gross.append(s.fwd_return)
            sel_net.append(s.fwd_return - FEE_RT)

    # full trap arrays for the evaluator (use the most-populous symbol's candles;
    # the per-symbol structural check above is the authoritative leakage gate, so
    # we patch the evaluator's leakage verdict with `look_clean` after the call).
    big_sym = max(per_symbol, key=lambda k: len(per_symbol[k]["idxs"]))
    bs = per_symbol[big_sym]

    # a per-feature p-value proxy: from the net-EV block CI (one-sided). We use the
    # bootstrap to get a crude p ~ fraction of resamples <= 0; here approximate via
    # the declared-regime net series.
    pval = _net_ev_pvalue(regime_samples)

    # register BEFORE consuming results (FDR honesty)
    ledger.register(
        feature.name, declared_regime, "trailing-3-bar return predicts forward exit pnl"
    )

    verdict = ag.evaluate_feature(
        feature=feature,
        regime=declared_regime,
        candles=bs["candles"],
        indices=sel_idx,
        symbols=sel_sym,
        net_returns=sel_net,
        gross_returns=sel_gross,
        trap_indices=bs["idxs"],
        trap_symbols=[big_sym] * len(bs["idxs"]),
        trap_fwd_returns=bs["fwd"],
        samples_for_walkforward=regime_samples,
        pvalue=pval,
        fdr_batch_pvalues=[pval],  # single-feature batch in the smoke run
        fee_rt=FEE_RT,
        panel_columns=None,  # no existing panel here => incrementality NOT_APPLICABLE
    )
    # override the structural leakage gate with the authoritative per-symbol check
    for g in verdict.gates:
        if g.name == "leakage_clean":
            g.result = ag.GateResult.PASS if look_clean else ag.GateResult.FAIL
            g.detail += f" | per-symbol lookahead_clean={look_clean}"
    verdict.accepted = all(gg.result == ag.GateResult.PASS for gg in verdict.gates)

    _print_verdict(label, declared_regime, regime_samples, sel_gross, verdict)
    return verdict


def _net_ev_pvalue(samples: list[wfv.Sample]) -> float:
    """Crude one-sided bootstrap p-value for net-EV > 0 of the selected (top-tercile)
    trades in this sample set, net of fee. Returns 1.0 if no spread is estimable."""
    import stats_validation as sv

    scores = [s.score for s in samples]
    if len(set(scores)) < 3:
        return 1.0
    hi_cut = sorted(scores)[(2 * len(scores)) // 3]
    by_sym: dict[str, list[float]] = {}
    for s in samples:
        if s.score >= hi_cut:
            by_sym.setdefault(s.sym, []).append(s.fwd_return - FEE_RT)
    series = [v for v in by_sym.values() if v]
    if not series:
        return 1.0
    _m, lo, hi, _ne, _b = sv.block_bootstrap_ci(series)
    # one-sided p proxy: if CI excludes 0 on +side, small p; if straddles, ~0.5+
    if lo > 0:
        return 0.01
    if hi < 0:
        return 0.99
    return 0.5


def _print_verdict(label, regime, regime_samples, sel_gross, verdict: ag.AcceptanceVerdict):
    print(f"\n{'#' * 90}")
    print(f"#  WINDOW {label}  —  declared regime: {regime}")
    print(f"{'#' * 90}")
    print(f"  samples in regime: {len(regime_samples)}  | selected (act) trades: {len(sel_gross)}")
    if sel_gross:
        print(f"  selected gross EV: {st.mean(sel_gross):+.3f}%  (2x fee bar = {2 * FEE_RT:.3f}%)")
    print(f"\n  {'GATE':>24}  {'RESULT':>14}  DETAIL")
    print(f"  {'-' * 24}  {'-' * 14}  {'-' * 40}")
    for g in verdict.gates:
        print(f"  {g.name:>24}  {g.result.value:>14}  {g.detail}")
    print(f"\n  ==> VERDICT: {'ACCEPT' if verdict.accepted else 'REJECT'}")
    if verdict.not_applicable_gates:
        print(f"      (NOT_APPLICABLE — not validated: {', '.join(verdict.not_applicable_gates)})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w1", default="/tmp/cal_candles_d1.json")
    ap.add_argument("--w2", default="/tmp/cal_candles.json")
    ap.add_argument("--regime", default="trend", choices=list(wfv.REGIMES))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    print("=" * 90)
    print("PHASE V — VALIDATION SPINE  (smoke run on cached windows, default REJECT)")
    print("=" * 90)
    print("  demo feature: trailing-3-bar return (leakage-CLEAN). Fee RT =", FEE_RT, "%")
    print("  NOTE: on this quiet chop tape momentum is expected to REJECT — that is the")
    print("        skeptic harness working, not a failure.")

    ledger = ag.PreRegistrationLedger()
    out: dict = {"phase": "V — validation spine smoke", "fee_rt": FEE_RT, "windows": {}}
    for label, path in (("W1", args.w1), ("W2", args.w2)):
        if not os.path.exists(path):
            print(f"\n  [skip] {label}: {path} not found", file=sys.stderr)
            continue
        with open(path) as f:
            raw = json.load(f)
        v = run_window(label, raw, args.regime, ledger)
        out["windows"][label] = v.to_dict()

    out["preregistration_ledger_batch_size"] = ledger.batch_size()
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\nWrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
