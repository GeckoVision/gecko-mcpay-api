#!/usr/bin/env python3
"""Voice-drift KS-test snapshot — Sprint 3 S3-4.

For each voice, compare the confidence distribution over a RECENT window
(default last 7d) to a PRIOR baseline window (the 7d before that). Flag
voices whose distribution has shifted materially — KS statistic above
threshold AND p-value below alpha.

Drift detection is the operational alarm that catches *silent* changes
in voice behavior — a prompt regression, an upstream-data shift, an LLM
provider update — before the voice's degraded output starts compounding
into bad trades. It does NOT explain *why* the distribution shifted;
that's a separate forensic step the alarm is meant to trigger.

DATA-ADEQUACY NOTE: KS-test power scales with sample size in BOTH
windows. At small N (per-window < 30) the test will flag few things
(low power), and any detection should be treated as exploratory rather
than load-bearing. The minimum-per-window guard below reports
"insufficient_window" instead of false-positive-prone results.

Output:
  JSON  : private/strategy/voice_drift_report.json
  text  : stdout

Run:
  uv run python scripts/calibration/voice_drift_report.py
                                          [--recent-days 7]
                                          [--baseline-days 7]
                                          [--ks-threshold 0.20]
                                          [--alpha 0.05]
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from scipy.stats import ks_2samp

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DECISION_RUNS_GLOB = os.path.join(_REPO_ROOT, "contest_bot", "decision_runs", "*", "decisions.jsonl")
DEFAULT_OUT = os.path.join(_REPO_ROOT, "private", "strategy", "voice_drift_report.json")

DEFAULT_RECENT_DAYS = 7
DEFAULT_BASELINE_DAYS = 7
DEFAULT_KS_THRESHOLD = 0.20  # KS statistic; 0 = identical, 1 = disjoint
DEFAULT_ALPHA = 0.05
MIN_SAMPLES_PER_WINDOW = 30


# ── Data shapes ────────────────────────────────────────────────────────
@dataclass
class VoiceObservation:
    voice_name: str
    ts: dt.datetime
    confidence: float
    verdict: str


@dataclass
class DriftResult:
    voice_name: str
    n_recent: int
    n_baseline: int
    recent_mean: float | None
    baseline_mean: float | None
    recent_stddev: float | None
    baseline_stddev: float | None
    ks_statistic: float | None
    p_value: float | None
    drift_detected: bool
    adequacy: dict = field(default_factory=dict)


# ── Loading ────────────────────────────────────────────────────────────
def load_voice_observations() -> list[VoiceObservation]:
    """Walk decision_runs/* and emit one VoiceObservation per (voice, decision)."""
    obs: list[VoiceObservation] = []
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
                    if not isinstance(row.get("voices"), list):
                        continue
                    ts_str = row.get("ts", "")
                    if not ts_str:
                        continue
                    try:
                        ts = dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        continue
                    for v in row["voices"]:
                        name = v.get("name")
                        if not name:
                            continue
                        try:
                            conf = float(v.get("confidence") or 0.0)
                        except (TypeError, ValueError):
                            conf = 0.0
                        obs.append(
                            VoiceObservation(
                                voice_name=name,
                                ts=ts,
                                confidence=conf,
                                verdict=str(v.get("verdict") or ""),
                            )
                        )
        except OSError:
            continue
    return obs


# ── Window splitter ────────────────────────────────────────────────────
def split_windows(
    observations: list[VoiceObservation],
    recent_days: int,
    baseline_days: int,
    reference: dt.datetime | None = None,
) -> tuple[list[VoiceObservation], list[VoiceObservation]]:
    """Split observations into recent + baseline windows.

    recent  = [now - recent_days, now]
    baseline = [now - recent_days - baseline_days, now - recent_days]

    `reference` lets tests pin the "now" to a fixed datetime for
    deterministic behaviour; defaults to utcnow().
    """
    ref = reference if reference is not None else dt.datetime.now(dt.UTC)
    recent_start = ref - dt.timedelta(days=recent_days)
    baseline_start = recent_start - dt.timedelta(days=baseline_days)
    recent = [o for o in observations if recent_start <= o.ts <= ref]
    baseline = [o for o in observations if baseline_start <= o.ts < recent_start]
    return recent, baseline


# ── Per-voice KS analysis ──────────────────────────────────────────────
def analyze_voice(
    voice_name: str,
    recent: list[VoiceObservation],
    baseline: list[VoiceObservation],
    ks_threshold: float,
    alpha: float,
) -> DriftResult:
    recent_v = [o.confidence for o in recent if o.voice_name == voice_name]
    baseline_v = [o.confidence for o in baseline if o.voice_name == voice_name]
    n_recent = len(recent_v)
    n_baseline = len(baseline_v)
    adequacy = {
        "min_samples_per_window": MIN_SAMPLES_PER_WINDOW,
        "recent_sufficient": n_recent >= MIN_SAMPLES_PER_WINDOW,
        "baseline_sufficient": n_baseline >= MIN_SAMPLES_PER_WINDOW,
        "ks_threshold": ks_threshold,
        "alpha": alpha,
    }
    if n_recent < 1 or n_baseline < 1:
        adequacy["reason"] = "insufficient_window (one or both empty)"
        return DriftResult(
            voice_name=voice_name,
            n_recent=n_recent,
            n_baseline=n_baseline,
            recent_mean=None,
            baseline_mean=None,
            recent_stddev=None,
            baseline_stddev=None,
            ks_statistic=None,
            p_value=None,
            drift_detected=False,
            adequacy=adequacy,
        )
    rec_arr = np.asarray(recent_v, dtype=float)
    base_arr = np.asarray(baseline_v, dtype=float)
    recent_mean = float(rec_arr.mean())
    baseline_mean = float(base_arr.mean())
    recent_stddev = float(rec_arr.std(ddof=1)) if n_recent > 1 else 0.0
    baseline_stddev = float(base_arr.std(ddof=1)) if n_baseline > 1 else 0.0
    ks_stat, p_val = ks_2samp(rec_arr, base_arr)
    ks_stat = float(ks_stat)
    p_val = float(p_val)
    drift_detected = (
        adequacy["recent_sufficient"]
        and adequacy["baseline_sufficient"]
        and ks_stat >= ks_threshold
        and p_val < alpha
    )
    if not adequacy["recent_sufficient"]:
        adequacy["reason"] = f"recent_window_too_small (n={n_recent} < {MIN_SAMPLES_PER_WINDOW})"
    elif not adequacy["baseline_sufficient"]:
        adequacy["reason"] = (
            f"baseline_window_too_small (n={n_baseline} < {MIN_SAMPLES_PER_WINDOW})"
        )
    elif drift_detected:
        adequacy["reason"] = f"drift_detected (ks={ks_stat:.3f}, p={p_val:.4f})"
    else:
        adequacy["reason"] = f"no_drift (ks={ks_stat:.3f}, p={p_val:.4f})"
    return DriftResult(
        voice_name=voice_name,
        n_recent=n_recent,
        n_baseline=n_baseline,
        recent_mean=recent_mean,
        baseline_mean=baseline_mean,
        recent_stddev=recent_stddev,
        baseline_stddev=baseline_stddev,
        ks_statistic=ks_stat,
        p_value=p_val,
        drift_detected=drift_detected,
        adequacy=adequacy,
    )


# ── Report builder ─────────────────────────────────────────────────────
def build_report(
    recent_days: int = DEFAULT_RECENT_DAYS,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    ks_threshold: float = DEFAULT_KS_THRESHOLD,
    alpha: float = DEFAULT_ALPHA,
    reference: dt.datetime | None = None,
) -> dict:
    observations = load_voice_observations()
    recent, baseline = split_windows(observations, recent_days, baseline_days, reference)
    voice_names = sorted({o.voice_name for o in observations})
    results = [
        analyze_voice(v, recent, baseline, ks_threshold, alpha) for v in voice_names
    ]
    return {
        "windowing": {
            "recent_days": recent_days,
            "baseline_days": baseline_days,
            "reference_ts": (reference or dt.datetime.now(dt.UTC)).isoformat(),
        },
        "thresholds": {
            "ks_threshold": ks_threshold,
            "alpha": alpha,
            "min_samples_per_window": MIN_SAMPLES_PER_WINDOW,
        },
        "totals": {
            "n_observations": len(observations),
            "n_recent": len(recent),
            "n_baseline": len(baseline),
            "n_drift_detected": sum(1 for r in results if r.drift_detected),
        },
        "voices": [asdict(r) for r in results],
    }


# ── Text rendering ─────────────────────────────────────────────────────
def render_text(report: dict) -> str:
    lines: list[str] = []
    w = report["windowing"]
    th = report["thresholds"]
    t = report["totals"]
    lines.append("=" * 92)
    lines.append("VOICE DRIFT REPORT (KS-test)")
    lines.append("=" * 92)
    lines.append(
        f"  Window: recent={w['recent_days']}d vs baseline={w['baseline_days']}d  "
        f"reference_ts={w['reference_ts'][:19]}"
    )
    lines.append(
        f"  Thresholds: KS>={th['ks_threshold']}  alpha={th['alpha']}  "
        f"min_samples_per_window={th['min_samples_per_window']}"
    )
    lines.append(
        f"  Observations: total={t['n_observations']}  recent={t['n_recent']}  "
        f"baseline={t['n_baseline']}  drift_detected={t['n_drift_detected']}"
    )
    lines.append("")
    for r in report["voices"]:
        lines.append("-" * 92)
        flag = "⚠ DRIFT" if r["drift_detected"] else "  ok   "
        lines.append(f"  {flag}  {r['voice_name']}")
        lines.append(
            f"    recent: n={r['n_recent']:3d}  mean={r['recent_mean']}  "
            f"stddev={r['recent_stddev']}"
            if r["recent_mean"] is not None
            else f"    recent: n={r['n_recent']:3d}  (no data)"
        )
        lines.append(
            f"    baseline: n={r['n_baseline']:3d}  mean={r['baseline_mean']}  "
            f"stddev={r['baseline_stddev']}"
            if r["baseline_mean"] is not None
            else f"    baseline: n={r['n_baseline']:3d}  (no data)"
        )
        if r["ks_statistic"] is not None:
            lines.append(
                f"    KS={r['ks_statistic']:.4f}  p={r['p_value']:.4f}  "
                f"-> {r['adequacy']['reason']}"
            )
        else:
            lines.append(f"    {r['adequacy']['reason']}")
    lines.append("=" * 92)
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────
def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--recent-days", type=int, default=DEFAULT_RECENT_DAYS)
    ap.add_argument("--baseline-days", type=int, default=DEFAULT_BASELINE_DAYS)
    ap.add_argument("--ks-threshold", type=float, default=DEFAULT_KS_THRESHOLD)
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    report = build_report(
        recent_days=a.recent_days,
        baseline_days=a.baseline_days,
        ks_threshold=a.ks_threshold,
        alpha=a.alpha,
    )
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    if not a.quiet:
        print(render_text(report))
        print(f"\nJSON written to {a.out}")


if __name__ == "__main__":
    _cli()
