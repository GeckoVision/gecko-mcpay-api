"""v5.5 demo output — structural smoke. No model calls."""

from __future__ import annotations

import io
import json
import re
from datetime import date
from pathlib import Path
from typing import get_args

from gecko_cli.render import render_research_demo
from gecko_core.models import ResearchResult
from rich.console import Console

_FIXTURE = Path(__file__).parent / "fixtures" / "demo_research_result.json"


def _load_fixture() -> ResearchResult:
    return ResearchResult.model_validate(json.loads(_FIXTURE.read_text(encoding="utf-8")))


def _render(result: ResearchResult) -> str:
    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=False, color_system=None, record=False)
    render_research_demo(result, "Stablecoin payouts API for LATAM gig platforms.", console)
    return buf.getvalue()


def test_demo_render_smoke_full_fixture() -> None:
    result = _load_fixture()
    output = _render(result)
    assert "verdict@" in output
    assert "▸ Voices" in output
    assert "▸ Surviving Dissent" in output
    assert "Falsifier:" in output
    assert "▸ Landscape" in output
    assert "▸ Next Steps" in output


def test_demo_render_skips_missing_optional_sections() -> None:
    result = _load_fixture().model_copy(
        update={
            "per_voice": None,
            "transcript_summary": None,
            "market_landscape": None,
            "next_steps_with_falsifiers": None,
        }
    )
    output = _render(result)
    # Header + dissent + footer always render.
    assert "verdict@" in output
    assert "▸ Surviving Dissent" in output
    # The optional sections drop out cleanly.
    assert "▸ Voices" not in output
    assert "▸ Landscape" not in output
    assert "▸ Next Steps" not in output


def test_demo_render_self_incriminates_when_dissent_missing() -> None:
    result = _load_fixture().model_copy(update={"surviving_dissent": None})
    output = _render(result)
    assert "▸ Surviving Dissent" in output
    assert "No dissent survived" in output


def test_dissent_section_renders_self_incrimination_when_empty() -> None:
    """Empty dissent (status = no_surviving_dissent, dissents = []) must
    still render the section header AND the self-incrimination text per
    design spec §2.5."""
    from gecko_core.models import SurvivingDissent

    empty_dissent = SurvivingDissent(
        dissent_status="no_surviving_dissent",
        dissents=[],
        rationale="All voices converged.",
    )
    result = _load_fixture().model_copy(update={"surviving_dissent": empty_dissent})
    output = _render(result)
    assert "▸ Surviving Dissent" in output
    # Copy lifted from `_NO_DISSENT_TEXT` in render.py.
    assert "consensus was real" in output
    assert "orchestration is collapsing voices" in output


def test_falsifier_iso_dates_are_not_in_the_past() -> None:
    """Structural eval: any ISO `by_when` value on the fixture's falsifiers
    must parse to a date strictly greater than today. Catches the v5.5
    bug where the model invented past dates (`2024-01-15`) when not given
    today's date in context.
    """
    result = _load_fixture()
    assert result.next_steps_with_falsifiers is not None
    today = date.today()
    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for step in result.next_steps_with_falsifiers.steps:
        by_when = step.falsifier.by_when.strip()
        if iso_re.match(by_when):
            parsed = date.fromisoformat(by_when)
            assert parsed > today, (
                f"falsifier by_when {by_when!r} is not strictly > today ({today.isoformat()})"
            )


def test_landscape_why_we_are_not_them_is_a_sentence_not_an_axis_key() -> None:
    """Structural eval: the v5.5 bug was the model writing the bare axis
    enum key (e.g. `provider_mix`) into `why_we_are_not_them`. The fix
    splits axis (key) from why_we_are_not_them (sentence). This test
    asserts the fixture's sentences are not equal to any axis enum key.
    """
    from gecko_core.models import CompetitorAxis

    result = _load_fixture()
    assert result.market_landscape is not None
    axis_keys = set(get_args(CompetitorAxis))
    for comp in result.market_landscape.competitors:
        if comp.flag is not None:
            continue
        assert comp.axis in axis_keys, f"competitor {comp.name!r} has invalid axis {comp.axis!r}"
        assert comp.why_we_are_not_them is not None
        sentence = comp.why_we_are_not_them.strip()
        assert sentence not in axis_keys, (
            f"competitor {comp.name!r} `why_we_are_not_them` is the bare axis key "
            f"{sentence!r} — should be a sentence."
        )
        # Sentence floor: real sentences have whitespace.
        assert " " in sentence, (
            f"competitor {comp.name!r} `why_we_are_not_them` has no whitespace; "
            f"likely an enum key, not a sentence: {sentence!r}"
        )
