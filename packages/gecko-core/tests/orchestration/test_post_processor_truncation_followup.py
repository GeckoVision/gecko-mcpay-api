"""S21-FIX-07 — surviving_dissent + next_steps_with_falsifiers truncation handling.

Production session ``cae5ab28`` returned ``surviving_dissent: null`` and
``next_steps_with_falsifiers: null`` because deepseek-v4-flash hit its
2000-token cap on those two post-processors. The fix mirrors S20-FIX-05
for market_landscape:

1. Bump ``max_tokens`` to 4000 (tunable via env).
2. Best-effort parse on truncation — recover the valid prefix instead of
   dropping the whole section.
3. Surface the failure mode via ``section_flag``
   (``truncated_partial_recovery`` / ``truncated_zero_recovery``).
4. Mark the DegradedSectionTracker so OBS-01 stamps
   ``ResearchResult.degraded_sections``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from gecko_core.orchestration.degraded import DegradedSectionTracker
from gecko_core.orchestration.llm_client import LLMTruncationError
from gecko_core.orchestration.pro import post_processors as pp
from gecko_core.orchestration.pro.post_processors import (
    _recover_next_steps_partial,
    _recover_surviving_dissent_partial,
)

# ---------------------------------------------------------------------------
# Direct partial-recovery helper tests (no I/O, no async).
# ---------------------------------------------------------------------------


def _dissent_json(voice: str = "analyst") -> str:
    return json.dumps(
        {
            "voice": voice,
            "verbatim": f"{voice} says the wedge is too narrow to defend.",
            "on_topic": "Surfaces a real risk to the verdict.",
        }
    )


def _step_json(action_idx: int, voice: str = "analyst") -> str:
    return json.dumps(
        {
            "action": f"Action #{action_idx}: ship a falsifiable test.",
            "surfaced_by_voice": voice,
            "falsifier": {
                "what_would_disprove_this": "If the test passes for 3 cohorts, the action is wrong.",
                "by_when": "2026-06-01",
            },
        }
    )


# --- surviving_dissent helper tests ---


def test_surviving_dissent_happy_passthrough_unused() -> None:
    """The helper is for truncation-recovery; calling on a complete payload
    that has the dissents marker still trims sensibly. Passing a fully
    formed JSON returns the parsed dissents with partial_recovery flag
    (since recovery always stamps a flag — that is its contract)."""
    a = _dissent_json("analyst")
    b = _dissent_json("critic")
    full = '{"dissent_status": "surviving", "dissents": [' + a + "," + b + "]}"
    result = _recover_surviving_dissent_partial(full)
    assert result.section_flag == "truncated_partial_recovery"
    assert len(result.dissents) == 2
    assert {d.voice for d in result.dissents} == {"analyst", "critic"}


def test_surviving_dissent_partial_recovery_trim_trailing() -> None:
    """Truncated mid-third-entry: 2 valid dissents recovered."""
    a = _dissent_json("analyst")
    b = _dissent_json("critic")
    partial = '{"dissents": [' + a + "," + b + ',{"voice": "archi'
    result = _recover_surviving_dissent_partial(partial)
    assert result.section_flag == "truncated_partial_recovery"
    assert len(result.dissents) == 2
    assert {d.voice for d in result.dissents} == {"analyst", "critic"}


def test_surviving_dissent_total_truncation_zero_recovery() -> None:
    """Truncation so early no parseable dissent → zero-recovery flag."""
    partial = '{"diss'
    result = _recover_surviving_dissent_partial(partial)
    assert result.section_flag == "truncated_zero_recovery"
    assert result.dissents == []
    assert result.dissent_status == "no_surviving_dissent"


# --- next_steps helper tests ---


def test_next_steps_happy_passthrough() -> None:
    """Full payload with two well-formed steps → both recovered."""
    s1 = _step_json(1, "analyst")
    s2 = _step_json(2, "critic")
    full = '{"steps": [' + s1 + "," + s2 + "]}"
    result = _recover_next_steps_partial(full)
    assert result.section_flag == "truncated_partial_recovery"
    assert len(result.steps) == 2


def test_next_steps_partial_recovery_trim_trailing() -> None:
    """Truncated mid-third-step: 2 valid steps recovered."""
    s1 = _step_json(1, "analyst")
    s2 = _step_json(2, "critic")
    partial = '{"steps": [' + s1 + "," + s2 + ',{"action": "Third'
    result = _recover_next_steps_partial(partial)
    assert result.section_flag == "truncated_partial_recovery"
    assert len(result.steps) == 2


def test_next_steps_total_truncation_zero_recovery() -> None:
    """Truncation before any step parseable → zero-recovery flag."""
    partial = '{"step'
    result = _recover_next_steps_partial(partial)
    assert result.section_flag == "truncated_zero_recovery"
    assert result.steps == []


def test_next_steps_drops_step_missing_falsifier() -> None:
    """A step with no falsifier dict is invalid → dropped silently."""
    bad = json.dumps({"action": "x", "surfaced_by_voice": "analyst"})
    good = _step_json(1, "analyst")
    partial = '{"steps": [' + bad + "," + good + "]}"
    result = _recover_next_steps_partial(partial)
    assert len(result.steps) == 1
    assert result.steps[0].surfaced_by_voice == "analyst"


# ---------------------------------------------------------------------------
# Task-level tests — drive _dissent_task / _steps_task via run_post_processors
# with monkeypatched _call_json.
# ---------------------------------------------------------------------------


def _drive_post_processors(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dissent_side_effect: Any = None,
    steps_side_effect: Any = None,
    landscape_side_effect: Any = None,
    tracker: DegradedSectionTracker | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Drive run_post_processors with controllable per-section side effects.

    Each *_side_effect can be:
      - None: a benign default payload is returned
      - a callable: invoked, return value used as the dict payload
      - an Exception: raised inside _call_json
    """
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

    async def _fake_run_section(
        client: Any, *, system: str, user: str, model_cls: Any, section: str
    ) -> Any:
        # Return None for per_voice so _coherence_drop_steps short-circuits
        # (per_voice is None → no drop). With an empty PerVoiceReadout the
        # coherence pass would prune every step that names any voice, which
        # would mask the section_flag we're asserting on in these tests.
        return None

    monkeypatch.setattr(pp, "_run_section", _fake_run_section)

    counters: dict[str, Any] = {"calls": 0}

    async def _fake_call_json(
        client: Any,
        *,
        system: str,
        user: str,
        model_cls: Any = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        counters["calls"] += 1
        # Route by system prompt sentinel (set in load_post_processors stub).
        if system == "SYS_LANDSCAPE":
            counters["landscape_max_tokens"] = max_tokens
            if isinstance(landscape_side_effect, BaseException):
                raise landscape_side_effect
            if callable(landscape_side_effect):
                return dict(landscape_side_effect())
            return {"competitors": [], "section_flag": None}
        if system == "SYS_DISSENT":
            counters["dissent_max_tokens"] = max_tokens
            if isinstance(dissent_side_effect, BaseException):
                raise dissent_side_effect
            if callable(dissent_side_effect):
                return dict(dissent_side_effect())
            return {"dissent_status": "no_surviving_dissent", "dissents": [], "rationale": ""}
        if system == "SYS_STEPS":
            counters["steps_max_tokens"] = max_tokens
            if isinstance(steps_side_effect, BaseException):
                raise steps_side_effect
            if callable(steps_side_effect):
                return dict(steps_side_effect())
            return {"steps": []}
        if system == "SYS_SUMMARY":
            return {"summary": "ok"}
        if system == "SYS_CLASSIFY":
            return {"idea_classification": "unclear", "founder_posture": "unclear"}
        return {}

    monkeypatch.setattr(pp, "_call_json", _fake_call_json)

    transcript = DebateTranscript(turns=[], total_tokens_in=0, total_tokens_out=0)

    async def _go() -> Any:
        return await pp.run_post_processors(transcript, "ctx", "idea", tracker=tracker)

    result = asyncio.run(_go())
    return result, counters


def test_dissent_task_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "dissent_status": "surviving",
        "dissents": [json.loads(_dissent_json("analyst"))],
        "rationale": "Analyst flagged the geo wedge.",
    }
    (_, _, _, dissent, _, _), _ = _drive_post_processors(
        monkeypatch, dissent_side_effect=lambda: payload
    )
    assert dissent is not None
    assert len(dissent.dissents) == 1
    assert dissent.section_flag is None


