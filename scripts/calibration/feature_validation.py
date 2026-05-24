#!/usr/bin/env python3
"""Phase V.1/V.2 — Feature protocol + leakage traps (quant-analyst, 2026-05-23).

WHAT A "FEATURE" IS HERE
  A Feature maps a point-in-time view of the tape to a single score:

      compute(candles, i) -> float        # STRICTLY uses candles[:i+1]

  The contract is CAUSALITY: the score at bar i may read bar i and every bar
  before it, and NOTHING at i+1 or later. A feature that peeks forward is the
  classic backtest lie — it "predicts" returns it has already seen. This module
  builds the traps that CATCH that lie, plus the statistical traps that catch a
  feature whose apparent edge is just noise.

THREE TRAPS (a feature must survive all three before any acceptance gate)
  1. LOOKAHEAD trap (structural, deterministic) — recompute the feature on a
     truncated prefix candles[:i+1] in isolation and compare to the value it
     produced on the full series. A causal feature is INVARIANT to future bars;
     a leaked feature CHANGES when you reveal/hide the future. This catches the
     leak directly, no statistics needed.
  2. SHUFFLE trap (statistical) — the feature's edge is the block-bootstrap CI on
     the (long-minus-short) forward-return spread between its top-tercile and
     bottom-tercile scores. SHUFFLE the forward-return labels (destroying any
     real score→return link) and recompute: a REAL edge must VANISH (CI straddles
     zero) on shuffled labels. If the "edge" survives shuffling, it was an
     artifact of the harness, not the feature.
  3. PLACEBO-LABEL trap (statistical) — replace the real forward returns with a
     synthetic label that is independent of price (pure noise with the same shape)
     and confirm the feature shows NO edge against it. A feature that "predicts" a
     random label is leaking through some shared structure.

WHY A LEAKED FEATURE FAILS
  The deliberately-leaked example reads candles[i+1]'s return into its own score.
  * It FAILS the lookahead trap outright (its value at i differs when the future
    is hidden).
  * Its unshuffled edge is enormous (it IS the forward return), but that is
    exactly what the shuffle trap is designed to expose as non-causal: we report
    the leak via the lookahead trap, which is unambiguous.

REUSE: stats_validation.block_bootstrap_ci (the canonical CI). No I/O / network.

Run: uv run pytest scripts/calibration/test_feature_validation.py -q
"""

from __future__ import annotations

import os
import random
import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stats_validation as sv


# ── The Feature protocol ────────────────────────────────────────────
@runtime_checkable
class Feature(Protocol):
    """A point-in-time scalar feature. MUST be computed strictly on candles[:i+1].

    `candles` is the enriched dict (keys: ts/open/high/low/close/volume + any
    indicators). `i` is the entry bar. Return a float score; convention is higher
    = more bullish, but the traps are sign-agnostic (they test |edge|)."""

    name: str

    def compute(self, candles: dict, i: int) -> float: ...


# ── Example features (one clean, one deliberately leaked) ────────────
@dataclass
class MomentumFeature:
    """Leakage-CLEAN example: trailing k-bar return, read only from candles[:i+1].

    score = (close[i] - close[i-k]) / close[i-k]  — pure backward window."""

    k: int = 3
    name: str = "trailing_return_clean"

    def compute(self, candles: dict, i: int) -> float:
        cl = candles["close"]
        if i - self.k < 0 or cl[i - self.k] == 0:
            return 0.0
        return (cl[i] - cl[i - self.k]) / cl[i - self.k]


@dataclass
class LeakedFeature:
    """Deliberately-LEAKED example: peeks at the FORWARD bar (i+1). This is the
    cheating feature the harness must catch. score reads candles[i+1] — a value
    that does not exist at decision time i."""

    name: str = "forward_peek_leaked"

    def compute(self, candles: dict, i: int) -> float:
        cl = candles["close"]
        if i + 1 >= len(cl) or cl[i] == 0:
            return 0.0
        # THE LEAK: the next bar's return, which is unknowable at bar i.
        return (cl[i + 1] - cl[i]) / cl[i]


# ── Trap 1: lookahead (structural, deterministic) ───────────────────
def _slice_candles(candles: dict, upto: int) -> dict:
    """Return a copy of `candles` truncated to indices [0, upto] inclusive."""
    return {key: val[: upto + 1] for key, val in candles.items()}


