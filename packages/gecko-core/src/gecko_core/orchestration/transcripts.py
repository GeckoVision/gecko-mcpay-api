"""Production judge-transcript capture (S12-HARDEN-03).

Every successful `research()` call writes one transcript record to disk so
public verdicts surfaced via CDP Bazaar have an audit trail (compliance +
post-hoc review of misranked verdicts). Schema mirrors the eval-side capture
in `tests/eval/runner.py::_archive_live_transcript` so the two corpora can
be analyzed with the same tooling.

Storage choice — filesystem, per data-engineer's S13 memo
(`docs/strategy/sprint-13+-data-engineer-memo-2026-04-30.md` § Theme 1):
transcripts are immutable, append-only, and rarely queried by ID. JSON-blob
queries in Postgres are slow without indexes we won't have time to design
under S12. Filesystem now; promote to a thin `judge_transcripts (id, run_id,
fixture_id, transcript_path, created_at)` index table only if S13 rubric v2
needs cross-run SQL queries.

Path resolution:
  1. `GECKO_TRANSCRIPT_DIR` env var (operator override).
  2. `/var/lib/gecko/judge_transcripts/` if the parent is writable
     (production VMs / persistent volumes).
  3. `/tmp/gecko/transcripts/` fallback (ECS Fargate ephemeral filesystem,
     local dev). A clear log line indicates which path was chosen.

Toggle: `GECKO_TRANSCRIPT_CAPTURE` (default true). Set to `0`/`false`/`no`
to disable — tests do this so the suite doesn't litter $TMP.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from gecko_core.models import ResearchResult, Verdict

logger = logging.getLogger(__name__)


# Mirrors `gecko_core.workflows._JUDGE_VERDICT_RE` and
# `tests/eval/rubric._V2_VERDICT_RE` — single contract for the post-S11
# `Final verdict: KILL|REFINE|BUILD` line.
_JUDGE_VERDICT_RE = re.compile(r"(?im)^\s*(?:final\s+)?verdict\s*[:\-]\s*(KILL|REFINE|BUILD)\b")


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def is_capture_enabled() -> bool:
    """Read `GECKO_TRANSCRIPT_CAPTURE`. Default true in production.

    Tests (pytest) opt out via env var or by leaving it explicitly false.
    """
    raw = (os.environ.get("GECKO_TRANSCRIPT_CAPTURE") or "").strip().lower()
    if raw in _FALSE_VALUES:
        return False
    if raw in _TRUE_VALUES:
        return True
    # Default: enabled. Production should leave the env var unset.
    return True


def _resolve_transcript_dir() -> Path:
    """Pick the on-disk directory for transcript records.

    Production-first: `/var/lib/gecko/judge_transcripts/` when writable.
    Falls back to `/tmp/gecko/transcripts/` (ECS Fargate / local dev).
    Operator override via `GECKO_TRANSCRIPT_DIR` always wins.
    """
    override = (os.environ.get("GECKO_TRANSCRIPT_DIR") or "").strip()
    if override:
        return Path(override)

    candidate = Path("/var/lib/gecko/judge_transcripts")
    parent = candidate.parent
    # Try to create the prod dir; fall through on PermissionError or any
    # OSError (read-only fs, missing parent on ECS Fargate, etc.).
    try:
        if parent.exists() and os.access(parent, os.W_OK):
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
    except OSError:  # pragma: no cover — defensive
        pass

    return Path("/tmp/gecko/transcripts")


def _extract_judge_prose(result: ResearchResult) -> str:
    """Pull the judge's final paragraph from the result.

    Pro tier: the explicit `pro_session_summary` (set by `_run_pro_debate`).
    Basic tier: empty — there is no judge agent in basic. We still archive
    the parsed verdict + gap_classification + advisor data so the audit
    trail is complete for both tiers.
    """
    summary = getattr(result, "pro_session_summary", None)
    if isinstance(summary, str) and summary:
        return summary
    return ""


def _extract_agent_turns(result: ResearchResult) -> dict[str, dict[str, Any]] | None:
    """Reshape `transcript.turns` into the per-agent map the eval side uses.

    Mirrors the shape `tests/eval/runner.py::_archive_live_transcript`
    writes so a single jq pipeline can query both production and eval
    corpora. Returns None for basic-tier results (no transcript).
    """
    transcript = getattr(result, "transcript", None)
    if not isinstance(transcript, dict):
        return None
    raw_turns = transcript.get("turns")
    if not isinstance(raw_turns, list):
        return None
    out: dict[str, dict[str, Any]] = {}
    for turn in raw_turns:
        if not isinstance(turn, dict):
            continue
        agent = turn.get("agent")
        if not isinstance(agent, str):
            continue
        # Last turn per agent wins — matches the eval-side dict semantics
        # (`out[turn.agent] = ...` in `_run_live`).
        out[agent] = {
            "text": str(turn.get("content") or ""),
            "tokens_in": int(turn.get("tokens_in") or 0),
            "tokens_out": int(turn.get("tokens_out") or 0),
        }
    return out or None


def _parse_verdict_token(judge_prose: str) -> str:
    """Re-parse the post-S11 verdict token from the judge prose.

    The structured `result.verdict` is the canonical answer; this is the
    raw token-as-said for diagnosis (judge said BUILD but typed gap forced
    REFINE → audit trail makes the disagreement visible).
    """
    if not judge_prose:
        return "UNKNOWN"
    match = _JUDGE_VERDICT_RE.search(judge_prose)
    if match is None:
        return "UNKNOWN"
    return match.group(1).upper()


def capture(
    *,
    session_id: UUID,
    idea: str,
    result: ResearchResult,
) -> Path | None:
    """Write one transcript record for a successful research run.

    Best-effort: any error is logged + swallowed. We never want a disk
    write to take down a paid `/research` response.

    Returns the written path on success, None when capture is disabled or
    the write failed. Callers don't act on the return value — it's there
    for tests that want to assert the file exists.
    """
    if not is_capture_enabled():
        return None

    try:
        out_dir = _resolve_transcript_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("transcript capture: mkdir failed at %s: %s", out_dir, exc)
        return None

    judge_prose = _extract_judge_prose(result)
    agent_turns = _extract_agent_turns(result)

    # Map the structured Verdict back to the v1 ship/kill/pivot taxonomy
    # the eval rubric still grades on. Same mapping `workflows._detect_research_verdict`
    # uses, kept inline so a transcript record is self-contained.
    structured = getattr(result, "verdict", None)
    if isinstance(structured, Verdict):
        v1_map = {Verdict.BUILD: "ship", Verdict.KILL: "kill", Verdict.REFINE: "pivot"}
        actual_verdict = v1_map[structured]
        actual_verdict_v2 = structured.value  # "KILL" | "REFINE" | "BUILD"
    else:
        actual_verdict = "unknown"
        actual_verdict_v2 = "UNKNOWN"

    # Pull gap_classification + gap_summary from the validation_report
    # (the typed evidence the verdict was derived from). This is the
    # surface a misranked-verdict review most needs.
    validation_report = getattr(result, "validation_report", None)
    gap_classification = getattr(validation_report, "gap_classification", None)
    gap_summary = getattr(validation_report, "gap_summary", None)

    payload: dict[str, Any] = {
        # Schema kept aligned with `tests/eval/runner.py::_archive_live_transcript`
        # so production + eval transcripts share a query surface.
        "id": str(session_id),
        "session_id": str(session_id),
        "idea_text": idea,
        "tier": getattr(result, "tier", "basic"),
        "judge_prose": judge_prose,
        "parsed_verdict": _parse_verdict_token(judge_prose),
        "actual_verdict": actual_verdict,
        "actual_verdict_v2": actual_verdict_v2,
        "gap_classification": str(gap_classification) if gap_classification else None,
        "gap_summary": gap_summary if isinstance(gap_summary, str) else None,
        "agent_turns": agent_turns,
        # Reserved keys to match the eval-side schema exactly so a single
        # jq pipeline works across both corpora.
        "advisor_voices": None,
        "advisor_consensus": None,
        "rubric_score": None,
        "expected_verdict": None,
        "expected_verdict_v2": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    out_path = out_dir / f"{session_id}.json"
    try:
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("transcript capture: write failed at %s: %s", out_path, exc)
        return None

    logger.info(
        "transcript captured session_id=%s path=%s verdict=%s",
        session_id,
        out_path,
        actual_verdict_v2,
    )
    return out_path


__all__ = ["capture", "is_capture_enabled"]
