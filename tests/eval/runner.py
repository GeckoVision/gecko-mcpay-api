"""Pro tier eval harness runner.

Defaults:
  --suite all     — runs general + crypto + saas (50 ideas total)
  --live False    — uses canned transcripts from `tests/eval/mocks.py`
  --reruns 1      — single pass per idea
  --baseline None — no diff; just save a new baseline JSON

Usage:
    uv run python -m tests.eval.runner
    uv run python -m tests.eval.runner --suite crypto
    uv run python -m tests.eval.runner --suite saas --live
    uv run python -m tests.eval.runner --idea good-devbrief
    uv run python -m tests.eval.runner --suite general \\
        --baseline tests/eval/baselines/general_baseline.json

Design notes:
  - The harness imports `gecko_core.orchestration.pro.generate` only when
    `--live` is set, so mock runs don't pull AG2 into the import graph.
  - JSON output is the canonical artifact. We don't write to Supabase or
    session_costs — this is a developer tool, not part of the user pipeline.
  - Exit code is non-zero on >15% regression on any of: verdict_accuracy,
    median_score, median_cost_usd. Used by CI.
  - Per-suite baselines live at `tests/eval/baselines/{suite}_baseline.json`.
    Live runs are captured separately under `tests/eval/live_runs/`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tests.eval.mocks import MOCK_TRANSCRIPTS, MockTranscript, get_mock_transcript
from tests.eval.rubric import (
    RubricScores,
    extract_verdict,
    score_transcript_live,
    score_transcript_mock,
)

EVAL_DIR = Path(__file__).parent
SUITES_DIR = EVAL_DIR / "suites"
BASELINES_DIR = EVAL_DIR / "baselines"
LIVE_RUNS_DIR = EVAL_DIR / "live_runs"

SUITE_NAMES = ("general", "crypto", "saas")

# Used to estimate cost in mock mode and as a sanity floor in live mode.
# These are the OpenRouter passthrough rates for the default model matrix
# at time of writing (April 2026). Update with the routing matrix from S1-02.
COST_PER_1K_IN_USD = 0.00015  # gpt-4o-mini in
COST_PER_1K_OUT_USD = 0.0006  # gpt-4o-mini out


@dataclass
class IdeaResult:
    id: str
    expected_verdict: str
    actual_verdict: str
    scores: dict[str, float]
    wall_seconds: float
    tokens_total: int
    cost_usd: float


def _suite_path(suite: str) -> Path:
    return SUITES_DIR / f"{suite}_suite.json"


def _load_suite(suite: str) -> list[dict[str, Any]]:
    """Load a single suite's idea list from `tests/eval/suites/{suite}_suite.json`."""
    path = _suite_path(suite)
    if not path.exists():
        raise SystemExit(f"suite file missing: {path}")
    with path.open("r", encoding="utf-8") as f:
        ideas = json.load(f)
    if not isinstance(ideas, list):
        raise SystemExit(f"suite {suite!r} root is not a list")
    return ideas


def _load_ideas(filter_id: str | None = None, suite: str | None = None) -> list[dict[str, Any]]:
    """Load ideas across one or all suites; preserves prior signature for tests.

    `suite=None` is treated as "all suites concatenated" so legacy test code
    that calls `_load_ideas(filter_id=None)` keeps working.
    """
    suites = [suite] if suite else list(SUITE_NAMES)
    ideas: list[dict[str, Any]] = []
    for s in suites:
        for idea in _load_suite(s):
            idea = {**idea, "_suite": s}
            ideas.append(idea)
    if filter_id:
        ideas = [i for i in ideas if i["id"] == filter_id]
        if not ideas:
            raise SystemExit(f"no idea with id={filter_id!r}")
    return ideas


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=EVAL_DIR.parent.parent, text=True
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _estimate_cost(tokens_in: int, tokens_out: int) -> float:
    return round(
        (tokens_in / 1000) * COST_PER_1K_IN_USD + (tokens_out / 1000) * COST_PER_1K_OUT_USD,
        4,
    )


def _transcript_total_tokens(t: MockTranscript) -> int:
    return sum(turn["tokens_in"] + turn["tokens_out"] for turn in t.values())


async def _run_live(idea_text: str) -> MockTranscript:
    """Run the real Pro debate; return a transcript shaped like a MockTranscript."""
    # Imported here so mock mode doesn't pay AG2 import cost.
    import os

    from gecko_core.orchestration.pro import generate

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set; --live requires it for the 5 AG2 agents. "
            "Run without --live to use mock mode (default, $0)."
        )
    # Also fail-fast check for the rubric judge so we don't burn $$$ on agents
    # only to crash at scoring time.
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")):
        raise SystemExit(
            "ANTHROPIC_API_KEY (or CLAUDE_API_KEY) is not set; --live requires it for "
            "the Sonnet 4.6 rubric judge. Run without --live to use mock mode (default, $0)."
        )

    llm_config = {
        "config_list": [{"model": "gpt-4o-mini", "api_key": api_key}],
        "temperature": 0.3,
    }
    transcript = await generate(idea=idea_text, rag_context="", llm_config=llm_config)
    out: MockTranscript = {}
    for turn in transcript.turns:
        out[turn.agent] = {
            "text": turn.content,
            "tokens_in": turn.tokens_in,
            "tokens_out": turn.tokens_out,
        }
    return out


