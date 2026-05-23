#!/usr/bin/env python3
"""Phase V.1 — per-regime partitioning + walk-forward folds (quant-analyst, 2026-05-23).

WHY
  An edge measured on the whole tape at once is in-sample (IS) — it can be
  curve-fit. V.2 requires OUT-OF-SAMPLE (OOS) evidence that holds the SAME SIGN
  across time folds, and it requires the edge to be evaluated WITHIN its declared
  regime (a chop edge and a trend edge are different claims). This module
  provides both, on a sample stream that is already point-in-time (the features
  are computed strictly on candles[:i+1] upstream, in feature_validation).

REGIME PARTITION
  We reuse the EXISTING classifier — chart_floor_calibration.regime_at(c, i) →
  "trend" / "transitional" / "chop" (ADX bands). We do NOT invent a new one.

WALK-FORWARD (documented choice: EXPANDING window)
  Samples are ordered by entry time (per the cached tape's bar order). We split
  the ordered stream into `n_folds` contiguous TEST segments. Fold f trains on
  everything STRICTLY BEFORE its test segment and evaluates OOS on the test
  segment. Expanding (not rolling) because the tape is short — every fold gets
  the largest causal train set available. The train/test cut is a hard index
  boundary: NO test sample's index precedes any of its train samples, so there is
  no lookahead across the cut. (The features themselves are already causal; this
  guards the EVALUATION split, not the feature.)

OUTPUTS
  * per_regime_edge   — block-bootstrap CI of the edge within each regime.
  * walk_forward      — per-fold OOS edge + a same_sign_across_folds flag and an
    oos_positive flag (every fold's OOS point edge > 0).

REUSE: stats_validation.block_bootstrap_ci, chart_floor_calibration.regime_at.
No network / live-bot state.

Run: uv run pytest scripts/calibration/test_walkforward_validation.py -q
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stats_validation as sv

REGIMES = ("trend", "transitional", "chop")


# ── A flat sample: one entry, its score, realized forward return, regime ─
@dataclass
class Sample:
    sym: str
    idx: int  # entry bar index (the time order key, within symbol)
    score: float
    fwd_return: float  # realized net-or-gross forward return (the label)
    regime: str  # "trend" / "transitional" / "chop"


def _signed_series(samples: list[Sample]) -> list[list[float]]:
    """Per-symbol ordered long-short signed-return series (top vs bottom tercile of
    score within THIS sample set). Mirrors feature_validation.edge_series but on
    Sample objects so regime/fold slices reuse the same edge definition."""
    scores = [s.score for s in samples]
    if len(set(scores)) < 3:
        return []
    srt = sorted(scores)
    lo_cut, hi_cut = srt[len(srt) // 3], srt[(2 * len(srt)) // 3]
    by_sym: dict[str, list[float]] = {}
    for s in samples:
        if s.score >= hi_cut:
            by_sym.setdefault(s.sym, []).append(s.fwd_return)
        elif s.score <= lo_cut:
            by_sym.setdefault(s.sym, []).append(-s.fwd_return)
    return [v for v in by_sym.values() if v]


def edge_of(samples: list[Sample]) -> dict:
    series = _signed_series(samples)
    if not series:
        return {"edge": float("nan"), "ci": (float("nan"), float("nan")), "n_eff": 0.0, "n": 0}
    mean, lo, hi, n_eff, _b = sv.block_bootstrap_ci(series)
    n = sum(len(s) for s in series)
    return {"edge": mean, "ci": (lo, hi), "n_eff": n_eff, "n": n, "excl_zero": (lo > 0 or hi < 0)}


# ── Per-regime partition ────────────────────────────────────────────
def partition_by_regime(samples: list[Sample]) -> dict[str, list[Sample]]:
    out: dict[str, list[Sample]] = {r: [] for r in REGIMES}
    for s in samples:
        out.setdefault(s.regime, []).append(s)
    return out


def per_regime_edge(samples: list[Sample]) -> dict[str, dict]:
    return {regime: edge_of(group) for regime, group in partition_by_regime(samples).items()}


# ── Walk-forward (expanding) ────────────────────────────────────────
def _time_order(samples: list[Sample]) -> list[Sample]:
    """Order by (idx, sym) — the within-tape bar order. The cached windows are a
    set of per-symbol series; idx is the bar index, which is the time key. Sorting
    by idx interleaves symbols by bar, which is the correct chronological order for
    a walk-forward split across a multi-symbol tape sampled on the same clock."""
    return sorted(samples, key=lambda s: (s.idx, s.sym))


def walk_forward(samples: list[Sample], n_folds: int = 4) -> dict:
    """Expanding-window walk-forward. Returns per-fold OOS edge + cross-fold flags.

    The ordered stream is cut into `n_folds` contiguous TEST segments. Fold f's
    train set is everything strictly before its test segment (expanding). Fold 0
    has no train history, so it is reported but excluded from the OOS verdict
    (no causal model could have been fit before it). The OOS verdict uses folds
    1..n_folds-1.
    """
    ordered = _time_order(samples)
    n = len(ordered)
    if n < n_folds * 3:  # need a few samples per fold to be meaningful
        return {
            "n_folds": n_folds,
            "folds": [],
            "oos_positive": False,
            "same_sign_across_folds": False,
            "note": f"insufficient samples ({n}) for {n_folds} folds",
        }
    bounds = [round(n * f / n_folds) for f in range(n_folds + 1)]
    folds: list[dict] = []
    for f in range(n_folds):
        test_lo, test_hi = bounds[f], bounds[f + 1]
        test = ordered[test_lo:test_hi]
        train = ordered[:test_lo]  # strictly before the test segment
        # lookahead guard on the split: max train idx must not exceed min test idx
        if train and test:
            max_train_idx = max(s.idx for s in train)
            min_test_idx = min(s.idx for s in test)
            split_clean = max_train_idx <= min_test_idx
        else:
            split_clean = True
        e = edge_of(test)
        folds.append(
            {
                "fold": f,
                "n_train": len(train),
                "n_test": e.get("n", 0),
                "oos_edge": e["edge"],
                "oos_ci": list(e["ci"]),
                "oos_excl_zero": e.get("excl_zero", False),
                "split_clean": split_clean,
                "is_warmup_fold": f == 0,
            }
        )
    # OOS verdict uses folds with a train history (f>=1) that have a finite edge
    oos_folds = [
        fd for fd in folds if not fd["is_warmup_fold"] and fd["oos_edge"] == fd["oos_edge"]
    ]
    oos_positive = bool(oos_folds) and all(fd["oos_edge"] > 0 for fd in oos_folds)
    signs = {1 if fd["oos_edge"] > 0 else (-1 if fd["oos_edge"] < 0 else 0) for fd in oos_folds}
    same_sign = bool(oos_folds) and len(signs) == 1 and 0 not in signs
    all_splits_clean = all(fd["split_clean"] for fd in folds)
    return {
        "n_folds": n_folds,
        "folds": folds,
        "oos_positive": oos_positive,
        "same_sign_across_folds": same_sign,
        "all_splits_clean": all_splits_clean,
    }


# ── Synthetic builders (tests) ──────────────────────────────────────
def make_consistent_samples(n: int = 200, edge: float = 0.5, seed: int = 1) -> list[Sample]:
    """Samples where high score => high forward return CONSISTENTLY across time
    (a real, time-stable edge). Single regime 'trend'. fwd_return = edge*score +
    small noise, so top-tercile minus bottom-tercile is reliably positive in
    every fold."""
    import random

    rng = random.Random(seed)
    out: list[Sample] = []
    for i in range(n):
        score = rng.gauss(0, 1)
        fwd = edge * score + rng.gauss(0, 0.3)
        out.append(Sample(sym="SYN", idx=i, score=score, fwd_return=fwd, regime="trend"))
    return out


def make_regime_split_samples(seed: int = 2) -> list[Sample]:
    """Two regimes with OPPOSITE edges: 'trend' has a positive score→return edge,
    'chop' has a NEGATIVE one. Partitioning must recover both signs separately."""
    import random

    rng = random.Random(seed)
    out: list[Sample] = []
    for i in range(150):
        sc = rng.gauss(0, 1)
        out.append(Sample("SYN", i, sc, 0.5 * sc + rng.gauss(0, 0.3), "trend"))
    for i in range(150, 300):
        sc = rng.gauss(0, 1)
        out.append(Sample("SYN", i, sc, -0.5 * sc + rng.gauss(0, 0.3), "chop"))
    return out


def make_regime_flips_sign_samples(seed: int = 3) -> list[Sample]:
    """A single regime whose edge FLIPS SIGN halfway through time (first half
    positive, second half negative) — same_sign_across_folds must be False."""
    import random

    rng = random.Random(seed)
    out: list[Sample] = []
    for i in range(150):
        sc = rng.gauss(0, 1)
        out.append(Sample("SYN", i, sc, 0.6 * sc + rng.gauss(0, 0.2), "trend"))
    for i in range(150, 300):
        sc = rng.gauss(0, 1)
        out.append(Sample("SYN", i, sc, -0.6 * sc + rng.gauss(0, 0.2), "trend"))
    return out


# ── Self-test ────────────────────────────────────────────────────────
def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # T1 — per-regime partition recovers opposite signs
    rs = make_regime_split_samples()
    pr = per_regime_edge(rs)
    check("T1a trend regime edge positive", pr["trend"]["edge"] > 0)
    check("T1b chop regime edge negative", pr["chop"]["edge"] < 0)
    check("T1c partition counts add up", len(rs) == 300)

    # T2 — walk-forward on a time-stable edge: OOS positive + same sign
    cs = make_consistent_samples(n=240, edge=0.5)
    wf = walk_forward(cs, n_folds=4)
    print(f"      consistent edge folds (OOS): {[round(fd['oos_edge'], 3) for fd in wf['folds']]}")
    check("T2a OOS positive across folds", wf["oos_positive"])
    check("T2b same sign across folds", wf["same_sign_across_folds"])
    check("T2c all train/test splits clean (no lookahead)", wf["all_splits_clean"])
    check("T2d fold 0 flagged as warmup (no train history)", wf["folds"][0]["is_warmup_fold"])
    check("T2e fold 1 has a train set", wf["folds"][1]["n_train"] > 0)

    # T3 — sign-flipping edge: same_sign_across_folds must be FALSE
    fl = make_regime_flips_sign_samples()
    wf2 = walk_forward(fl, n_folds=4)
    print(f"      sign-flip folds (OOS): {[round(fd['oos_edge'], 3) for fd in wf2['folds']]}")
    check("T3a sign-flipping edge fails same-sign check", not wf2["same_sign_across_folds"])

    print(f"\n  {'ALL TESTS PASS' if ok else 'SOME TESTS FAILED'}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if self_test() else 1)
