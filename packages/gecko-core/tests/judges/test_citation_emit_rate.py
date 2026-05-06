"""S21-FIX-07 — citation cardinality + emit-rate telemetry.

Production session ``cae5ab28``: model emitted 11 citation entries against
3 prose markers — 8 unmatched were silently dropped. The fix has two
parts:

1. Prompt tightening (basic._SYSTEM_PROMPT) — explicit cardinality rule
   forbidding emit-without-marker.
2. INFO emit_rate telemetry in synth_citations.py — captures the over-
   emission rate for the next dogfood pass.
"""

from __future__ import annotations

import logging

import pytest
from gecko_core.judges.synth_citations import extract_citation_markers


def _raw(idx: int, doc_id: str, url: str) -> dict[str, object]:
    return {"idx": idx, "doc_id": doc_id, "url": url, "span": None}


def test_prompt_contains_cardinality_rule() -> None:
    """Schema-drift guard — the cardinality + inverse-map instruction must
    survive any future prompt edit. If this fails the model has lost the
    over-emission guardrail."""
    from gecko_core.orchestration.basic import _SYSTEM_PROMPT

    assert "cardinality" in _SYSTEM_PROMPT
    assert "inverse map" in _SYSTEM_PROMPT


def test_emit_rate_logged_on_happy_path(caplog: pytest.LogCaptureFixture) -> None:
    """3 prose markers, 3 matched citations → emit_rate INFO with zero drop."""
    allowed = {"chunk-a", "chunk-b", "chunk-c"}
    raw = [
        _raw(1, "chunk-a", "https://example.com/a"),
        _raw(2, "chunk-b", "https://example.com/b"),
        _raw(3, "chunk-c", "https://example.com/c"),
    ]
    prose = ["one [1] two [2] three [3]"]

    with caplog.at_level(logging.INFO, logger="gecko_core.judges.synth_citations"):
        extract_citation_markers(raw_citations=raw, allowed_doc_ids=allowed, prose_surfaces=prose)

    msgs = [r.getMessage() for r in caplog.records]
    emit_rate = [m for m in msgs if m.startswith("synth.citation.emit_rate")]
    assert len(emit_rate) == 1
    assert "emitted=3" in emit_rate[0]
    assert "prose_markers=3" in emit_rate[0]
    assert "dropped_unmatched=0" in emit_rate[0]
    assert "matched=3" in emit_rate[0]


def test_emit_rate_logged_on_cae5ab28_reproducer(caplog: pytest.LogCaptureFixture) -> None:
    """11 citation entries vs 3 prose markers → emit_rate logs the drop count.

    Reproduces the production over-emission scenario. ``emitted`` is the
    grounded count (post hallucination filter), so when all 11 doc_ids
    are valid the emit_rate logs emitted=11. Of those, 3 match prose
    markers and 8 are dropped — exactly the cae5ab28 signal.
    """
    allowed = {f"chunk-{i}" for i in range(1, 12)}
    raw = [_raw(i, f"chunk-{i}", f"https://example.com/{i}") for i in range(1, 12)]
    prose = ["claim a [1] claim b [2] claim c [3]"]

    with caplog.at_level(logging.INFO, logger="gecko_core.judges.synth_citations"):
        markers, cited = extract_citation_markers(
            raw_citations=raw, allowed_doc_ids=allowed, prose_surfaces=prose
        )

    # Verify the structural outcome first — only the 3 matched survive.
    assert len(markers) == 3
    assert sorted(cited) == ["chunk-1", "chunk-2", "chunk-3"]

    msgs = [r.getMessage() for r in caplog.records]
    emit_rate = [m for m in msgs if m.startswith("synth.citation.emit_rate")]
    assert len(emit_rate) == 1
    line = emit_rate[0]
    assert "emitted=11" in line
    assert "prose_markers=3" in line
    assert "dropped_unmatched=8" in line
    assert "matched=3" in line