def _normalize_verdict(v: str) -> str:
    """Treat `pivot` as kill-equivalent for accuracy scoring.

    The judge often softens a real kill into a pivot recommendation; treating
    them as the same bucket keeps verdict_accuracy honest without forcing
    the judge into a binary it doesn't want.
    """
    return "kill" if v in ("kill", "pivot") else v


async def _evaluate_one(
    idea: dict[str, Any],
    *,
    live: bool,
    reruns: int,
    cohort_median_tokens: float,
) -> IdeaResult:
    """Run one idea `reruns` times, average the scores, return an IdeaResult."""
    score_accum: list[RubricScores] = []
    verdicts: list[str] = []
    wall_accum: list[float] = []
    tokens_accum: list[int] = []
    cost_accum: list[float] = []

    for _ in range(reruns):
        t0 = time.perf_counter()
        if live:
            transcript = await _run_live(idea["text"])
            scores = score_transcript_live(transcript)
        else:
            transcript = get_mock_transcript(idea["id"])
            scores = score_transcript_mock(transcript, cohort_median_tokens)
        wall = time.perf_counter() - t0

        score_accum.append(scores)
        verdicts.append(extract_verdict(transcript.get("judge", {"text": ""})["text"]))
        total = _transcript_total_tokens(transcript)
        tokens_accum.append(total)
        in_total = sum(t["tokens_in"] for t in transcript.values())
        out_total = sum(t["tokens_out"] for t in transcript.values())
        cost_accum.append(_estimate_cost(in_total, out_total))
        wall_accum.append(wall)

    # Average scores across reruns; verdict = mode-equivalent (first one).
    avg = RubricScores(
        agent_voice=round(statistics.mean(s.agent_voice for s in score_accum), 2),
        source_grounding=round(statistics.mean(s.source_grounding for s in score_accum), 2),
        verdict_justification=round(
            statistics.mean(s.verdict_justification for s in score_accum), 2
        ),
        cost_predictability=round(statistics.mean(s.cost_predictability for s in score_accum), 2),
    )
    return IdeaResult(
        id=idea["id"],
        expected_verdict=idea["expected_verdict"],
        actual_verdict=verdicts[0],
        scores=avg.to_dict(),
        wall_seconds=round(statistics.mean(wall_accum), 3),
        tokens_total=int(statistics.mean(tokens_accum)),
        cost_usd=round(statistics.mean(cost_accum), 4),
    )


def _aggregate(results: list[IdeaResult]) -> dict[str, Any]:
    if not results:
        return {
            "kill_rate": 0.0,
            "verdict_accuracy": 0.0,
            "median_score": 0.0,
            "median_cost_usd": 0.0,
            "n": 0,
        }
    correct = sum(
        1
        for r in results
        if _normalize_verdict(r.actual_verdict) == _normalize_verdict(r.expected_verdict)
    )
    kills = sum(1 for r in results if _normalize_verdict(r.actual_verdict) == "kill")
    median_scores = [statistics.median(r.scores.values()) for r in results]
    return {
        "kill_rate": round(kills / len(results), 3),
        "verdict_accuracy": round(correct / len(results), 3),
        "median_score": round(statistics.median(median_scores), 3),
        "median_cost_usd": round(statistics.median(r.cost_usd for r in results), 4),
        "n": len(results),
    }


async def _run_one_suite(
    suite: str,
    *,
    live: bool,
    reruns: int,
    filter_id: str | None,
) -> tuple[list[IdeaResult], dict[str, Any]]:
    ideas = _load_ideas(filter_id=filter_id, suite=suite)

    # Compute cohort median tokens FIRST so cost_predictability has a stable
    # reference. In mock mode we know the transcripts up-front; in live mode
    # we do a per-idea fall-through (cohort_median ignored by the live path).
    if not live:
        cohort_totals = [
            _transcript_total_tokens(MOCK_TRANSCRIPTS.get(i["id"], get_mock_transcript(i["id"])))
            for i in ideas
        ]
        cohort_median = statistics.median(cohort_totals) if cohort_totals else 0.0
    else:
        cohort_median = 0.0

    results: list[IdeaResult] = []
    print(f"\n[suite={suite}] {len(ideas)} ideas")
    for idea in ideas:
        r = await _evaluate_one(idea, live=live, reruns=reruns, cohort_median_tokens=cohort_median)
        results.append(r)
        print(
            f"  {r.id:<48} expected={r.expected_verdict:<5} actual={r.actual_verdict:<7} "
            f"median_score={statistics.median(r.scores.values()):.2f} "
            f"tokens={r.tokens_total} cost=${r.cost_usd:.4f}"
        )
    return results, _aggregate(results)


