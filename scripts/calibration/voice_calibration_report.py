#!/usr/bin/env python3
"""Voice calibration report — Sprint 3 S3-1.

Reads ``contest_bot/decision_runs/{run_id}/decisions.jsonl`` across all runs,
joins each decision row to its outcome row by ``decision_id``, and computes
per-voice calibration: Brier score + Platt (logistic) scaling + isotonic
regression + binned reliability curve.

For each voice, we ask: when this voice says ``bullish`` with confidence X,
do the resulting trades win X% of the time? If yes, the voice is *calibrated*
and its confidence is a real probability. If no — the confidence is a
self-reported number with no statistical meaning — we know how to correct it.

DATA-ADEQUACY DISCLAIMER (read this before believing any number this script
emits): meaningful calibration requires N ≥ 100 acted decisions per voice
AND meaningful variance in the voice's confidence output. At smaller N or
when a voice emits a constant value (current state for chart_analyst @ 0.85
and risk_voice @ 0.7), the Brier score and reliability curve are DEGENERATE
— Brier reduces to ``(constant_prob - mean_win_rate)²`` and the reliability
curve collapses to a single point. The script reports adequacy explicitly so
results are not over-read. Battle-testing PAPER for ≥2 weeks at ~5-10 acted
decisions / day grows the sample; voice-confidence variance grows after the
voice-prompt iteration (Sprint 3+ work).

Output:
  JSON  : private/strategy/voice_calibration_report.json
  text  : printed to stdout (also captured by the deliverable doc)

Run:
  uv run python scripts/calibration/voice_calibration_report.py
                                             [--days 30] [--voice <name>]
                                             [--min-confidence-variance 0.01]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DECISION_RUNS_GLOB = os.path.join(_REPO_ROOT, "contest_bot", "decision_runs", "*", "decisions.jsonl")
DEFAULT_OUT = os.path.join(_REPO_ROOT, "private", "strategy", "voice_calibration_report.json")

# Numerical adequacy thresholds. These are the founder-pending Op-2 defaults
# (see private/strategy/2026-05-26-sprint-3-voice-calibration.md). Any number
# changes here should be reflected there too — but the values below are
# *justified defaults*, not arbitrary picks:
#  - 100: rule-of-thumb minimum for Brier-score CI to be tight enough to
#         distinguish two calibrators with realistic separation (Steyerberg).
#  - 0.05: minimum stddev on confidence values for fitting a non-degenerate
#         calibration curve — below this the voice is effectively constant.
#  - 0.20: Brier-score upper bound for "well-calibrated for a binary trade
#         outcome" — random guessing on a 50/50 outcome gets Brier 0.25; a
#         calibrated voice with discriminative power should land < 0.20.
MIN_N_FOR_CALIBRATION_CLAIM = 100
MIN_CONFIDENCE_STDDEV = 0.05
BRIER_WELL_CALIBRATED_THRESHOLD = 0.20


# ── Data shapes ────────────────────────────────────────────────────────
@dataclass
class VoiceObservation:
    """One row of (predicted_prob_of_win, actual_win 0/1) for a single voice
    on a single decision."""

    decision_id: str
    voice_name: str
    verdict: str  # bullish / bearish / neutral / abstain
    confidence: float
    predicted_prob_win: float  # transformed from verdict+confidence
    win: int  # 0 or 1
    pnl_pct: float
    ts: str
    symbol: str
    regime_1h: str
    coordinator_action: str


@dataclass
class CalibrationResult:
    voice_name: str
    n_observations: int
    n_directional: int  # observations where verdict was bullish or bearish (not abstain)
    win_rate: float | None
    mean_predicted_prob: float | None
    confidence_stddev: float | None
    brier_score: float | None
    platt_scaling: dict | None  # {slope, intercept} of fitted logistic
    isotonic_curve: list[dict] | None  # [{predicted, calibrated}]
    reliability_bins: list[dict] | None  # [{lo, hi, n, predicted_avg, observed_avg}]
    adequacy: dict = field(default_factory=dict)


# ── Data loading ───────────────────────────────────────────────────────
def load_decision_runs() -> tuple[dict[str, dict], dict[str, dict]]:
    """Walk all decision_runs and return (decisions_by_id, outcomes_by_id).

    A "decision" row has the full voices+indicators+oracle+coordinator
    payload; an "outcome" row carries the same decision_id but with only the
    ``outcome`` sub-document. Some decisions never close (e.g. open mid-run);
    those have no outcome row and are excluded from calibration.
    """
    decisions: dict[str, dict] = {}
    outcomes: dict[str, dict] = {}
    for path in sorted(glob.glob(DECISION_RUNS_GLOB)):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    did = row.get("decision_id")
                    if not isinstance(did, str):
                        continue
                    if "voices" in row and isinstance(row.get("voices"), list):
                        decisions[did] = row
                    elif row.get("outcome"):
                        outcomes[did] = row["outcome"]
        except OSError:
            continue
    return decisions, outcomes


# ── Voice → prediction transform ───────────────────────────────────────
def voice_to_prediction(verdict: str, confidence: float) -> float | None:
    """Map (verdict, confidence) → predicted_prob_of_win in [0, 1].

    The voice's verdict tells us its DIRECTION; the confidence is the
    strength. For calibration we need a single probability per opinion:

      - bullish: voice predicts the long opens a winner → prob_win = confidence
      - bearish: voice predicts the long opens a loser  → prob_win = 1 - confidence
      - neutral: voice has no opinion either way        → prob_win = 0.5
      - abstain: voice declines to predict              → return None (exclude)

    Returning None for abstain lets the calibration sample be filtered to
    directional opinions only — including abstains as 0.5 dilutes the
    discriminative signal we're trying to measure.
    """
    verdict_norm = (verdict or "").lower()
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return None
    c = max(0.0, min(1.0, c))
    if verdict_norm == "bullish":
        return c
    if verdict_norm == "bearish":
        return 1.0 - c
    if verdict_norm == "neutral":
        return 0.5
    return None  # abstain / unknown


def build_observations(
    decisions: dict[str, dict], outcomes: dict[str, dict]
) -> list[VoiceObservation]:
    """Join decisions↔outcomes, expand to one row per (voice, decision)."""
    out: list[VoiceObservation] = []
    for did, decision in decisions.items():
        outcome = outcomes.get(did)
        if outcome is None:
            continue
        pnl_pct = outcome.get("pnl_pct")
        if not isinstance(pnl_pct, (int, float)):
            continue
        win = 1 if pnl_pct > 0 else 0
        indicators = decision.get("indicators") or {}
        coordinator = decision.get("coordinator") or {}
        voices = decision.get("voices") or []
        for v in voices:
            voice_name = v.get("name")
            if not voice_name:
                continue
            verdict = v.get("verdict") or ""
            confidence = v.get("confidence")
            pred = voice_to_prediction(verdict, confidence)
            obs = VoiceObservation(
                decision_id=did,
                voice_name=voice_name,
                verdict=verdict,
                confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.0,
                predicted_prob_win=pred if pred is not None else -1.0,  # sentinel
                win=win,
                pnl_pct=float(pnl_pct),
                ts=decision.get("ts", ""),
                symbol=decision.get("symbol", ""),
                regime_1h=indicators.get("regime_1h", ""),
                coordinator_action=coordinator.get("action", ""),
            )
            out.append(obs)
    return out


# ── Calibration math ───────────────────────────────────────────────────
def brier_score(predictions: list[float], outcomes: list[int]) -> float:
    """Mean squared error of probability vs binary outcome.

    Brier is 0 for a perfect probabilistic classifier, 0.25 for random
    guessing on a 50/50 outcome, 1.0 for the worst possible inverted
    classifier. For a binary outcome it's a strictly proper scoring rule
    — minimised IFF the predicted probabilities match the true conditional
    probabilities given the input features.
    """
    if not predictions:
        return float("nan")
    arr_p = np.asarray(predictions, dtype=float)
    arr_y = np.asarray(outcomes, dtype=float)
    return float(np.mean((arr_p - arr_y) ** 2))


def fit_platt(predictions: list[float], outcomes: list[int]) -> dict | None:
    """Logistic regression: calibrated = 1 / (1 + exp(-(slope*x + intercept))).

    Returns {slope, intercept, scaled_predictions} or None if the inputs are
    degenerate (constant prediction OR all-same outcomes, which prevent a
    meaningful fit).
    """
    if len(set(outcomes)) < 2:
        return None  # all wins or all losses — degenerate
    if len(set(round(p, 6) for p in predictions)) < 2:
        return None  # constant prediction — degenerate
    X = np.asarray(predictions, dtype=float).reshape(-1, 1)
    y = np.asarray(outcomes, dtype=int)
    model = LogisticRegression(solver="lbfgs")
    model.fit(X, y)
    slope = float(model.coef_[0][0])
    intercept = float(model.intercept_[0])
    scaled = model.predict_proba(X)[:, 1].tolist()
    return {"slope": slope, "intercept": intercept, "scaled_predictions": scaled}


def fit_isotonic(predictions: list[float], outcomes: list[int]) -> list[dict] | None:
    """Non-parametric monotonic mapping from predicted prob → observed win
    rate. Pool-adjacent-violators under the hood.

    Returns [{predicted, calibrated}] sorted by predicted, or None when
    degenerate.
    """
    if len(set(outcomes)) < 2 or len(set(round(p, 6) for p in predictions)) < 2:
        return None
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(predictions, outcomes)
    pts = sorted(set(round(p, 4) for p in predictions))
    fitted = iso.predict(pts).tolist()
    return [{"predicted": p, "calibrated": float(c)} for p, c in zip(pts, fitted)]


def reliability_bins(
    predictions: list[float], outcomes: list[int], n_bins: int = 5
) -> list[dict]:
    """Bin observations by predicted probability and report the observed win
    rate per bin. Even at degenerate N or constant prediction the bins still
    print useful counts; they collapse to one bin in those cases."""
    if not predictions:
        return []
    arr_p = np.asarray(predictions, dtype=float)
    arr_y = np.asarray(outcomes, dtype=int)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out: list[dict] = []
    for i in range(n_bins):
        lo, hi = float(edges[i]), float(edges[i + 1])
        if i == n_bins - 1:
            mask = (arr_p >= lo) & (arr_p <= hi)
        else:
            mask = (arr_p >= lo) & (arr_p < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        out.append(
            {
                "lo": lo,
                "hi": hi,
                "n": n,
                "predicted_avg": float(arr_p[mask].mean()),
                "observed_avg": float(arr_y[mask].mean()),
            }
        )
    return out


# ── Per-voice calibration ──────────────────────────────────────────────
def calibrate_voice(
    voice_name: str, observations: list[VoiceObservation]
) -> CalibrationResult:
    voice_obs = [o for o in observations if o.voice_name == voice_name]
    n = len(voice_obs)
    directional = [o for o in voice_obs if o.predicted_prob_win >= 0]
    n_dir = len(directional)
    if n_dir == 0:
        return CalibrationResult(
            voice_name=voice_name,
            n_observations=n,
            n_directional=0,
            win_rate=None,
            mean_predicted_prob=None,
            confidence_stddev=None,
            brier_score=None,
            platt_scaling=None,
            isotonic_curve=None,
            reliability_bins=None,
            adequacy={
                "n_sufficient": False,
                "variance_sufficient": False,
                "well_calibrated": False,
                "reason": "no_directional_observations",
            },
        )
    preds = [o.predicted_prob_win for o in directional]
    outs = [o.win for o in directional]
    confs = [o.confidence for o in directional]
    win_rate = float(np.mean(outs))
    mean_pred = float(np.mean(preds))
    conf_std = float(np.std(confs))
    brier = brier_score(preds, outs)
    platt = fit_platt(preds, outs)
    iso = fit_isotonic(preds, outs)
    bins = reliability_bins(preds, outs)
    n_sufficient = n_dir >= MIN_N_FOR_CALIBRATION_CLAIM
    var_sufficient = conf_std >= MIN_CONFIDENCE_STDDEV
    well_calibrated = (
        brier is not None
        and not np.isnan(brier)
        and brier <= BRIER_WELL_CALIBRATED_THRESHOLD
        and n_sufficient
        and var_sufficient
    )
    if not n_sufficient:
        reason = f"n_too_small (n={n_dir}, need ≥{MIN_N_FOR_CALIBRATION_CLAIM})"
    elif not var_sufficient:
        reason = (
            f"confidence_stddev_too_small (stddev={conf_std:.4f}, "
            f"need ≥{MIN_CONFIDENCE_STDDEV}); voice is emitting near-constant"
        )
    elif not well_calibrated:
        reason = f"brier_above_threshold ({brier:.4f} > {BRIER_WELL_CALIBRATED_THRESHOLD})"
    else:
        reason = "passes_all_checks"
    return CalibrationResult(
        voice_name=voice_name,
        n_observations=n,
        n_directional=n_dir,
        win_rate=win_rate,
        mean_predicted_prob=mean_pred,
        confidence_stddev=conf_std,
        brier_score=brier,
        platt_scaling={k: v for k, v in (platt or {}).items() if k != "scaled_predictions"}
        if platt
        else None,
        isotonic_curve=iso,
        reliability_bins=bins,
        adequacy={
            "n_sufficient": n_sufficient,
            "variance_sufficient": var_sufficient,
            "well_calibrated": well_calibrated,
            "reason": reason,
            "min_n": MIN_N_FOR_CALIBRATION_CLAIM,
            "min_stddev": MIN_CONFIDENCE_STDDEV,
            "brier_threshold": BRIER_WELL_CALIBRATED_THRESHOLD,
        },
    )


# ── Text report ────────────────────────────────────────────────────────
def render_text(report: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 88)
    lines.append("VOICE CALIBRATION REPORT")
    lines.append("=" * 88)
    lines.append(f"  Total decisions joined (with outcomes): {report['totals']['n_decisions']}")
    lines.append(
        f"  Adequacy thresholds: n ≥ {MIN_N_FOR_CALIBRATION_CLAIM}, "
        f"confidence stddev ≥ {MIN_CONFIDENCE_STDDEV}, "
        f"Brier ≤ {BRIER_WELL_CALIBRATED_THRESHOLD}"
    )
    lines.append("")
    for r in report["voices"]:
        lines.append("-" * 88)
        status = "✓ CALIBRATED" if r["adequacy"]["well_calibrated"] else "✗ NOT YET CALIBRATED"
        lines.append(f"  {r['voice_name']:18s} {status}")
        lines.append(
            f"    observations: total={r['n_observations']}  directional={r['n_directional']}"
        )
        if r["n_directional"] > 0:
            lines.append(
                f"    win_rate (acted decisions): {r['win_rate']:.3f}  "
                f"mean predicted P(win): {r['mean_predicted_prob']:.3f}"
            )
            lines.append(
                f"    confidence stddev: {r['confidence_stddev']:.4f}  "
                f"Brier score: {r['brier_score']:.4f}"
            )
        lines.append(f"    adequacy: {r['adequacy']['reason']}")
        if r["platt_scaling"]:
            p = r["platt_scaling"]
            lines.append(
                f"    Platt fit: slope={p['slope']:+.3f}  intercept={p['intercept']:+.3f}"
            )
        if r["reliability_bins"]:
            lines.append("    reliability bins:")
            for b in r["reliability_bins"]:
                lines.append(
                    f"      [{b['lo']:.2f}, {b['hi']:.2f}]  n={b['n']:3d}  "
                    f"predicted={b['predicted_avg']:.3f}  observed={b['observed_avg']:.3f}"
                )
    lines.append("=" * 88)
    return "\n".join(lines)


# ── Main / CLI ─────────────────────────────────────────────────────────
def build_report(voice_filter: str | None = None) -> dict:
    decisions, outcomes = load_decision_runs()
    n_matched = sum(1 for d in decisions if d in outcomes)
    observations = build_observations(decisions, outcomes)
    voice_names = sorted({o.voice_name for o in observations})
    if voice_filter:
        voice_names = [v for v in voice_names if v == voice_filter]
    voice_results = [calibrate_voice(v, observations) for v in voice_names]
    return {
        "totals": {
            "n_decisions_total": len(decisions),
            "n_outcomes_total": len(outcomes),
            "n_decisions": n_matched,
            "n_observations": len(observations),
        },
        "voices": [asdict(r) for r in voice_results],
        "adequacy_thresholds": {
            "min_n_for_calibration_claim": MIN_N_FOR_CALIBRATION_CLAIM,
            "min_confidence_stddev": MIN_CONFIDENCE_STDDEV,
            "brier_well_calibrated_threshold": BRIER_WELL_CALIBRATED_THRESHOLD,
        },
    }


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--voice", default=None, help="Filter to a single voice name")
    ap.add_argument(
        "--out", default=DEFAULT_OUT, help="Output JSON path (default: private/strategy/...)"
    )
    ap.add_argument(
        "--quiet", action="store_true", help="Skip the human-readable text report on stdout"
    )
    a = ap.parse_args()
    report = build_report(voice_filter=a.voice)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(report, f, indent=2)
    if not a.quiet:
        print(render_text(report))
        print(f"\nJSON written to {a.out}")


if __name__ == "__main__":
    _cli()
