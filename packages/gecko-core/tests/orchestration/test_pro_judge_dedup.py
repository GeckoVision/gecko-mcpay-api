"""FIX-02 — judge-output dedup tests.

The judge LLM occasionally double-emits its scoring block in a single turn
(observed in dogfood ``3d26b165-90ba-4e17-8e50-db483abf6932``). The
``dedup_judge_summary`` helper keeps the LAST block and emits a structured
WARN ``pro.judge.dedup_count`` with the count.
"""

from __future__ import annotations

import logging

import pytest
from gecko_core.orchestration.pro.judge_dedup import dedup_judge_summary


def test_single_judge_output_passes_through(caplog: pytest.LogCaptureFixture) -> None:
    """One scoring block → identity, no WARN log."""
    summary = (
        "TAM: 4 | WEDGE: 5 | V1_FEASIBILITY: 8 | gap_classification: Partial:segment\n"
        "Final verdict: REFINE — narrow to vet practices."
    )
    with caplog.at_level(logging.WARNING):
        out = dedup_judge_summary(summary)
    assert out == summary
    assert not [r for r in caplog.records if "pro.judge.dedup_count" in r.getMessage()]


def test_two_judge_outputs_keeps_last_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    """Dogfood scenario: two ``---``-separated blocks → keep last, WARN with count=2."""
    first = (
        "TAM: 4 | WEDGE: 3 | V1_FEASIBILITY: 7 | gap_classification: Partial:segment\n"
        "Final verdict: REFINE"
    )
    last = (
        "TAM: 4 | WEDGE: 5 | V1_FEASIBILITY: 8 | gap_classification: Partial:segment\n"
        "Final verdict: REFINE — sharper recommendation."
    )
    summary = f"{first}\n\n---\n\n{last}"
    with caplog.at_level(logging.WARNING):
        out = dedup_judge_summary(summary)
    assert out == last
    matches = [r for r in caplog.records if r.getMessage() == "pro.judge.dedup_count"]
    assert len(matches) == 1
    assert getattr(matches[0], "count", None) == 2


def test_two_judge_outputs_via_repeated_final_verdict_marker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No ``---`` separator but two ``Final verdict:`` markers → still dedup."""
    summary = (
        "TAM: 5 | WEDGE: 4 | V1_FEASIBILITY: 6\n"
        "Final verdict: REFINE\n"
        "Wait, reconsidering.\n"
        "TAM: 5 | WEDGE: 6 | V1_FEASIBILITY: 7\n"
        "Final verdict: GO"
    )
    with caplog.at_level(logging.WARNING):
        out = dedup_judge_summary(summary)
    assert out is not None
    assert "Final verdict: GO" in out
    assert "Final verdict: REFINE" not in out
    matches = [r for r in caplog.records if r.getMessage() == "pro.judge.dedup_count"]
    assert len(matches) == 1


def test_empty_judge_output(caplog: pytest.LogCaptureFixture) -> None:
    """Empty content → identity, no crash, no WARN."""
    with caplog.at_level(logging.WARNING):
        assert dedup_judge_summary("") == ""
        assert dedup_judge_summary(None) is None
    assert not [r for r in caplog.records if "pro.judge.dedup_count" in r.getMessage()]