async def run_eval(
    *,
    live: bool,
    reruns: int,
    filter_id: str | None,
    suite: str = "all",
) -> dict[str, Any]:
    """Run one or all suites; payload always includes `suite` field.

    For suite=='all', payload contains a `suites` map with per-suite
    breakdown plus a top-level `aggregate` rolled up across all 50 ideas.
    """
    suites_to_run: list[str] = list(SUITE_NAMES) if suite == "all" else [suite]

    all_results: list[IdeaResult] = []
    per_suite: dict[str, dict[str, Any]] = {}
    for s in suites_to_run:
        results, agg = await _run_one_suite(s, live=live, reruns=reruns, filter_id=filter_id)
        per_suite[s] = {
            "aggregate": agg,
            "ideas": [asdict(r) for r in results],
        }
        all_results.extend(results)

    payload: dict[str, Any] = {
        "date": time.strftime("%Y-%m-%d"),
        "git_sha": _git_sha(),
        "mode": "live" if live else "mock",
        "reruns": reruns,
        "suite": suite,
        "aggregate": _aggregate(all_results),
    }
    if suite == "all":
        payload["suites"] = per_suite
    else:
        # Single-suite shape: keep top-level `ideas` for backwards compat with
        # the old per-day baseline format and downstream tooling.
        payload["ideas"] = per_suite[suite]["ideas"]
    return payload


def _save_baseline(payload: dict[str, Any]) -> Path:
    """Save mock-mode runs to `baselines/{suite}_baseline.json`; live to `live_runs/`.

    Mock-mode is canonical for CI gates, so we overwrite a single per-suite
    file rather than a dated history (the dated files in baselines/ are kept
    for archaeology but no longer canonical).
    """
    suite = payload.get("suite", "all")
    if payload["mode"] == "live":
        LIVE_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = LIVE_RUNS_DIR / f"{payload['date']}-{suite}.json"
        if out_path.exists():
            i = 2
            while True:
                candidate = LIVE_RUNS_DIR / f"{payload['date']}-{suite}-{i}.json"
                if not candidate.exists():
                    out_path = candidate
                    break
                i += 1
    else:
        BASELINES_DIR.mkdir(parents=True, exist_ok=True)
        out_path = BASELINES_DIR / f"{suite}_baseline.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out_path


def _diff_against_baseline(current: dict[str, Any], baseline_path: Path) -> int:
    """Return non-zero exit code if any axis regressed >15% vs baseline."""
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    base_agg = base["aggregate"]
    cur_agg = current["aggregate"]

    THRESHOLD = 0.15
    regressions: list[str] = []

    def _check(name: str, *, lower_is_worse: bool) -> None:
        b = base_agg.get(name, 0.0)
        c = cur_agg.get(name, 0.0)
        if b == 0:
            return
        delta = (c - b) / b
        worse = (delta < -THRESHOLD) if lower_is_worse else (delta > THRESHOLD)
        marker = "WORSE" if worse else "ok"
        sign = "+" if delta >= 0 else ""
        print(
            f"  {name:<20} baseline={b:.3f}  current={c:.3f}  delta={sign}{delta * 100:.1f}%  [{marker}]"
        )
        if worse:
            regressions.append(name)

    print(f"\nDiff vs {baseline_path.name}:")
    _check("verdict_accuracy", lower_is_worse=True)
    _check("median_score", lower_is_worse=True)
    _check("median_cost_usd", lower_is_worse=False)  # cost going UP is bad

    if regressions:
        print(f"\nFAIL: regression on {regressions} exceeds {int(THRESHOLD * 100)}% threshold")
        return 1
    print("\nOK: no regressions exceed threshold")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tests.eval.runner",
        description="Pro tier eval harness (mock by default).",
    )
    p.add_argument(
        "--suite",
        choices=[*SUITE_NAMES, "all"],
        default="all",
        help="which suite to run (default: all = general + crypto + saas)",
    )
    p.add_argument("--live", action="store_true", help="real API calls (~$3-5/run)")
    p.add_argument("--reruns", type=int, default=1, help="passes per idea")
    p.add_argument("--idea", type=str, default=None, help="filter to a single idea id")
    p.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="path to baseline JSON; non-zero exit on >15%% regression",
    )
    p.add_argument(
        "--no-save",
        action="store_true",
        help="skip writing a new baseline JSON (useful for ad-hoc inspection)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    print(
        f"Pro eval harness | suite={args.suite} | "
        f"mode={'LIVE' if args.live else 'mock'} | reruns={args.reruns}"
        f"{' | filter=' + args.idea if args.idea else ''}"
    )

    payload = asyncio.run(
        run_eval(
            live=args.live,
            reruns=args.reruns,
            filter_id=args.idea,
            suite=args.suite,
        )
    )

    print(f"\nAggregate ({args.suite}): {json.dumps(payload['aggregate'], indent=2)}")
    if "suites" in payload:
        for s, body in payload["suites"].items():
            print(f"  {s:<8} -> {json.dumps(body['aggregate'])}")

    if not args.no_save:
        out = _save_baseline(payload)
        print(f"Saved -> {out}")

    if args.baseline:
        return _diff_against_baseline(payload, Path(args.baseline))
    return 0


if __name__ == "__main__":
    sys.exit(main())