def lookahead_clean(feat: Feature, candles: dict, indices: list[int]) -> bool:
    """True iff the feature is INVARIANT to future bars at every test index.

    For each i, compute the feature on the full series and on the prefix
    candles[:i+1]. A causal feature gives the SAME value (it never used anything
    past i). A leaked feature differs because the full-series call saw the future
    that the truncated call cannot. Returns False on the first violation."""
    for i in indices:
        full = feat.compute(candles, i)
        prefix = feat.compute(_slice_candles(candles, i), i)
        if not _close(full, prefix):
            return False
    return True


def _close(a: float, b: float, tol: float = 1e-9) -> bool:
    if a != a or b != b:  # NaN
        return a != a and b != b
    return abs(a - b) <= tol + tol * max(abs(a), abs(b))


# ── Edge estimator: top-tercile minus bottom-tercile forward return ─
def _terciles(scores: list[float]) -> tuple[float, float]:
    """(low_cut, high_cut) tercile boundaries of the score distribution."""
    s = sorted(scores)
    n = len(s)
    return s[n // 3], s[(2 * n) // 3]


def edge_series(
    scores: list[float], fwd_returns: list[float], symbols: list[str]
) -> list[list[float]]:
    """Per-symbol ordered series of the SIGNED forward return, where a sample is
    +fwd_return if its score is in the top tercile, −fwd_return if in the bottom
    tercile, and dropped if in the middle. The mean of this pooled series is the
    long-short spread (the feature's edge). Per-symbol ordering is preserved so
    the block bootstrap can model the within-symbol autocorrelation."""
    if len(set(scores)) < 3:
        # degenerate: no spread possible
        return []
    lo_cut, hi_cut = _terciles(scores)
    by_sym: dict[str, list[float]] = {}
    for sc, fr, sym in zip(scores, fwd_returns, symbols, strict=True):
        if sc >= hi_cut:
            by_sym.setdefault(sym, []).append(fr)
        elif sc <= lo_cut:
            by_sym.setdefault(sym, []).append(-fr)
    return [v for v in by_sym.values() if v]


def edge_ci(scores: list[float], fwd_returns: list[float], symbols: list[str]) -> dict:
    """Block-bootstrap CI on the long-short edge. excl_zero=True means the feature
    has a CI-clean directional edge against these labels."""
    series = edge_series(scores, fwd_returns, symbols)
    if not series:
        return {"edge": float("nan"), "ci": (float("nan"), float("nan")), "excl_zero": False}
    mean, lo, hi, n_eff, _b = sv.block_bootstrap_ci(series)
    return {"edge": mean, "ci": (lo, hi), "n_eff": n_eff, "excl_zero": (lo > 0 or hi < 0)}


# ── Trap 2: shuffle the labels (edge must vanish) ───────────────────
def shuffle_trap(
    scores: list[float], fwd_returns: list[float], symbols: list[str], seed: int = sv.RNG_SEED
) -> dict:
    """Shuffle the forward-return labels (breaking any score→return link) and
    confirm the edge VANISHES (CI straddles zero). Returns the real-edge CI and
    the shuffled-edge CI; `passes` is True iff the real edge is CI-clean AND the
    shuffled edge straddles zero (a real, non-spurious edge)."""
    real = edge_ci(scores, fwd_returns, symbols)
    rng = random.Random(seed)
    shuffled_returns = fwd_returns[:]
    rng.shuffle(shuffled_returns)
    shuf = edge_ci(scores, shuffled_returns, symbols)
    passes = bool(real["excl_zero"]) and not bool(shuf["excl_zero"])
    return {"real": real, "shuffled": shuf, "passes": passes}


# ── Trap 3: placebo label (independent noise) ───────────────────────
def placebo_trap(scores: list[float], symbols: list[str], seed: int = 4242) -> dict:
    """Score the feature against a PLACEBO label: noise independent of price,
    same length/shape as the real labels. A clean feature shows NO edge against
    pure noise (CI straddles zero) → passes. A feature that "predicts" random
    noise is leaking through shared structure → fails."""
    rng = random.Random(seed)
    placebo = [rng.gauss(0.0, 1.0) for _ in scores]
    res = edge_ci(scores, placebo, symbols)
    passes = not bool(res["excl_zero"])  # no edge vs noise = pass
    return {"placebo_edge": res, "passes": passes}


# ── Combined leakage verdict ────────────────────────────────────────
@dataclass
class LeakageReport:
    feature: str
    lookahead_clean: bool
    shuffle_passes: bool
    placebo_passes: bool
    detail: dict = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        """A feature is leakage-clean only if it survives ALL THREE traps."""
        return self.lookahead_clean and self.shuffle_passes and self.placebo_passes


def run_leakage_traps(
    feat: Feature,
    candles: dict,
    indices: list[int],
    fwd_returns: list[float],
    symbols: list[str],
) -> LeakageReport:
    """Run all three traps for one feature on one window. `indices`, `fwd_returns`,
    `symbols` are aligned per-sample (sample s = entry at indices[s], realized
    forward return fwd_returns[s], symbol symbols[s])."""
    look = lookahead_clean(feat, candles, indices)
    scores = [feat.compute(candles, i) for i in indices]
    shuf = shuffle_trap(scores, fwd_returns, symbols)
    plac = placebo_trap(scores, symbols)
    return LeakageReport(
        feature=feat.name,
        lookahead_clean=look,
        shuffle_passes=shuf["passes"],
        placebo_passes=plac["passes"],
        detail={"shuffle": shuf, "placebo": plac},
    )


# ── Synthetic builder for tests/demos ───────────────────────────────
def build_predictive_window(n: int = 240, phi: float = 0.0, seed: int = 3) -> dict:
    """Build a synthetic single-symbol enriched candle window where the trailing
    k=3 return is GENUINELY predictive of the next return (momentum), so the clean
    feature has a real causal edge. Returns the enriched dict (close-only walk)."""
    rng = random.Random(seed)
    close = [100.0]
    drift = 0.0
    for _t in range(1, n):
        # momentum: drift persists, so trailing return predicts forward return
        drift = phi * drift + 0.004 * (1 if rng.random() < 0.52 else -1) + rng.gauss(0, 0.001)
        nxt = close[-1] * (1 + drift)
        close.append(nxt)
    return {
        "ts": [t * 300_000 for t in range(n)],
        "open": close[:],
        "high": [c * 1.001 for c in close],
        "low": [c * 0.999 for c in close],
        "close": close,
        "volume": [1.0] * n,
    }


def forward_return(candles: dict, i: int, horizon: int = 1) -> float:
    """Realized forward return over `horizon` bars (the label). Uses bars AFTER i
    — this is the LABEL, not a feature; labels are allowed to look forward."""
    cl = candles["close"]
    j = min(i + horizon, len(cl) - 1)
    if cl[i] == 0:
        return 0.0
    return (cl[j] - cl[i]) / cl[i]


# ── Self-test ────────────────────────────────────────────────────────
def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # build a momentum window where the clean feature is genuinely predictive
    c = build_predictive_window(n=300, phi=0.6, seed=5)
    n = len(c["close"])
    indices = list(range(5, n - 2))  # leave room for forward label
    syms = ["SYN"] * len(indices)
    fwd = [forward_return(c, i, horizon=1) for i in indices]

    clean = MomentumFeature(k=3)
    leaked = LeakedFeature()

    # Trap 1 — lookahead
    check("T1a clean feature is lookahead-invariant", lookahead_clean(clean, c, indices))
    check("T1b leaked feature FAILS lookahead trap", not lookahead_clean(leaked, c, indices))

    # full trap suite
    rep_clean = run_leakage_traps(clean, c, indices, fwd, syms)
    rep_leaked = run_leakage_traps(leaked, c, indices, fwd, syms)
    print(
        f"      clean : lookahead={rep_clean.lookahead_clean} "
        f"shuffle={rep_clean.shuffle_passes} placebo={rep_clean.placebo_passes} "
        f"-> clean={rep_clean.clean}"
    )
    print(
        f"      leaked: lookahead={rep_leaked.lookahead_clean} "
        f"shuffle={rep_leaked.shuffle_passes} placebo={rep_leaked.placebo_passes} "
        f"-> clean={rep_leaked.clean}"
    )

    # Trap 2 — shuffle: clean feature's real edge present, shuffled edge vanishes
    sh = rep_clean.detail["shuffle"]
    check("T2a clean: real edge CI-clean", sh["real"]["excl_zero"])
    check("T2b clean: shuffled edge straddles zero", not sh["shuffled"]["excl_zero"])
    check("T2c clean: shuffle trap PASSES", rep_clean.shuffle_passes)

    # Trap 3 — placebo: clean feature shows no edge vs noise
    check("T3a clean: placebo trap PASSES (no edge vs noise)", rep_clean.placebo_passes)

    # THE HEADLINE: leaked feature is rejected, clean feature is accepted
    check("T4a leaked feature is NOT clean (caught)", not rep_leaked.clean)
    check("T4b clean feature IS clean (passes)", rep_clean.clean)

    print(f"\n  {'ALL TESTS PASS' if ok else 'SOME TESTS FAILED'}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if self_test() else 1)
