"""S20-COHERENCE-VERDICT-LABEL-01 — premise-incoherence flag scanner.

Scans the 5-agent debate transcript for the structured sentinel line
each voice is instructed to emit when the idea's premise itself fails
to compose (NOT just "weak market" or "feasibility risk" — those route
through PIVOT/REFINE). When ≥``COHERENCE_KILL_MIN_FLAGS`` distinct
voices flag premise incoherence, the synthesizer flips the headline
verdict to ``Verdict.KILL`` regardless of gap classification.

The legacy KILL token (S11 / pre-S17) meant "weak idea, don't build
as-is" and was renamed to PIVOT. The S20 KILL is a structurally
different label: it fires only on premise-incoherence consensus. The
re-introduction is intentional and the trigger condition is sharper —
see ``Verdict`` docstring for the full rename history.

The scanner is intentionally regex-driven and case-insensitive:
prompts evolve (v5.4 today, v5.5+ tomorrow) but the sentinel format
``INCOHERENT_PREMISE: yes`` is the contract surface. Any voice whose
content emits the sentinel counts once, no matter how many times it
repeats. The judge's verdict prose is also scanned because the judge
sometimes synthesises critic flags into its own sentence.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from gecko_core.orchestration.pro.transcript import AgentTurn

# Sentinel: ``INCOHERENT_PREMISE: yes``. Allow whitespace flexibility,
# match case-insensitively, and bind to a word-boundary so prose like
# "the idea is not incoherent_premise: …" can't false-positive (the
# prompt instructs voices to emit the line as a standalone sentinel).
_INCOHERENT_PATTERN = re.compile(
    r"\bINCOHERENT_PREMISE\s*:\s*yes\b",
    re.IGNORECASE,
)


def turn_flags_incoherent_premise(content: str) -> bool:
    """Return True iff the turn's content contains the sentinel line.

    Pure helper so call sites and tests can probe a single string
    without building a transcript.
    """
    return bool(_INCOHERENT_PATTERN.search(content or ""))


def count_incoherent_premise_flags(turns: Iterable[AgentTurn]) -> int:
    """Return the number of DISTINCT voices that flagged incoherence.

    A voice counts at most once even if it emits the sentinel in
    multiple turns — the synthesizer cares about voice-level consensus,
    not turn count. The judge counts as a voice; if the judge alone
    flags incoherence, that's 1 (≥2 needed for KILL).
    """
    flagged: set[str] = set()
    for turn in turns:
        if turn_flags_incoherent_premise(turn.content):
            flagged.add(turn.agent)
    return len(flagged)


# Sentinel: ``NO_SURVIVING_DISSENT: yes``. Emitted by the v5.5
# surviving_dissent post-processor when no dissent survived the debate.
# Eval-harness facing — the renderer ignores it.
_NO_SURVIVING_DISSENT_PATTERN = re.compile(
    r"\bNO_SURVIVING_DISSENT\s*:\s*yes\b",
    re.IGNORECASE,
)


def count_no_surviving_dissent_flags(
    turns: Iterable[AgentTurn] | list[dict[str, object]],
) -> int:
    """Count NO_SURVIVING_DISSENT: yes sentinel emissions across turns.

    Sibling to ``count_incoherent_premise_flags``. Accepts either a list
    of ``AgentTurn`` (production) or a list of plain dicts (eval harness
    replay path) — duck-typed on a ``content`` key/attribute.
    """
    count = 0
    for turn in turns:
        raw = turn.get("content", "") if isinstance(turn, dict) else getattr(turn, "content", "")
        content = raw if isinstance(raw, str) else ""
        if _NO_SURVIVING_DISSENT_PATTERN.search(content):
            count += 1
    return count


# Sentinel: ``idea_classification: <greenfield|iterative|unclear>``.
# Emitted by the judge as the FIRST line of its synthesis when the
# v5.5.1 named-rubric calibration upgrade is active. Sibling to
# the gap_classification / Final verdict / INCOHERENT_PREMISE sentinels:
# regex extraction from judge prose, no extra LLM call. Case-insensitive
# match because prompt drift across versions tends to flip casing.
_IDEA_CLASSIFICATION_PATTERN = re.compile(
    r"\bidea_classification\s*:\s*(greenfield|iterative|unclear)\b",
    re.IGNORECASE,
)

_IDEA_CLASSIFICATION_VALUES: frozenset[str] = frozenset({"greenfield", "iterative", "unclear"})


def extract_idea_classification(
    turns: Iterable[AgentTurn] | list[dict[str, object]],
) -> str | None:
    """Return the judge's idea_classification label, or None if absent.

    Scans turns in order and returns the FIRST match — the judge prompt
    instructs the agent to emit the sentinel as its very first output
    line, so any later mention (e.g. a critic quoting the judge) loses
    to the original. Caller normalises None to leave
    ``ResearchResult.idea_classification`` unset.

    Accepts the production AgentTurn shape and the eval-harness replay
    dict shape, mirroring ``count_no_surviving_dissent_flags``.
    """
    for turn in turns:
        raw = turn.get("content", "") if isinstance(turn, dict) else getattr(turn, "content", "")
        content = raw if isinstance(raw, str) else ""
        match = _IDEA_CLASSIFICATION_PATTERN.search(content)
        if match:
            label = match.group(1).lower()
            if label in _IDEA_CLASSIFICATION_VALUES:
                return label
    return None


# Sentinel: ``founder_posture: <high|moderate|unclear>``.
# Emitted by the judge as a sibling line to ``idea_classification`` when
# the v5.5.2 calibration upgrade is active (Alliance-style founder lens).
# The judge prompt asks for it; the post-processor batch extracts it again
# as a fallback so a missed sentinel does not silently null the field.
# Same regex shape as ``idea_classification`` for parity.
_FOUNDER_POSTURE_PATTERN = re.compile(
    r"\bfounder_posture\s*:\s*(high|moderate|unclear)\b",
    re.IGNORECASE,
)

_FOUNDER_POSTURE_VALUES: frozenset[str] = frozenset({"high", "moderate", "unclear"})


def extract_founder_posture(
    turns: Iterable[AgentTurn] | list[dict[str, object]],
) -> str | None:
    """Return the judge's founder_posture label, or None if absent.

    Sibling to :func:`extract_idea_classification`. First-match wins so
    a critic later quoting the judge can't override the original. Caller
    normalises None to leave ``ResearchResult.founder_posture`` unset
    (the post-processor JSON path then has a chance to fill it in).
    Accepts AgentTurn (production) and dict (eval-replay) shapes.
    """
    for turn in turns:
        raw = turn.get("content", "") if isinstance(turn, dict) else getattr(turn, "content", "")
        content = raw if isinstance(raw, str) else ""
        match = _FOUNDER_POSTURE_PATTERN.search(content)
        if match:
            label = match.group(1).lower()
            if label in _FOUNDER_POSTURE_VALUES:
                return label
    return None


__all__ = [
    "count_incoherent_premise_flags",
    "count_no_surviving_dissent_flags",
    "extract_founder_posture",
    "extract_idea_classification",
    "turn_flags_incoherent_premise",
]
