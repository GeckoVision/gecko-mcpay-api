"""S20-C-CONFIDENCE-PROMPT-01 — confidence self-rating parser + aggregator."""

from __future__ import annotations

import logging

import pytest
from gecko_core.judges.confidence_prompt import (
    CONFIDENCE_PROMPT_INSTRUCTION,
    ConfidenceRating,
    aggregate_confidence,
    parse_confidence,
)
from pydantic import ValidationError


def test_parse_confidence_valid() -> None:
    rating = parse_confidence({"confidence": 0.9, "rationale": "dense base"})
    assert isinstance(rating, ConfidenceRating)
    assert rating.confidence == 0.9
    assert rating.rationale == "dense base"
    # Per-dimension scores are optional and default None.
    assert rating.evidence_floor is None
    assert rating.dissent_quality is None
    assert rating.citation_density is None


def test_parse_confidence_with_per_dimension_scores() -> None:
    rating = parse_confidence(
        {
            "confidence": 0.6,
            "rationale": "dissent partially addressed",
            "evidence_floor": 0.9,
            "dissent_quality": 0.6,
            "citation_density": 0.9,
        }
    )
    assert rating.confidence == 0.6
    assert rating.evidence_floor == 0.9
    assert rating.dissent_quality == 0.6
    assert rating.citation_density == 0.9


def test_parse_confidence_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        parse_confidence({"confidence": 1.5, "rationale": "x"})


def test_parse_confidence_negative_raises() -> None:
    with pytest.raises(ValidationError):
        parse_confidence({"confidence": -0.1, "rationale": "x"})


def test_parse_confidence_truncates_long_rationale() -> None:
    """Verbose rationale is truncated, not rejected — permissive boundary."""
    long_rationale = "word " * 80  # ~400 chars
    rating = parse_confidence({"confidence": 0.7, "rationale": long_rationale})
    assert rating.confidence == 0.7
    assert len(rating.rationale) <= 200
    assert rating.rationale.endswith("...")


def test_aggregate_confidence_min() -> None:
    assert aggregate_confidence([0.9, 0.6, 0.3]) == 0.3
    assert aggregate_confidence([0.9]) == 0.9
    assert aggregate_confidence([0.5, 0.5]) == 0.5


def test_aggregate_confidence_empty_returns_zero(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = aggregate_confidence([])
    assert result == 0.0
    assert any("synth.confidence.aggregate.empty" in r.message for r in caplog.records)


def test_prompt_instruction_mentions_three_dimensions() -> None:
    """Schema-drift smoke: prompt fragment must cover all three dimensions
    and the calibration anchor values 0.9 and 0.3."""
    text = CONFIDENCE_PROMPT_INSTRUCTION
    assert "EVIDENCE_FLOOR" in text
    assert "DISSENT_QUALITY" in text
    assert "CITATION_DENSITY" in text
    assert "0.9" in text
    assert "0.3" in text
    # The 20-word rationale cap is part of the calibration contract.
    assert "20 words" in text
