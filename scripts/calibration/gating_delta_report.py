#!/usr/bin/env python3
"""Aggregator gating-delta report — Sprint 3 S3-3.

Reads ``contest_bot/decision_runs/{run_id}/decisions.jsonl`` across all runs,
groups decisions by which ``coordinator_rule`` fired, and reports per-rule:

  - **Fire count + fraction** of all decisions where this rule was the
    one that determined the action.
  - **For act-rules** (``all_voices_aligned`` / ``chop_high_conviction`` /
    ``1h_adverse_high_conviction``): realized PnL distribution from the
    positions that actually opened — mean, stddev, win rate, n.
  - **For decline-rules** (``risk_veto`` / ``chart_below_threshold`` /
    ``chop_below_high_bar`` / ``1h_adverse_below_high_bar`` /
    ``memory_contradicts`` / ``chart_voice_missing``): fire count only
    (no outcome — position was not opened).

This is the **honest read** of which rules are load-bearing in current
production. Per ``feedback_prompt_iteration_plateau``, rules STAY in code
— this report does NOT propose changing them, it makes their per-rule
behavior visible so an operator can see "rule X is firing most, rule Y
produces our best act-decisions, rule Z hasn't fired once in 30d".

A TRUE counterfactual gating-delta ("what if we removed rule X — which
decisions would have flipped, what would those PnLs have been?") requires
A/B testing or shadow-mode replay against a different rule set; that's
out of scope for this script and belongs in a paired-replay harness
(future ticket). What we CAN measure from observed data is what's here:
fire frequency + outcome distribution per fire.

Output:
  JSON  : private/strategy/gating_delta_report.json
  text  : stdout

Run:
  uv run python scripts/calibration/gating_delta_report.py [--rule X]
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

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DECISION_RUNS_GLOB = os.path.join(_REPO_ROOT, "contest_bot", "decision_runs", "*", "decisions.jsonl")
DEFAULT_OUT = os.path.join(_REPO_ROOT, "private", "strategy", "gating_delta_report.json")

# Canonical rule taxonomy from coordinator_rules.py. Used to classify
# act-vs-decline at report time so the output is stable even when the
# coordinator file adds new labels (unknown rule → reported separately).
ACT_RULES = frozenset(
    {"all_voices_aligned", "chop_high_conviction", "1h_adverse_high_conviction"}
)
DECLINE_RULES = frozenset(
    {
        "risk_veto",
        "chart_below_threshold",
        "chop_below_high_bar",
        "1h_adverse_below_high_bar",
        "memory_contradicts",
        "chart_voice_missing",
    }
)

MIN_N_FOR_PNL_CLAIM = 30  # below this, the mean-PnL CI is too wide to act on


# ── Data shapes ────────────────────────────────────────────────────────
@dataclass
class RuleStats:
    rule: str
    rule_kind: str  # "act" | "decline" | "unknown"
    fire_count: int
    fire_fraction: float
    # Only populated for act rules with linked outcomes:
    n_with_outcome: int = 0
    mean_pnl_pct: float | None = None
    median_pnl_pct: float | None = None
    stddev_pnl_pct: float | None = None
    win_rate: float | None = None
    pnl_ci_low: float | None = None
    pnl_ci_high: float | None = None
    n_sufficient_for_pnl_claim: bool = False
    sample_outcomes: list[dict] = field(default_factory=list)


# ── Data loading ───────────────────────────────────────────────────────
def load_decision_runs() -> list[tuple[dict, dict | None]]:
    """Return [(decision_row, outcome_or_None)] across all runs.

    Decisions without a matching outcome row are still returned (outcome=None);
    that's normal for decline-rule decisions where no position opened.
    """
    decisions_by_id: dict[str, dict] = {}
    outcomes_by_id: dict[str, dict] = {}
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
                        decisions_by_id[did] = row
                    elif row.get("outcome"):
                        outcomes_by_id[did] = row["outcome"]
        except OSError:
            continue
    return [(d, outcomes_by_id.get(did)) for did, d in decisions_by_id.items()]


# ── Stats helpers ──────────────────────────────────────────────────────
def bootstrap_mean_ci(
    values: list[float], n_resamples: int = 1000, alpha: float = 0.05, seed: int = 1729
) -> tuple[float, float]:
    """Percentile-bootstrap CI for the mean. Returns (low, high)."""
    if not values:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    means = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        means[i] = arr[idx].mean()
    low = float(np.percentile(means, 100 * alpha / 2))
    high = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return low, high


def classify_rule(rule: str) -> str:
    if rule in ACT_RULES:
        return "act"
    if rule in DECLINE_RULES:
        return "decline"
    return "unknown"


# ── Per-rule analysis ──────────────────────────────────────────────────
def analyze_rule(
    rule: str, decisions_with_outcomes: list[tuple[dict, dict | None]], total: int
) -> RuleStats:
    rule_kind = classify_rule(rule)
    matching = [
        (d, o) for d, o in decisions_with_outcomes if (d.get("coordinator") or {}).get("rule") == rule
    ]
    fire_count = len(matching)
    fire_fraction = fire_count / total if total > 0 else 0.0
    stats = RuleStats(
        rule=rule,
        rule_kind=rule_kind,
        fire_count=fire_count,
        fire_fraction=fire_fraction,
    )
    if rule_kind != "act":
        # Decline rules don't have outcomes; just report fire count.
        return stats
    # Act rules — pull outcome rows and compute PnL stats.
    pnls: list[float] = []
    samples: list[dict] = []
    for d, o in matching:
        if not o or "pnl_pct" not in o:
            continue
        try:
            pnl = float(o["pnl_pct"])
        except (TypeError, ValueError):
            continue
        pnls.append(pnl)
        samples.append(
            {
                "decision_id": d.get("decision_id"),
                "symbol": d.get("symbol"),
                "ts": d.get("ts"),
                "pnl_pct": pnl,
                "exit_reason": o.get("exit_reason"),
                "duration_min": o.get("duration_min"),
            }
        )
    n_with_outcome = len(pnls)
    if n_with_outcome > 0:
        arr = np.asarray(pnls)
        stats.n_with_outcome = n_with_outcome
        stats.mean_pnl_pct = float(arr.mean())
        stats.median_pnl_pct = float(np.median(arr))
        stats.stddev_pnl_pct = float(arr.std(ddof=1)) if n_with_outcome > 1 else 0.0
        stats.win_rate = float((arr > 0).mean())
        if n_with_outcome >= 5:
            low, high = bootstrap_mean_ci(pnls)
            stats.pnl_ci_low = low
            stats.pnl_ci_high = high
        stats.n_sufficient_for_pnl_claim = n_with_outcome >= MIN_N_FOR_PNL_CLAIM
        # Sort samples by pnl ascending so the worst outcomes are visible first.
        samples.sort(key=lambda s: s["pnl_pct"])
        # Cap at 5 samples to keep the report readable.
        stats.sample_outcomes = samples[:5] if len(samples) <= 5 else samples[:3] + samples[-2:]
    return stats


# ── Report builder ─────────────────────────────────────────────────────
def build_report(rule_filter: str | None = None) -> dict:
    decisions_with_outcomes = load_decision_runs()
    total = len(decisions_with_outcomes)
    # Discover every rule actually present in the data, even unknown ones.
    rules_seen = sorted(
        {(d.get("coordinator") or {}).get("rule", "<missing>") for d, _ in decisions_with_outcomes}
    )
    if rule_filter:
        rules_seen = [r for r in rules_seen if r == rule_filter]
    rule_stats = [analyze_rule(r, decisions_with_outcomes, total) for r in rules_seen]
    # Order: act rules first (highest leverage to inspect), then decline,
    # then unknown — within each, by fire_count desc.
    rule_stats.sort(key=lambda s: ({"act": 0, "decline": 1, "unknown": 2}[s.rule_kind], -s.fire_count))
    return {
        "totals": {
            "n_decisions": total,
            "n_with_outcomes": sum(1 for _, o in decisions_with_outcomes if o),
            "n_rules_seen": len(rules_seen),
        },
        "rules": [asdict(s) for s in rule_stats],
        "adequacy_thresholds": {
            "min_n_for_pnl_claim": MIN_N_FOR_PNL_CLAIM,
        },
    }


# ── Text rendering ─────────────────────────────────────────────────────
def render_text(report: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 96)
    lines.append("AGGREGATOR GATING-DELTA REPORT")
    lines.append("=" * 96)
    t = report["totals"]
    lines.append(
        f"  Decisions: {t['n_decisions']}  with outcomes: {t['n_with_outcomes']}  "
        f"distinct rules fired: {t['n_rules_seen']}"
    )
    lines.append(f"  PnL-claim adequacy threshold: n >= {MIN_N_FOR_PNL_CLAIM}")
    lines.append("")
    for r in report["rules"]:
        lines.append("-" * 96)
        kind_tag = f"[{r['rule_kind'].upper()}]"
        lines.append(
            f"  {r['rule']:32s} {kind_tag:9s} fires={r['fire_count']:4d}  "
            f"({r['fire_fraction'] * 100:5.1f}% of decisions)"
        )
        if r["rule_kind"] == "act" and r["n_with_outcome"] > 0:
            adequacy = (
                "OK for PnL claim" if r["n_sufficient_for_pnl_claim"]
                else f"EXPLORATORY (n={r['n_with_outcome']} < {MIN_N_FOR_PNL_CLAIM})"
            )
            lines.append(
                f"    realized PnL: mean={r['mean_pnl_pct']:+.3f}%  "
                f"median={r['median_pnl_pct']:+.3f}%  stddev={r['stddev_pnl_pct']:.3f}%"
            )
            lines.append(
                f"    win rate: {r['win_rate'] * 100:.1f}%  ({adequacy})"
            )
            if r["pnl_ci_low"] is not None:
                ci_signal = (
                    "CI excludes 0 (+EV)" if r["pnl_ci_low"] > 0
                    else "CI excludes 0 (-EV)" if r["pnl_ci_high"] < 0
                    else "CI straddles 0"
                )
                lines.append(
                    f"    bootstrap 95% CI on mean: "
                    f"[{r['pnl_ci_low']:+.3f}%, {r['pnl_ci_high']:+.3f}%]  ({ci_signal})"
                )
            if r["sample_outcomes"]:
                lines.append("    worst + best samples:")
                for s in r["sample_outcomes"]:
                    lines.append(
                        f"      {s['symbol']:6s} {s['ts'][:19]}  "
                        f"pnl={s['pnl_pct']:+.2f}%  exit={s['exit_reason']}  "
                        f"hold={s['duration_min']:.1f}m"
                    )
    lines.append("=" * 96)
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────
def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rule", default=None, help="Filter to a single rule name")
    ap.add_argument("--out", default=DEFAULT_OUT, help="Output JSON path")
    ap.add_argument("--quiet", action="store_true", help="Skip text output")
    a = ap.parse_args()
    report = build_report(rule_filter=a.rule)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(report, f, indent=2)
    if not a.quiet:
        print(render_text(report))
        print(f"\nJSON written to {a.out}")


if __name__ == "__main__":
    _cli()
