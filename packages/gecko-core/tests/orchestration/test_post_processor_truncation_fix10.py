"""S22-FIX-10 / FIX-11 — truncation handling for the remaining post-processors.

Mirrors ``test_post_processor_truncation_followup.py`` for the three
post-processors that previously routed truncation through the generic
``except Exception`` and silently returned ``None``:

- ``per_voice_extraction``
- ``transcript_summary`` (also covers FIX-11 — the ``pro_session_summary``
  surface degrades to ``transcript_summary`` when the judge transcript turn
  is itself degraded; hardening the post-processor closes the silent-null
  hole at the post-processor layer)
- ``classification_extraction``

Per ``feedback_lighter_tests.md``: helpers tested directly as pure
functions (no mocks, no asyncio); ONE end-to-end smoke per post-processor
that exercises the task with a monkeypatched ``_call_json`` raising
``LLMTruncationError``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from gecko_core.orchestration.llm_client import LLMTruncationError
from gecko_core.orchestration.pro import post_processors as pp
from gecko_core.orchestration.pro.post_processors import (
    _recover_classification_partial,
    _recover_per_voice_partial,
    _recover_transcript_summary_partial,
)

# ---------------------------------------------------------------------------
# Helper-level pure-function tests (no I/O, no async, no mocks).
# ---------------------------------------------------------------------------


def _voice_json(name: str = "analyst") -> str:
    return json.dumps(
        {
            "name": name,
            "position": f"{name}'s position",
            "tension": f"{name}'s tension",
            "recommendation": f"{name} recommends ship.",
            "status": "engaged",
        }
    )


def test_per_voice_partial_recovery_trim_trailing() -> None:
    a = _voice_json("analyst")
    b = _voice_json("critic")
    partial = '{"voices": [' + a + "," + b + ',{"name": "archi'
    result = _recover_per_voice_partial(partial)
    assert len(result.voices) == 2
    assert {v.name for v in result.voices} == {"analyst", "critic"}


def test_per_voice_zero_recovery_returns_empty() -> None:
    result = _recover_per_voice_partial('{"voi')
    assert result.voices == []


def test_transcript_summary_partial_recovery_marks_truncated() -> None:
    partial = (
        '{"summary": "The debate centered on whether the wedge is defensible against incumbents and'
    )
    out = _recover_transcript_summary_partial(partial)
    assert out is not None
    assert out.endswith("[truncated]")
    assert "wedge is defensible" in out


def test_transcript_summary_too_short_returns_none() -> None:
    partial = '{"summary": "tiny'
    out = _recover_transcript_summary_partial(partial)
    assert out is None


def test_transcript_summary_complete_payload_returns_value() -> None:
    full = '{"summary": "complete summary text here, fully closed."}'
    out = _recover_transcript_summary_partial(full)
    assert out == "complete summary text here, fully closed."


def test_classification_partial_recovers_both_labels() -> None:
    partial = '{"idea_classification": "iterative", "founder_posture": "high"'
    idea, founder = _recover_classification_partial(partial)
    assert idea == "iterative"
    assert founder == "high"


def test_classification_partial_recovers_only_first_label() -> None:
    partial = '{"idea_classification": "greenfield", "founder_post'
    idea, founder = _recover_classification_partial(partial)
    assert idea == "greenfield"
    assert founder is None


def test_classification_invalid_label_dropped() -> None:
    partial = '{"idea_classification": "bogus_label", "founder_posture": "moderate"}'
    idea, founder = _recover_classification_partial(partial)
    assert idea is None
    assert founder == "moderate"


# ---------------------------------------------------------------------------
# End-to-end smokes — ONE per post-processor, using the same drive helper
# pattern as test_post_processor_truncation_followup.py.
# ---------------------------------------------------------------------------


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    *,
    per_voice_side_effect: Any = None,
    summary_side_effect: Any = None,
    classify_side_effect: Any = None,
    tracker: Any = None,
) -> Any:
    import asyncio

    from gecko_core.orchestration.pro.transcript import DebateTranscript

    monkeypatch.setattr(
        pp,
        "load_post_processors",
        lambda: {
            "per_voice_extraction": "SYS_PER_VOICE",
            "transcript_summary": "SYS_SUMMARY",
            "market_landscape": "SYS_LANDSCAPE",
            "surviving_dissent": "SYS_DISSENT",
            "next_steps_with_falsifiers": "SYS_STEPS",
            "classification_extraction": "SYS_CLASSIFY",
        },
    )

    class _Closeable:
        async def close(self) -> None:
            return None

    monkeypatch.setattr(pp, "_build_client", lambda: _Closeable())

    async def _fake_call_json(
        client: Any,
        *,
        system: str,
        user: str,
        model_cls: Any = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if system == "SYS_PER_VOICE":
            if isinstance(per_voice_side_effect, BaseException):
                raise per_voice_side_effect
            return {"voices": []}
        if system == "SYS_SUMMARY":
            if isinstance(summary_side_effect, BaseException):
                raise summary_side_effect
            return {"summary": "ok"}
        if system == "SYS_CLASSIFY":
            if isinstance(classify_side_effect, BaseException):
                raise classify_side_effect
            return {"idea_classification": "unclear", "founder_posture": "unclear"}
        if system == "SYS_LANDSCAPE":
            return {"competitors": [], "section_flag": None}
        if system == "SYS_DISSENT":
            return {"dissent_status": "no_surviving_dissent", "dissents": [], "rationale": ""}
        if system == "SYS_STEPS":
            return {"steps": []}
        return {}

    monkeypatch.setattr(pp, "_call_json", _fake_call_json)

    transcript = DebateTranscript(turns=[], total_tokens_in=0, total_tokens_out=0)

    async def _go() -> Any:
        return await pp.run_post_processors(transcript, "ctx", "idea", tracker=tracker)

    return asyncio.run(_go())


def test_per_voice_truncation_recovers_via_task(monkeypatch: pytest.MonkeyPatch) -> None:
    a = _voice_json("analyst")
    partial = '{"voices": [' + a + ',{"name": "crit'
    exc = LLMTruncationError("trunc", partial_content=partial)
    from gecko_core.orchestration.degraded import DegradedSectionTracker

    tracker = DegradedSectionTracker()
    per_voice, _, _, _, _, _ = _drive(monkeypatch, per_voice_side_effect=exc, tracker=tracker)
    assert per_voice is not None
    assert len(per_voice.voices) == 1
    assert tracker.to_dict().get("per_voice") == "truncated_partial_recovery"


def test_transcript_summary_truncation_recovers_non_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIX-11 regression — the post-processor surface that backs the
    pro_session_summary degraded path must NOT return None on truncation.
    """
    partial = (
        '{"summary": "Verdict: KILL — saturated with no named ICP. The debate '
        "showed that the analyst and critic both flagged the lack of"
    )
    exc = LLMTruncationError("trunc", partial_content=partial)
    from gecko_core.orchestration.degraded import DegradedSectionTracker

    tracker = DegradedSectionTracker()
    _, summary, _, _, _, _ = _drive(monkeypatch, summary_side_effect=exc, tracker=tracker)
    assert summary is not None
    assert summary.endswith("[truncated]")
    assert tracker.to_dict().get("transcript_summary") == "truncated_partial_recovery"


def test_classification_truncation_recovers_via_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = '{"idea_classification": "iterative", "founder_posture": "mod'
    exc = LLMTruncationError("trunc", partial_content=partial)
    from gecko_core.orchestration.degraded import DegradedSectionTracker

    tracker = DegradedSectionTracker()
    _, _, _, _, _, meta = _drive(monkeypatch, classify_side_effect=exc, tracker=tracker)
    assert meta.get("idea_classification") == "iterative"
    assert meta.get("founder_posture") is None
    assert tracker.to_dict().get("classification_extraction") == "truncated_partial_recovery"
