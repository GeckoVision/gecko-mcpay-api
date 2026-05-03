"""Boundary coercion tests for LLM-emitted Pydantic shapes.

Two production bugs surfaced on 2026-05-03 dogfooding against
api.geckovision.tech, both rooted in gpt-4o-mini drifting away from the
prompted JSON shape:

    1. ``MarketLandscape.competitors[*].what_they_do`` was returned under
       ``description`` (and a couple of plausible aliases) instead of the
       prompted ``what_they_do`` key, blowing up
       ``MarketLandscape.model_validate`` with required-field errors.
    2. ``PRD.acceptance_criteria`` (and its sister ``list[str]`` fields)
       was sometimes returned as a single string, sometimes as a list of
       dicts (``[{"criterion": "..."}]``), instead of a flat list of
       strings.

Both fixes live as permissive validators in ``gecko_core.models`` —
matching the codebase's existing posture of absorbing mild output drift
at the boundary rather than failing the whole verdict and forcing a
retry. These tests assert the round-trips work against shapes captured
from the real failures.
"""

from __future__ import annotations

from gecko_core.models import PRD, Competitor, MarketLandscape

# ---------------------------------------------------------------------------
# Bug 1 — MarketLandscape.competitors[*].what_they_do alias coercion.
# ---------------------------------------------------------------------------


def test_competitor_accepts_description_alias() -> None:
    """LLM emitted `description` instead of `what_they_do` — coerce it."""
    raw = {
        "name": "OpenAI",
        "axis": "verdict_shape",
        "description": "Conversational AI with broad capabilities for startup idea validation.",
        "why_we_are_not_them": "We output a typed verdict; they output prose.",
    }
    comp = Competitor.model_validate(raw)
    assert comp.what_they_do.startswith("Conversational AI")
    assert comp.axis == "verdict_shape"


def test_competitor_accepts_summary_alias() -> None:
    raw = {
        "name": "Perplexity",
        "summary": "Search-grounded LLM with citations.",
        "axis": "provider_mix",
        "why_we_are_not_them": "Single-source grounding; we mix providers.",
    }
    comp = Competitor.model_validate(raw)
    assert comp.what_they_do == "Search-grounded LLM with citations."


def test_competitor_prefers_explicit_what_they_do_over_alias() -> None:
    """If both `what_they_do` and `description` are present, the prompted
    field wins — the alias is a fallback, not an override."""
    raw = {
        "name": "X",
        "what_they_do": "PROMPTED",
        "description": "ALIAS",
        "axis": "verdict_shape",
        "why_we_are_not_them": "We do not output prose.",
    }
    comp = Competitor.model_validate(raw)
    assert comp.what_they_do == "PROMPTED"


def test_market_landscape_round_trip_with_description_aliases() -> None:
    """Mirrors the actual 2026-05-03 dogfood error: the LLM dropped
    `what_they_do` for every competitor and emitted `description`
    instead. Pre-fix this raised ``5 validation errors``; post-fix the
    landscape parses cleanly."""
    raw = {
        "competitors": [
            {
                "name": "OpenAI",
                "axis": "verdict_shape",
                "description": "Conversational AI for startup idea validation.",
                "why_we_are_not_them": "We output a typed verdict; they output prose.",
            },
            {
                "name": "Perplexity",
                "axis": "provider_mix",
                "description": "Search-grounded LLM with citations.",
                "why_we_are_not_them": "Single-source grounding; we mix providers.",
            },
            {
                "name": "Anthropic Claude",
                "axis": "debate_vs_single_voice",
                "description": "Single-voice synthesis without adversarial debate.",
                "why_we_are_not_them": "We run a 5-voice adversarial debate.",
            },
        ]
    }
    landscape = MarketLandscape.model_validate(raw)
    assert len(landscape.competitors) == 3
    assert all(c.what_they_do for c in landscape.competitors)


# ---------------------------------------------------------------------------
# Bug 2 — PRD list-of-strings coercion.
# ---------------------------------------------------------------------------


_BASE_PRD: dict[str, object] = {
    "v1_scope": [],
    "v2_scope": [],
    "v3_scope": [],
    "acceptance_criteria": [],
    "non_functional": [],
    "success_metrics": [],
    "citations": [],
}


def _prd_with(field: str, value: object) -> dict[str, object]:
    return {**_BASE_PRD, field: value}


def test_prd_acceptance_criteria_string_coerced_to_list() -> None:
    """Pre-existing case: LLM returned a single string instead of a list."""
    prd = PRD.model_validate(_prd_with("acceptance_criteria", "Settles in < 5s end-to-end."))
    assert prd.acceptance_criteria == ["Settles in < 5s end-to-end."]


def test_prd_acceptance_criteria_empty_string_coerced_to_empty_list() -> None:
    prd = PRD.model_validate(_prd_with("acceptance_criteria", "   "))
    assert prd.acceptance_criteria == []


def test_prd_acceptance_criteria_dict_items_flattened_to_strings() -> None:
    """LLM returned list items as dicts (`[{"criterion": "..."}]`) — pull
    the first string-valued field out of each dict so the list-of-strings
    contract holds."""
    raw_value = [
        {"criterion": "Settles in < 5s end-to-end."},
        {"text": "P95 latency < 200ms."},
        {"value": "99.5% monthly uptime."},
    ]
    prd = PRD.model_validate(_prd_with("acceptance_criteria", raw_value))
    assert prd.acceptance_criteria == [
        "Settles in < 5s end-to-end.",
        "P95 latency < 200ms.",
        "99.5% monthly uptime.",
    ]


def test_prd_acceptance_criteria_mixed_string_and_dict_items() -> None:
    raw_value = [
        "Plain string criterion.",
        {"criterion": "Dict-shaped criterion."},
    ]
    prd = PRD.model_validate(_prd_with("acceptance_criteria", raw_value))
    assert prd.acceptance_criteria == [
        "Plain string criterion.",
        "Dict-shaped criterion.",
    ]


def test_prd_acceptance_criteria_empty_string_items_dropped() -> None:
    raw_value = ["Real criterion.", "", "   "]
    prd = PRD.model_validate(_prd_with("acceptance_criteria", raw_value))
    assert prd.acceptance_criteria == ["Real criterion."]


def test_prd_v1_scope_same_coercion_applies() -> None:
    """The validator covers all six list[str] fields, not just
    acceptance_criteria."""
    prd = PRD.model_validate(_prd_with("v1_scope", "Single-feature scope line."))
    assert prd.v1_scope == ["Single-feature scope line."]
