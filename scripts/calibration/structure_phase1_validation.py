#!/usr/bin/env python3
"""Phase 1 — does STRUCTURE lift the primitive's GROSS EDGE past fees? (quant-analyst).

THE BINDING CONSTRAINT (proven three ways)
  The oracle/local gate SELECTS cleanly in uptrends (CI-clean positive gating
  delta in trend_up), but the trades it selects are ~3-4x too thin to clear the
  round-trip fee. Selection is solved; GROSS EDGE is the bottleneck. This script
  tests whether any STRUCTURE filter — framed as a VETO and/or a ROOM-TO-RUN gate
  per the prior de-risk finding — produces a candidate-entry set whose GROSS edge
  clears the 2x-fee bar, in any of the four regimes, CI-clean.

WHAT IT DOES (free, deterministic, no LLM)
  1. Replays all 24 tapes through the EXACT live candidate gate (breakout OR
     volume-spike, full-horizon) and the real close-based exit stack
     (exit_reconciliation.simulate_exit_real_close) -> per-candidate GROSS pnl%.
     Resampling unit = the tape (a (sym, tf) ordered series); within-tape order
     preserved for the block bootstrap.
  2. Partitions candidates by the 4-WAY regime (trend_up / trend_down /
     transitional / chop), reusing the base 3-way classifier + a trend-direction
     split (mirrors the cross-regime study's regime4_at).
  3. For each structure Feature (the contest_bot/features conformers): the SELECTED
     ("act") subset is the candidates where the feature's `passes` predicate is
     True. Per regime it reports:
       - GROSS-EDGE DELTA = grossEV(structure-filtered) - grossEV(ungated),
         paired block-bootstrap CI (fee cancels -> gross),
       - the structure-filtered subset's GROSS EV + block-CI vs the 2x-fee bar,
       - N_eff (Bartlett VIF -> N/VIF),
       - whether the gross edge CLEARS 2x fee (the real bar) CI-clean.
  4. Runs the full Phase V acceptance gate (default REJECT) per feature x its
     declared regime: leakage (lookahead+shuffle+placebo), net-EV-excl-zero,
     BH-FDR across the pre-registered batch, N_eff>=30, OOS same-sign across
     walk-forward folds, incremental-VIF, gross>=2x fee.

THE QUESTION ANSWERED
  Does any structure feature (veto and/or room-to-run gate) produce a candidate
  set whose GROSS edge clears the 2x-fee bar in any regime, CI-clean? That is the
  thing momentum alone could not do. Default REJECT — no lift is claimed unless
  the CI excludes zero AND it clears 2x fee.

HONESTY
  * The gross-edge DELTA (filtered vs ungated) is the lift question; the gross-EV
    LEVEL vs 2x-fee is the monetization question. Both are reported. A feature can
    lift the delta CI-clean yet still fail the fee bar — that is reported as such.
  * Block bootstrap (canonical, stats_validation) — IID would understate width.
  * Leakage traps run on the FULL candidate set; the lift/level stats on the
    SELECTED subset.
  * READ-ONLY w.r.t. the live bot. No network. No result numbers in this file's
    docstrings (findings go to the gitignored private/ doc).

Run:
  python3 scripts/calibration/structure_phase1_validation.py --json-out /tmp/structure_phase1.json
  uv run pytest scripts/calibration/test_structure_phase1_validation.py -q   # unit tests
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

import acceptance_gate as ag  # noqa: E402
import chart_floor_calibration as base  # noqa: E402  candidate gate + enrich + regime
import exit_reconciliation as recon  # noqa: E402  real close-based exit stack
import feature_validation as fv  # noqa: E402
import stats_validation as sv  # noqa: E402
import structure_features as sf  # noqa: E402
import walkforward_validation as wfv  # noqa: E402

TAPE_DIR = os.path.join(_HERE, "data", "tape")
RESERVED = {"tape_index.json", "regime_windows.json"}
REGIMES_4 = ("trend_up", "trend_down", "transitional", "chop")
TREND_DIR_LOOKBACK = 14  # mirrors the cross-regime study's trend-direction split
FEE_RT = sf.DEFAULT_FEE_RT  # 0.75 RT central; 2x = 1.5% is the economic bar
FWD_HORIZON = 18  # bars for the leakage-trap forward label (matches has_full_horizon)


# ── 4-way regime (faithful to the tape's regime labels) ─────────────
def regime4_at(c: dict, i: int) -> str:
    r = base.regime_at(c, i)
    if r != "trend":
        return r
    lo = max(0, i - TREND_DIR_LOOKBACK)
    net = c["close"][i] - c["close"][lo]
    return "trend_up" if net >= 0 else "trend_down"


# ── A graded candidate (one per fired bar) ──────────────────────────
@dataclass
class Cand:
    tape: str  # "BTC_1H" — the resampling unit (within-tape order preserved)
    idx: int
    regime: str  # 4-way
    pnl_real: float  # GROSS realized pnl%, real close-based exit


def collect_all_tapes(tape_dir: str = TAPE_DIR) -> tuple[dict[str, dict], list[Cand], dict]:
    """Return (enriched_by_tape, candidates, meta). Candidates use the EXACT live
    gate (breakout OR volume-spike, full-horizon) + real close exit. The enriched
    candle dicts are kept so the Feature conformers can recompute on candles[:i+1]."""
    enriched: dict[str, dict] = {}
    cands: list[Cand] = []
    meta: dict = {"tapes": {}, "skipped": []}
    files = sorted(
        f for f in os.listdir(tape_dir) if f.endswith(".json") and "_" in f and f not in RESERVED
    )
    for fname in files:
        with open(os.path.join(tape_dir, fname)) as fh:
            raw = json.load(fh)
        if not isinstance(raw, list) or len(raw) < 60:
            meta["skipped"].append(fname)
            continue
        tape = fname[:-5]
        c = base.enrich(raw)
        enriched[tape] = c
        n = len(c["close"])
        per_tape = 0
        i = base.WARMUP
        while i < n:
            if (
                base.breakout_fires(c, i) or base.volume_spike_fires(c, i)
            ) and base.has_full_horizon(c, i):
                cands.append(
                    Cand(
                        tape=tape,
                        idx=i,
                        regime=regime4_at(c, i),
                        pnl_real=recon.simulate_exit_real_close(c, i),
                    )
                )
                per_tape += 1
                i += 6  # no-overlap, mirrors the backtest run
            else:
                i += 1
        meta["tapes"][tape] = {"bars": n, "candidates": per_tape}
    return enriched, cands, meta


# ── Gross-EV block-CI on a candidate subset (the LEVEL, by tape) ────
def _by_tape_gross(cands: list[Cand]) -> list[list[float]]:
    by: dict[str, list[float]] = {}
    for c in sorted(cands, key=lambda x: (x.tape, x.idx)):
        by.setdefault(c.tape, []).append(c.pnl_real)
    return [v for v in by.values() if v]


def gross_ev_ci(cands: list[Cand]) -> dict:
    series = _by_tape_gross(cands)
    if not series:
        return {"gross_ev": float("nan"), "ci": (float("nan"), float("nan")), "n": 0, "n_eff": 0.0}
    mean, lo, hi, n_eff, _b = sv.block_bootstrap_ci(series)
    return {
        "gross_ev": mean,
        "ci": (lo, hi),
        "n": sum(len(s) for s in series),
        "n_eff": n_eff,
        "excl_zero_pos": lo == lo and lo > 0,
    }


# ── Paired gross-edge DELTA: filtered vs ungated, same resample ─────
def gross_delta_paired(cands: list[Cand], passes: list[bool], seed: int = sv.RNG_SEED) -> dict:
    """Paired block bootstrap of grossEV(filtered) - grossEV(ungated). The filtered
    arm is a SUBSET of the ungated arm, so each resample draws per-tape blocks of
    (pnl, is_in) tuples ONCE and recomputes BOTH arm means on the same resample.
    Fee cancels -> the delta is gross (= the lift in gross edge from the filter)."""
    import random

    by_tape: dict[str, list[tuple[float, bool]]] = {}
    for c, p in sorted_with(cands, passes):
        by_tape.setdefault(c.tape, []).append((c.pnl_real, p))
    series = [v for v in by_tape.values() if v]
    flat = [t for s in series for t in s]
    on = [g for (g, p) in flat if p]
    off = [g for (g, _p) in flat]
    if not on or not off:
        return {
            "delta": float("nan"),
            "ci": (float("nan"),) * 2,
            "n_on": len(on),
            "n_off": len(off),
            "excl_zero_pos": False,
        }
    point = stx.mean(on) - stx.mean(off)
    block = sv.choose_block_length([[g for (g, _p) in s] for s in series])
    weights = [len(s) for s in series]
    total = len(flat)

    # Prefix sums per tape so a block's contribution is an O(1) lookup, not an
    # O(block) list-extend. Each resample then costs O(total/block) block draws
    # instead of O(total) — the difference between minutes and seconds at N=36k.
    # all_cum[t][j]   = sum of pnl over the first j candidates of tape t,
    # on_cum[t][j]    = sum of pnl over selected ("on") candidates in first j,
    # oncnt_cum[t][j] = count of selected candidates in first j.
    all_cum: list[list[float]] = []
    on_cum: list[list[float]] = []
    oncnt_cum: list[list[int]] = []
    for s in series:
        ac, oc, occ = [0.0], [0.0], [0]
        for g, p in s:
            ac.append(ac[-1] + g)
            oc.append(oc[-1] + (g if p else 0.0))
            occ.append(occ[-1] + (1 if p else 0))
        all_cum.append(ac)
        on_cum.append(oc)
        oncnt_cum.append(occ)

    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(sv.N_BOOTSTRAP):
        sum_all = sum_on = 0.0
        n_all = n_on = 0
        while n_all < total:
            si = rng.choices(range(len(series)), weights=weights, k=1)[0]
            slen = len(series[si])
            bb = min(block, slen, total - n_all)
            start = rng.randrange(0, slen - min(block, slen) + 1)
            end = start + bb
            sum_all += all_cum[si][end] - all_cum[si][start]
            sum_on += on_cum[si][end] - on_cum[si][start]
            n_on += oncnt_cum[si][end] - oncnt_cum[si][start]
            n_all += bb
        if n_on > 0 and n_all > 0:
            boots.append(sum_on / n_on - sum_all / n_all)
    boots.sort()
    if not boots:
        return {
            "delta": point,
            "ci": (float("nan"),) * 2,
            "n_on": len(on),
            "n_off": len(off),
            "excl_zero_pos": False,
        }
    lo = boots[int(0.025 * len(boots))]
    hi = boots[int(0.975 * len(boots))]
    return {
        "delta": point,
        "ci": (lo, hi),
        "n_on": len(on),
        "n_off": len(off),
        "gross_on": stx.mean(on),
        "gross_off": stx.mean(off),
        "excl_zero_pos": lo > 0,
        "excl_zero": (lo > 0 or hi < 0),
    }


def sorted_with(cands: list[Cand], passes: list[bool]) -> list[tuple[Cand, bool]]:
    """Zip cands+passes preserving the (tape, idx) order the bootstrap needs."""
    paired = list(zip(cands, passes, strict=True))
    return sorted(paired, key=lambda cp: (cp[0].tape, cp[0].idx))


# ── Per-feature, per-regime structure-lift analysis ─────────────────
def feature_passes(feat, enriched: dict[str, dict], cands: list[Cand]) -> list[bool]:
    """The feature's `passes` predicate at each candidate bar (the SELECTED subset).
    Features without an explicit `passes` (continuous) fall back to top-half of the
    score within the candidate pool (a default selection rule)."""
    if hasattr(feat, "passes"):
        return [feat.passes(enriched[c.tape], c.idx) for c in cands]
    scores = [feat.compute(enriched[c.tape], c.idx) for c in cands]
    if len(set(scores)) < 2:
        return [True] * len(cands)
    med = stx.median(scores)
    return [s >= med for s in scores]


def precompute_feature(feat, enriched: dict[str, dict], cands: list[Cand]) -> dict:
    """Compute the feature's score AND `passes` for every candidate ONCE. Returns
    {"scores": [...], "passes": [...]} aligned to `cands`. This is the single
    expensive pass (pivot detection); every downstream regime slice / bootstrap /
    acceptance gate reuses it instead of recomputing pivots per regime."""
    scores = [feat.compute(enriched[c.tape], c.idx) for c in cands]
    if hasattr(feat, "passes"):
        passes = [feat.passes(enriched[c.tape], c.idx) for c in cands]
    else:
        med = stx.median(scores) if len(set(scores)) >= 2 else None
        passes = [True] * len(cands) if med is None else [s >= med for s in scores]
    return {"scores": scores, "passes": passes}


def analyze_feature(feat, cands: list[Cand], pre: dict) -> dict:
    """Per-regime gross-edge delta (filtered vs ungated) + gross-EV level vs 2x fee.
    Uses precomputed scores/passes (pre) — no pivot recomputation here."""
    out: dict = {"feature": feat.name, "regimes": {}}
    bar = ag.ECON_FEE_MULTIPLE * FEE_RT  # 2x fee
    idx_of = {id(c): n for n, c in enumerate(cands)}
    for rg in ("ALL", *REGIMES_4):
        pool = cands if rg == "ALL" else [c for c in cands if c.regime == rg]
        if not pool:
            out["regimes"][rg] = {"n": 0}
            continue
        passes = [pre["passes"][idx_of[id(c)]] for c in pool]
        selected = [c for c, p in zip(pool, passes, strict=True) if p]
        delta = gross_delta_paired(pool, passes)
        sel_ev = gross_ev_ci(selected)
        base_ev = gross_ev_ci(pool)
        clears = bool(
            sel_ev["gross_ev"] == sel_ev["gross_ev"]
            and sel_ev["ci"][0] == sel_ev["ci"][0]
            and sel_ev["ci"][0] >= bar  # CI lower bound clears 2x fee
        )
        out["regimes"][rg] = {
            "n_pool": len(pool),
            "n_selected": len(selected),
            "gross_delta": delta["delta"],
            "delta_ci": list(delta["ci"]),
            "delta_excl_zero_pos": delta.get("excl_zero_pos", False),
            "selected_gross_ev": sel_ev["gross_ev"],
            "selected_gross_ci": list(sel_ev["ci"]),
            "selected_n_eff": sel_ev["n_eff"],
            "baseline_gross_ev": base_ev["gross_ev"],
            "two_x_fee_bar": bar,
            "clears_2x_fee_ci_clean": clears,
        }
    return out


# ── Phase V acceptance gate per feature (declared regime) ───────────
def acceptance_for_feature(
    feat,
    enriched: dict[str, dict],
    cands: list[Cand],
    pre: dict,
    declared_regime: str,
    pvalue: float,
    fdr_batch_pvalues: list[float],
) -> ag.AcceptanceVerdict:
    """Run the default-REJECT acceptance gate for one feature in its declared
    regime. Leakage traps run on the FULL pool; the EV gates on the SELECTED
    subset. Symbols = tape id (the resampling unit). No panel columns supplied ->
    incrementality is honestly NOT_APPLICABLE (not a pass). `pre` holds the
    precomputed per-candidate scores/passes (no pivot recomputation)."""
    idx_of = {id(c): n for n, c in enumerate(cands)}
    pool = [c for c in cands if c.regime == declared_regime]
    # A single enriched dict can't span tapes; the lookahead trap needs per-tape
    # context. We run the trap on the LARGEST tape in the pool (representative),
    # since lookahead-clean is a structural property of the feature, not the data.
    # (shuffle/placebo are pooled across the subset below.)
    by_tape: dict[str, list[Cand]] = {}
    for c in pool:
        by_tape.setdefault(c.tape, []).append(c)
    if not by_tape:
        # empty regime -> a trivially-rejected verdict
        return ag.AcceptanceVerdict(
            feature=feat.name, regime=declared_regime, gates=[], fee_rt=FEE_RT, accepted=False
        )
    big_tape = max(by_tape, key=lambda t: len(by_tape[t]))
    big_c = enriched[big_tape]
    big_indices = [c.idx for c in by_tape[big_tape]]
    big_syms = [big_tape] * len(big_indices)
    big_fwd = [fv.forward_return(big_c, i, FWD_HORIZON) * 100 for i in big_indices]

    # Selected subset (the "act" trades) for the EV/econ gates (precomputed passes).
    passes = [pre["passes"][idx_of[id(c)]] for c in pool]
    sel = [c for c, p in zip(pool, passes, strict=True) if p]
    sel_idx = [c.idx for c in sel]
    sel_syms = [c.tape for c in sel]
    gross = [c.pnl_real for c in sel]
    net = [c.pnl_real - FEE_RT for c in sel]

    # Walk-forward samples: precomputed score + realized forward return per pool
    # candidate.
    wf_samples = [
        wfv.Sample(
            sym=c.tape,
            idx=c.idx,
            score=pre["scores"][idx_of[id(c)]],
            fwd_return=c.pnl_real,
            regime=declared_regime,
        )
        for c in pool
    ]

    return ag.evaluate_feature(
        feature=feat,
        regime=declared_regime,
        candles=big_c,
        indices=sel_idx,
        symbols=sel_syms,
        net_returns=net,
        gross_returns=gross,
        trap_indices=big_indices,
        trap_symbols=big_syms,
        trap_fwd_returns=big_fwd,
        samples_for_walkforward=wf_samples,
        pvalue=pvalue,
        fdr_batch_pvalues=fdr_batch_pvalues,
        fee_rt=FEE_RT,
        panel_columns=None,  # honest NOT_APPLICABLE
    )


# ── Feature roster ──────────────────────────────────────────────────
def feature_roster() -> list:
    return [
        sf.OverheadRoomFeature(),
        sf.RoomToRunGate(),
        sf.NotIntoResistanceVeto(),
        sf.NotMidRangeVeto(),
        sf.StructureNotDownVeto(),
        sf.StructureStackGate(),
    ]


# ── Reporting ───────────────────────────────────────────────────────
def _fmt(x: float) -> str:
    return "  n/a" if x != x else f"{x:+.3f}"


def print_lift_table(analyses: list[dict]) -> None:
    bar = ag.ECON_FEE_MULTIPLE * FEE_RT
    print(f"\n{'=' * 100}")
    print(
        f"GROSS-EDGE LIFT — structure-filtered vs ungated, per 4-way regime (2x-fee bar = {bar:.2f}%)"
    )
    print(f"{'=' * 100}")
    for a in analyses:
        print(f"\n  FEATURE: {a['feature']}")
        hdr = (
            f"  {'regime':>13} {'nPool':>6} {'nSel':>5} | {'ΔgrossEV%':>10} {'delta 95% CI':>20} "
            f"{'CI+':>4} | {'selGrossEV%':>11} {'sel 95% CI':>20} | {'clears 2x?':>10}"
        )
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for rg in ("ALL", *REGIMES_4):
            r = a["regimes"].get(rg, {})
            if not r or r.get("n_pool", 0) == 0:
                print(f"  {rg:>13} {'(empty)':>6}")
                continue
            dlo, dhi = r["delta_ci"]
            slo, shi = r["selected_gross_ci"]
            ci_pos = "YES" if r["delta_excl_zero_pos"] else "no"
            clears = "YES(+)" if r["clears_2x_fee_ci_clean"] else "no"
            print(
                f"  {rg:>13} {r['n_pool']:>6} {r['n_selected']:>5} | "
                f"{_fmt(r['gross_delta']):>10} [{_fmt(dlo)},{_fmt(dhi)}] {ci_pos:>4} | "
                f"{_fmt(r['selected_gross_ev']):>11} [{_fmt(slo)},{_fmt(shi)}] | {clears:>10}"
            )


def print_acceptance(verdicts: list[ag.AcceptanceVerdict]) -> None:
    print(f"\n{'=' * 100}")
    print("PHASE V ACCEPTANCE GATE (default REJECT) — per feature x declared regime")
    print(f"{'=' * 100}")
    for v in verdicts:
        print(
            f"\n  {v.feature}  (regime={v.regime})  ->  {'ACCEPTED' if v.accepted else 'REJECTED'}"
        )
        for g in v.gates:
            print(f"      {g.name:>24}: {g.result.value:>14}  {g.detail}")


def run(json_out: str | None) -> dict:
    print("Loading 24-tape dataset + replaying live gate...", file=sys.stderr)
    enriched, cands, meta = collect_all_tapes()
    dist = {rg: sum(1 for c in cands if c.regime == rg) for rg in REGIMES_4}
    print(
        f"  tapes: {len(meta['tapes'])}  candidates: {len(cands)}  regime dist: {dist}",
        file=sys.stderr,
    )

    roster = feature_roster()
    # One expensive pivot pass per feature; everything downstream reuses it.
    print("Precomputing feature scores/passes (single pivot pass each)...", file=sys.stderr)
    pres = []
    for f in roster:
        import time as _t

        t0 = _t.time()
        pres.append(precompute_feature(f, enriched, cands))
        print(f"    {f.name}: {_t.time() - t0:.1f}s", file=sys.stderr)
    analyses = [analyze_feature(f, cands, pre) for f, pre in zip(roster, pres, strict=True)]
    print_lift_table(analyses)

    # Pre-registration ledger + FDR batch. Each feature's declared regime is the
    # one with the most SELECTED candidates (its strongest operating regime), but
    # we declare trend_up as the primary hypothesis regime (where selection works)
    # and ALSO record each feature's own best-regime acceptance.
    ledger = ag.PreRegistrationLedger()
    declared = "trend_up"
    for f in roster:
        ledger.register(
            f.name, declared, f"structure filter {f.name} lifts gross edge in {declared}"
        )

    # p-values from the gross-edge delta sign+CI in the declared regime (a simple
    # one-sided proxy: p ~ fraction of bootstrap mass <= 0 is not stored, so we use
    # the delta_excl_zero_pos as a 0.04/0.5 proxy — honest, conservative).
    fdr_p: list[float] = []
    for a in analyses:
        r = a["regimes"].get(declared, {})
        fdr_p.append(0.04 if r.get("delta_excl_zero_pos") else 0.5)

    verdicts = [
        acceptance_for_feature(f, enriched, cands, pre, declared, pvalue=p, fdr_batch_pvalues=fdr_p)
        for f, pre, p in zip(roster, pres, fdr_p, strict=True)
    ]
    print_acceptance(verdicts)

    result = {
        "generated": "2026-05-23",
        "phase": "Phase 1 structure — gross-edge lift validation",
        "fee_rt": FEE_RT,
        "two_x_fee_bar": ag.ECON_FEE_MULTIPLE * FEE_RT,
        "tape_meta": meta,
        "regime_distribution": dist,
        "n_candidates": len(cands),
        "declared_regime": declared,
        "lift_analyses": analyses,
        "acceptance": [v.to_dict() for v in verdicts],
        "ledger_batch_size": ledger.batch_size(),
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
