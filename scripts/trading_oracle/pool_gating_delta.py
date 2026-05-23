#!/usr/bin/env python3
"""Pool W1 + W2 oracle gating-delta runs and report per-window + pooled deltas.

Reuses oracle_gating_delta.gating_delta_paired_ci (the EXACT paired moving-block
bootstrap, block=3, seed=1729, 5000 resamples) so the pooled numbers are
byte-identical in method to the per-window harness. Adds a jackknife (drop-one)
on the pooled SAFE/GATE-OFF graded pool.

Pooling caveat (load-bearing, printed): W1 and W2 are two overlapping snapshots
of the same live tape (Jaccard ~0.90 on raw bar timestamps), offset ~90 min.
They are NOT independent windows; pooling tightens the CI but the effective
information is < N1+N2. We report N_eff alongside.

Usage:
    uv run python scripts/trading_oracle/pool_gating_delta.py \
        tests/eval/live_runs/2026-05-22-oracle-gating-delta-w1.json \
        tests/eval/live_runs/2026-05-22-oracle-gating-delta-w2.json
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CALIB = os.path.join(os.path.dirname(_HERE), "calibration")
sys.path.insert(0, _CALIB)
sys.path.insert(0, _HERE)

import exit_reconciliation as recon  # noqa: E402
import oracle_gating_delta as ogd  # noqa: E402


def load_entries(path: str) -> list[ogd.GradedEntry]:
    with open(path) as f:
        d = json.load(f)
    out: list[ogd.GradedEntry] = []
    for e in d["entries"]:
        # Drop fields not on the dataclass defensively (forward-compat).
        out.append(ogd.GradedEntry(**{k: v for k, v in e.items() if k in ogd.GradedEntry.__dataclass_fields__}))
    return out


def clean(entries: list[ogd.GradedEntry]) -> list[ogd.GradedEntry]:
    """The harness grades only clean panel reads: no transport error, no degraded voice."""
    return [e for e in entries if e.verdict != "ERROR" and not e.degraded]


def regime_table(label: str, entries: list[ogd.GradedEntry]) -> dict:
    graded = clean(entries)
    print(f"\n{'=' * 92}")
    print(f"{label}  (clean N={len(graded)} of {len(entries)} attempted)")
    print(f"{'=' * 92}")
    hdr = (
        f"  {'scope':>14} {'nSAFE':>5} {'nOFF':>5} | {'mSAFE%':>8} {'mOFF%':>8} | "
        f"{'Δ%':>8} {'paired 95% CI':>22} {'clean':>7}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    results: dict = {}
    for slabel, rg in [
        ("ALL", None),
        ("trend", "trend"),
        ("transitional", "transitional"),
        ("chop", "chop"),
    ]:
        subset = [e for e in graded if rg is None or e.regime == rg]
        gd = ogd.gating_delta_paired_ci(subset)
        results[slabel] = gd
        if gd["delta"] != gd["delta"]:
            print(
                f"  {slabel:>14} {gd['n_safe']:>5} {gd['n_gate_off']:>5} | "
                f"{'—':>8} {'—':>8} | {'—':>8} {gd.get('note', 'undefined'):>22}"
            )
            continue
        ci = gd["ci"]
        print(
            f"  {slabel:>14} {gd['n_safe']:>5} {gd['n_gate_off']:>5} | "
            f"{gd['mean_safe']:>+8.3f} {gd['mean_gate_off']:>+8.3f} | "
            f"{gd['delta']:>+8.3f} [{ci[0]:>+7.3f},{ci[1]:>+7.3f}] {gd['ci_clean']:>7}"
        )
    # N_eff for the pooled graded set.
    gross_series = list(
        recon.regime_series_gross(
            [recon.Cand(e.sym, e.idx, e.regime, 0.0, False, e.pnl_real, e.pnl_real) for e in graded],
            None,
            "pnl_real",
        )
    )
    vif = recon.variance_inflation(gross_series)
    n = sum(len(s) for s in gross_series)
    print(f"\n  graded pool: N={n}  VIF={vif:.2f}  N_eff={n / vif if vif else n:.0f}")
    results["_meta"] = {"n_clean": len(graded), "vif": vif, "n_eff": n / vif if vif else n}
    return results


def jackknife(entries: list[ogd.GradedEntry]) -> dict:
    """Drop-one on the clean graded pool; report the range of the ALL-scope delta."""
    graded = [e for e in clean(entries) if e.verdict in (ogd.SAFE_VERDICTS | ogd.GATE_OFF_VERDICTS)]
    base_delta = ogd.gating_delta_paired_ci(graded)["delta"]
    deltas = []
    worst_drop = None
    worst_val = base_delta
    for i in range(len(graded)):
        sub = graded[:i] + graded[i + 1 :]
        gd = ogd.gating_delta_paired_ci(sub)
        d = gd["delta"]
        if d == d:
            deltas.append(d)
            if d < worst_val:
                worst_val = d
                worst_drop = graded[i]
    lo, hi = min(deltas), max(deltas)
    all_pos = lo > 0
    print(f"\n  jackknife (drop-one, N={len(graded)}): base Δ={base_delta:+.3f}  "
          f"range [{lo:+.3f}, {hi:+.3f}]  {'ALWAYS POSITIVE' if all_pos else 'CROSSES ZERO'}")
    if worst_drop is not None:
        print(f"    most-influential drop -> Δ={worst_val:+.3f} "
              f"(removing {worst_drop.sym} {worst_drop.regime} {worst_drop.verdict} pnl={worst_drop.pnl_real:+.2f})")
    return {"base": base_delta, "range": [lo, hi], "always_positive": all_pos, "min": worst_val}


def main() -> None:
    paths = sys.argv[1:]
    if len(paths) < 2:
        print("usage: pool_gating_delta.py <w1.json> <w2.json> [...]", file=sys.stderr)
        sys.exit(1)
    per_window = {}
    all_entries: list[ogd.GradedEntry] = []
    for p in paths:
        es = load_entries(p)
        wlabel = os.path.basename(p)
        per_window[wlabel] = regime_table(wlabel, es)
        all_entries.extend(es)

    pooled = regime_table("POOLED (W1 + W2)", all_entries)
    print("\n  *** POOLING CAVEAT: W1 and W2 overlap ~90% on raw bar timestamps "
          "(Jaccard 0.90); they are two snapshots of the same tape offset ~90 min, "
          "NOT independent windows. Pooled N overstates effective information. ***")
    jk = jackknife(all_entries)

    out = {
        "per_window": per_window,
        "pooled": pooled,
        "pooled_jackknife": jk,
        "n_windows": len(paths),
    }
    out_path = "/tmp/oracle_gating_delta_pooled.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
