"""FIX-03 — partial-tolerant ``next_steps_with_falsifiers`` validation tests.

The strict ``NextStepsWithFalsifiers.model_validate(raw)`` path drops the
entire payload when one step is malformed; we want surviving steps to
propagate so a single bad falsifier doesn't blank the whole section.

Observed regression: dogfood ``3d26b165-90ba-4e17-8e50-db483abf6932``
returned ``null`` for the entire field; the prior run on ``6afd55d7``
returned 3 falsifiers.
"""

from __future__ import annotations

import logging

import pytest
from gecko_core.orchestration.pro.post_processors import _validate_next_steps_partial


def test_three_valid_falsifiers_propagate(caplog: pytest.LogCaptureFixture) -> None:
    """Synth output with 3 well-formed steps → all 3 propagate; no WARN."""
    raw = {
        "steps": [
            {
                "action": "Email 5 EPCS-active vet practices to validate the wedge.",
                "surfaced_by_voice": "critic",
                "falsifier": {
                    "what_would_disprove_this": "Fewer than 3 vet practices respond.",
                    "by_when": "within 14 days of V1 ship",
                },
            },
            {
                "action": "Ship the V1 booking flow.",
                "surfaced_by_voice": "scoper",
                "falsifier": {
                    "what_would_disprove_this": "Less than 5% conversion at booking step.",
                    "by_when": "within 30 days of launch",
                },
            },
            {
                "action": "Negotiate a Helium pilot.",
                "surfaced_by_voice": "analyst",
                "falsifier": {
                    "what_would_disprove_this": "Pilot blocks at legal review.",
                    "by_when": "within 21 days of intro call",
                },
            },
        ]
    }
    with caplog.at_level(logging.WARNING):
        result = _validate_next_steps_partial(raw)
    assert result is not None
    assert len(result.steps) == 3
    assert not [r for r in caplog.records if r.getMessage() == "pro.falsifiers.dropped"]


def test_missing_steps_field_returns_none_with_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Synth output missing the ``steps`` key → return None, WARN logged."""
    with caplog.at_level(logging.WARNING):
        result = _validate_next_steps_partial({})
    assert result is None
    matches = [r for r in caplog.records if r.getMessage() == "pro.falsifiers.dropped"]
    assert len(matches) == 1
    assert getattr(matches[0], "reason", None) == "missing_or_invalid_steps_field"


def test_partial_malformed_steps_propagate_valid_ones(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Three steps where one has bad ``surfaced_by_voice`` → 2 propagate; WARN logs dropped=1."""
    raw = {
        "steps": [
            {
                "action": "Email 5 EPCS-active vet practices.",
                "surfaced_by_voice": "critic",
                "falsifier": {
                    "what_would_disprove_this": "Fewer than 3 respond.",
                    "by_when": "within 14 days of V1 ship",
                },
            },
            {
                # Malformed: surfaced_by_voice is not in the canonical voice enum.
                "action": "Run a customer-discovery panel.",
                "surfaced_by_voice": "the_panel",
                "falsifier": {
                    "what_would_disprove_this": "Less than 5 sign up.",
                    "by_when": "within 21 days",
                },
            },
            {
                "action": "Negotiate a Helium pilot.",
                "surfaced_by_voice": "analyst",
                "falsifier": {
                    "what_would_disprove_this": "Pilot blocks at legal review.",
                    "by_when": "within 21 days of intro call",
                },
            },
        ]
    }
    with caplog.at_level(logging.WARNING):
        result = _validate_next_steps_partial(raw)
    assert result is not None
    assert len(result.steps) == 2
    assert {s.surfaced_by_voice for s in result.steps} == {"critic", "analyst"}
    matches = [r for r in caplog.records if r.getMessage() == "pro.falsifiers.dropped"]
    assert len(matches) == 1
    assert getattr(matches[0], "dropped", None) == 1
    assert getattr(matches[0], "kept", None) == 2


def test_empty_steps_list_propagates_as_empty_no_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """KILL-verdict path: 0 steps is legitimate; empty list propagates without WARN."""
    with caplog.at_level(logging.WARNING):
        result = _validate_next_steps_partial({"steps": []})
    assert result is not None
    assert result.steps == []
    assert not [r for r in caplog.records if r.getMessage() == "pro.falsifiers.dropped"]


def test_all_steps_malformed_returns_none_with_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every step fails validation → return None so renderer skips section."""
    raw = {
        "steps": [
            {"action": "do thing", "surfaced_by_voice": "the_panel", "falsifier": {}},
        ]
    }
    with caplog.at_level(logging.WARNING):
        result = _validate_next_steps_partial(raw)
    assert result is None
    matches = [r for r in caplog.records if r.getMessage() == "pro.falsifiers.dropped"]
    assert len(matches) == 1
    assert getattr(matches[0], "dropped", None) == 1
