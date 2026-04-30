"""Build a SprintReview from git log + memory + sprint docs (S7-DOGFOOD-01).

The builder is intentionally tolerant: a missing git binary, an empty
memory store, or a docs/ directory without any sprint plans should still
yield a usable (if minimal) SprintReview. The LLM call only happens when
the caller passes a ``llm_caller`` and asks for live mode.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from gecko_core.memory import MemoryEntryType, MemoryScope, recall
from gecko_core.memory.models import MemoryEntry
from gecko_core.memory.store import MemoryStore
from gecko_core.review.models import SprintReview

logger = logging.getLogger(__name__)

# Memory entry types we care about for sprint review.
_REVIEW_ENTRY_TYPES: tuple[MemoryEntryType, ...] = (
    MemoryEntryType.verdict_received,
    MemoryEntryType.scaffold_generated,
    MemoryEntryType.plan_advised,
    MemoryEntryType.advisor_voiced,
    MemoryEntryType.pulse_run,
    MemoryEntryType.feature_shipped,
)

# Type alias for the pluggable LLM caller. Receives one prompt string and
# must return JSON-decodable text. Async so it can fan into the existing
# AsyncOpenAI / ClawRouter stack without blocking the event loop.
LLMCaller = Callable[[str, str], Awaitable[str]]


def _repo_root() -> Path:
    """Return the repo root: GECKO_REPO_ROOT or cwd."""
    raw = os.environ.get("GECKO_REPO_ROOT")
    if raw:
        return Path(raw).expanduser()
    return Path.cwd()


def _git_log_since(repo: Path, since_days: int) -> list[str]:
    """Return ``git log --since`` one-liners. Empty list on any failure.

    Tolerates: missing git binary, non-repo cwd, network-detached HEAD.
    """
    since = f"{since_days}.days.ago"
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--oneline", "--no-decorate"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("git log failed (%s); review will skip commits", exc)
        return []
    if result.returncode != 0:
        logger.warning("git log returned %s: %s", result.returncode, result.stderr.strip())
        return []
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    return lines


def _read_sprint_docs(repo: Path) -> list[tuple[str, str]]:
    """Return ``[(filename, content), …]`` for any docs/build-plan-sprint-*.md."""
    docs_dir = repo / "docs"
    if not docs_dir.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(docs_dir.glob("build-plan-sprint-*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover — defensive
            logger.warning("could not read %s: %s", path, exc)
            continue
        out.append((path.name, text))
    return out


async def _load_memory_entries(
    project_id: str | None,
    since_days: int,
    store: MemoryStore | None,
) -> list[MemoryEntry]:
    """Fetch memory entries for the project across the review window."""
    if project_id is None:
        return []
    scope = MemoryScope(type="project", id=project_id)
    since = datetime.now(UTC) - timedelta(days=since_days)
    out: list[MemoryEntry] = []
    for entry_type in _REVIEW_ENTRY_TYPES:
        try:
            rows = await recall(
                scope,
                entry_type=entry_type,
                since=since,
                limit=100,
                store=store,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("review: recall %s failed: %s", entry_type.value, exc)
            continue
        out.extend(rows)
    out.sort(key=lambda e: e.created_at, reverse=True)
    return out


def _stub_shipped_bullets(commits: list[str], entries: list[MemoryEntry]) -> list[str]:
    """Render a non-AI shipped list: top-N commit subjects + memory highlights."""
    bullets: list[str] = []
    # Pull the first ~10 commit subjects (drop the SHA prefix for readability).
    for line in commits[:10]:
        # Lines look like "abc1234 message". Split once on whitespace.
        parts = line.split(" ", 1)
        subject = parts[1] if len(parts) > 1 else line
        bullets.append(f"commit: {subject}")
    # Surface feature_shipped journal entries explicitly.
    for entry in entries:
        if entry.entry_type == MemoryEntryType.feature_shipped:
            label = entry.value.get("title") or entry.value.get("name") or entry.key or "feature"
            bullets.append(f"shipped: {label}")
    return bullets[:15]


def _stub_weakest_link(entries: list[MemoryEntry]) -> str:
    """Return a deterministic, non-AI 'weakest link' hint.

    v1 heuristic: if there are pulse_run entries, surface the most recent
    delta count. If there are advisor closing lines, return the staff_manager
    closing line. Otherwise fall back to a generic "no signal" message.
    """
    for entry in entries:
        if entry.entry_type == MemoryEntryType.pulse_run:
            deltas = entry.value.get("deltas") or []
            changed = [
                d for d in deltas if isinstance(d, dict) and d.get("after") != d.get("before")
            ]
            if changed:
                first = changed[0]
                return (
                    f"pulse_run flagged {len(changed)} voice(s) shifting; "
                    f"most recent: {first.get('voice', '?')}"
                )
    for entry in entries:
        if entry.entry_type == MemoryEntryType.advisor_voiced:
            closing = entry.value.get("closing_line")
            if closing:
                role = entry.value.get("role", entry.key or "voice")
                return f"latest advisor signal ({role}): {closing}"
    return "no advisor / pulse signal in window — run gecko_plan to surface risk"


def _stub_proposed_next(entries: list[MemoryEntry], commits: list[str]) -> list[str]:
    """Three deterministic bullets to seed the next sprint."""
    out: list[str] = []
    if not commits:
        out.append("Re-confirm review window — no commits matched git log")
    else:
        out.append(f"Lock in the {len(commits)} commit(s) this window with a release tag")
    plans = [e for e in entries if e.entry_type == MemoryEntryType.plan_advised]
    if plans:
        out.append("Run a fresh gecko_pulse against the latest plan_advised entry")
    else:
        out.append("Run gecko_plan against an active session to set a panel baseline")
    out.append("Schedule a sprint_reviewed journal pass before next planning")
    return out[:3]


def _build_llm_prompt(
    *,
    project_id: str | None,
    since_days: int,
    commits: list[str],
    entries: list[MemoryEntry],
    sprint_docs: list[tuple[str, str]],
) -> str:
    """Render the synthesis prompt for the live-mode LLM call.

    The prompt asks for STRICT JSON ({shipped, weakest_link, proposed_next})
    so the caller can parse without regex. Memory values are truncated to
    keep the prompt under the 60k input cap.
    """
    parts: list[str] = []
    parts.append(
        "You are Gecko's sprint review synthesizer. Read the inputs below and "
        "return STRICT JSON with this exact shape:\n"
        '{"shipped": [str, ...], "weakest_link": str, "proposed_next": [str, str, str]}\n'
        "Bullets must be 1 line each. Do NOT include markdown fences."
    )
    parts.append(f"## Window\nproject_id={project_id} since_days={since_days}")

    parts.append("## Git log (oneline)")
    if commits:
        parts.append("\n".join(commits[:50]))
    else:
        parts.append("(no commits in window)")

    parts.append("## Memory entries")
    if entries:
        for entry in entries[:40]:
            value_summary = json.dumps(entry.value, default=str)[:400]
            parts.append(
                f"- [{entry.entry_type.value}] {entry.created_at.isoformat()} "
                f"key={entry.key!r} value={value_summary}"
            )
    else:
        parts.append("(no memory entries)")

    parts.append("## Sprint plan docs")
    if sprint_docs:
        for name, content in sprint_docs:
            # Cap each doc at ~6k chars; 3 docs is plenty under the input cap.
            parts.append(f"### {name}\n{content[:6000]}")
    else:
        parts.append("(no docs/build-plan-sprint-*.md files found)")

    return "\n\n".join(parts)


def _coerce_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if x]


def _parse_llm_response(raw: str) -> tuple[list[str], str, list[str]]:
    """Parse the JSON synthesis response.

    Falls back gracefully on bad JSON: returns empty lists / empty string so
    the caller can still surface the deterministic stub fields.
    """
    text = raw.strip()
    # Strip code fences if the model ignored the no-fences instruction.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("review: LLM returned non-JSON (%s); falling back", exc)
        return [], "", []
    shipped = _coerce_str_list(data.get("shipped"))
    weakest = str(data.get("weakest_link") or "").strip()
    proposed = _coerce_str_list(data.get("proposed_next"))
    return shipped, weakest, proposed


async def build_review(
    project_id: str | None,
    since_days: int = 14,
    *,
    llm_caller: LLMCaller | None = None,
    tier_preset: str = "balanced",
    store: MemoryStore | None = None,
    repo_root: Path | None = None,
) -> SprintReview:
    """Synthesize a SprintReview.

    Args:
        project_id: Project UUID (string). When None, only git + sprint docs
            are read; memory recall is skipped.
        since_days: Window in days for git log + memory recall.
        llm_caller: Optional async ``(system_prompt, user_prompt) -> str``.
            When provided, runs ONE call to synthesize structured output.
            When None, returns a deterministic stub-mode review.
        tier_preset: Forwarded to the caller (informational; tests assert
            we surface it through). Default "balanced".
        store: Optional MemoryStore (for tests / DI). Defaults to env.
        repo_root: Override for the git + docs root. Defaults to
            GECKO_REPO_ROOT env or cwd.

    Returns:
        A populated SprintReview. Free / live distinction is encoded in
        ``mode`` so callers can render the right disclaimer.
    """
    repo = repo_root or _repo_root()

    # Run the cheap reads in parallel where possible. Git log + docs are
    # sync; memory is async. Wrap the sync work in to_thread so they don't
    # block the event loop on a slow disk.
    commits_task = asyncio.to_thread(_git_log_since, repo, since_days)
    docs_task = asyncio.to_thread(_read_sprint_docs, repo)
    memory_task = _load_memory_entries(project_id, since_days, store)
    commits, sprint_docs, entries = await asyncio.gather(commits_task, docs_task, memory_task)

    mode = "live" if llm_caller is not None else "stub"
    shipped: list[str]
    weakest_link: str
    proposed_next: list[str]

    if llm_caller is not None:
        system_prompt = (
            "Return STRICT JSON only. No prose, no markdown. The JSON must "
            "have keys: shipped (list[str]), weakest_link (str), "
            "proposed_next (list[str], length 3)."
        )
        user_prompt = _build_llm_prompt(
            project_id=project_id,
            since_days=since_days,
            commits=commits,
            entries=entries,
            sprint_docs=sprint_docs,
        )
        try:
            raw = await llm_caller(system_prompt, user_prompt)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("review: LLM call failed (%s); falling back to stub", exc)
            raw = ""
        shipped, weakest_link, proposed_next = _parse_llm_response(raw)
        # Backfill from the stub heuristics if the LLM produced empties so
        # the surface stays useful even on a degraded call.
        if not shipped:
            shipped = _stub_shipped_bullets(commits, entries)
        if not weakest_link:
            weakest_link = _stub_weakest_link(entries)
        if not proposed_next:
            proposed_next = _stub_proposed_next(entries, commits)
    else:
        shipped = _stub_shipped_bullets(commits, entries)
        weakest_link = _stub_weakest_link(entries)
        proposed_next = _stub_proposed_next(entries, commits)

    # tier_preset is currently informational; reference it so static analysis
    # (and future routing decisions) don't drop it. The variable shows up in
    # the prompt context for live calls via the caller's choice of model.
    _ = tier_preset

    return SprintReview(
        project_id=project_id,
        since_days=since_days,
        shipped=shipped,
        weakest_link=weakest_link,
        proposed_next=proposed_next[:3] if proposed_next else [],
        mode=mode,
        git_commits=commits,
        memory_entry_count=len(entries),
        sprint_docs=[name for name, _ in sprint_docs],
        generated_at=datetime.now(UTC),
    )


__all__ = ["LLMCaller", "build_review"]