def test_dissent_task_truncated_partial_recovery(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    a = _dissent_json("analyst")
    b = _dissent_json("critic")
    partial = '{"dissents": [' + a + "," + b + ',{"voice": "archi'
    exc = LLMTruncationError(
        "LLM output truncated [finish_reason=length, completion_tokens=2000]",
        partial_content=partial,
    )
    with caplog.at_level(logging.WARNING):
        (_, _, _, dissent, _, _), _ = _drive_post_processors(monkeypatch, dissent_side_effect=exc)
    assert dissent is not None
    assert dissent.section_flag == "truncated_partial_recovery"
    assert len(dissent.dissents) == 2
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "pro.surviving_dissent.truncated" in msgs


def test_dissent_task_call_failed_returns_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        (_, _, _, dissent, _, _), _ = _drive_post_processors(
            monkeypatch, dissent_side_effect=RuntimeError("network down")
        )
    assert dissent is None
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "pro.surviving_dissent.call_failed" in msgs


def test_steps_task_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"steps": [json.loads(_step_json(1, "analyst"))]}
    (_, _, _, _, steps, _), _ = _drive_post_processors(
        monkeypatch, steps_side_effect=lambda: payload
    )
    assert steps is not None
    assert len(steps.steps) == 1


def test_steps_task_truncated_partial_recovery(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s1 = _step_json(1, "analyst")
    s2 = _step_json(2, "critic")
    partial = '{"steps": [' + s1 + "," + s2 + ',{"action": "Third'
    exc = LLMTruncationError(
        "LLM output truncated [finish_reason=length, completion_tokens=2000]",
        partial_content=partial,
    )
    with caplog.at_level(logging.WARNING):
        (_, _, _, _, steps, _), _ = _drive_post_processors(monkeypatch, steps_side_effect=exc)
    assert steps is not None
    assert steps.section_flag == "truncated_partial_recovery"
    assert len(steps.steps) == 2
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "pro.next_steps.truncated" in msgs


def test_steps_task_call_failed_returns_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        (_, _, _, _, steps, _), _ = _drive_post_processors(
            monkeypatch, steps_side_effect=RuntimeError("network down")
        )
    assert steps is None
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "pro.next_steps.call_failed" in msgs


# ---------------------------------------------------------------------------
# OBS-01 wiring: tracker.mark fires + apply_to populates ResearchResult.
# ---------------------------------------------------------------------------


def test_tracker_marks_on_truncation_and_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = _dissent_json("analyst")
    partial = '{"dissents": [' + a + ',{"voice": "crit'
    dissent_exc = LLMTruncationError("LLM output truncated", partial_content=partial)
    s1 = _step_json(1, "analyst")
    steps_partial = '{"steps": [' + s1 + ',{"action": "Cu'
    steps_exc = LLMTruncationError("LLM output truncated", partial_content=steps_partial)

    tracker = DegradedSectionTracker()
    _drive_post_processors(
        monkeypatch,
        dissent_side_effect=dissent_exc,
        steps_side_effect=steps_exc,
        tracker=tracker,
    )

    state = tracker.to_dict()
    assert "surviving_dissent" in state
    assert state["surviving_dissent"] == "truncated_partial_recovery"
    assert "next_steps_with_falsifiers" in state
    assert state["next_steps_with_falsifiers"] == "truncated_partial_recovery"

    # apply_to populates the ResearchResult fields.
    from gecko_core.models import (
        PRD,
        BusinessPlan,
        ResearchResult,
        ValidationReport,
    )

    rr = ResearchResult(
        session_id="00000000-0000-0000-0000-000000000000",
        tier="pro",
        business_plan=BusinessPlan(
            problem="p",
            icp="i",
            solution="s",
            market="m",
            business_model="b",
            channels="c",
            risks=[],
            citations=[],
        ),
        validation_report=ValidationReport(
            market_size_signal="s",
            competitor_analysis="c",
            demand_evidence="d",
            risk_flags=[],
            citations=[],
        ),
        prd=PRD(
            v1_scope=[],
            v2_scope=[],
            v3_scope=[],
            acceptance_criteria=[],
            non_functional=[],
            success_metrics=[],
            citations=[],
        ),
        sources=[],
    )
    tracker.apply_to(rr)
    assert "surviving_dissent" in rr.degraded_sections
    assert "next_steps_with_falsifiers" in rr.degraded_sections


# ---------------------------------------------------------------------------
# max_tokens defaults + env override.
# ---------------------------------------------------------------------------


def test_max_tokens_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env unset → both new caps default to 4000."""
    monkeypatch.delenv("GECKO_SURVIVING_DISSENT_MAX_TOKENS", raising=False)
    monkeypatch.delenv("GECKO_NEXT_STEPS_MAX_TOKENS", raising=False)
    from gecko_core.orchestration import settings as orch_settings

    orch_settings.get_orchestration_settings.cache_clear()
    try:
        _, counters = _drive_post_processors(monkeypatch)
        assert counters.get("dissent_max_tokens") == 4000
        assert counters.get("steps_max_tokens") == 4000
    finally:
        orch_settings.get_orchestration_settings.cache_clear()


def test_max_tokens_env_override_dissent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GECKO_SURVIVING_DISSENT_MAX_TOKENS", "8000")
    from gecko_core.orchestration import settings as orch_settings

    orch_settings.get_orchestration_settings.cache_clear()
    try:
        _, counters = _drive_post_processors(monkeypatch)
        assert counters.get("dissent_max_tokens") == 8000
    finally:
        orch_settings.get_orchestration_settings.cache_clear()


def test_max_tokens_env_override_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GECKO_NEXT_STEPS_MAX_TOKENS", "9000")
    from gecko_core.orchestration import settings as orch_settings

    orch_settings.get_orchestration_settings.cache_clear()
    try:
        _, counters = _drive_post_processors(monkeypatch)
        assert counters.get("steps_max_tokens") == 9000
    finally:
        orch_settings.get_orchestration_settings.cache_clear()
