"""S35-#91 — unit tests for the emitted-citation selector.

Pure-function tests over `select_emitted_citations` / `_parse_used_markers`.
No Mongo, no LLM, no autogen. Per CLAUDE.md feedback_lighter_tests: the
selector is pure data-in / data-out, so we exercise it directly with light
fakes — a list of turn-shaped objects and a list of chunk dicts.

Why these matter: the S35-WS1 diagnosis
(docs/eval/2026-05-17-s35-citation-relevance-diagnosis.md) found the verdict
envelope emitted ALL 15 retrieved chunks as citations — 9 protocol_native +
6 cross-cutting canon — flooring `citation_relevance` at ~0.47. The selector
trims the EMITTED list to chunks a turn actually referenced, while a coverage
floor protects the statistically locked `provider_kind_coverage` dimension.
These tests pin: used-only selection, the coverage floor, the no-marker
rank-trim fallback, and marker-validity bounds.
"""

from __future__ import annotations

from gecko_core.orchestration.trade_panel import (
    _CITATION_TRIM_TARGET,
    _parse_used_markers,
    select_emitted_citations,
)
from gecko_core.orchestration.trade_panel.models import TradePanelTurn


def _turn(content: str, agent: str = "fundamental_analyst") -> TradePanelTurn:
    return TradePanelTurn(agent=agent, content=content, parsed_verdict=None)


def _chunk(idx: int, *, kind: str, score: float) -> dict:
    """A retrieval-shaped chunk dict. `idx` only labels it for readability."""
    return {
        "id": f"chunk-{idx}",
        "provider_kind": kind,
        "score": score,
        "text": f"chunk {idx} body text " + "x" * 50,
        "source": kind,
    }


# 9 protocol_native + 6 canon — the invariant retrieval composition the
# diagnosis observed across all 30 N=30 rows.
def _retrieval_set() -> list[dict]:
    chunks: list[dict] = []
    for i in range(1, 10):  # 1..9 protocol_native
        chunks.append(_chunk(i, kind="protocol_native", score=0.9 - i * 0.01))
    for i, k in enumerate(
        [
            "canon_berkshire",
            "canon_marks",
            "canon_macro",
            "canon_damodaran",
            "canon_mauboussin",
            "canon_berkshire",
        ],
        start=10,
    ):
        chunks.append(_chunk(i, kind=k, score=0.5 - i * 0.01))
    return chunks


# --- _parse_used_markers ---------------------------------------------------


def test_parse_markers_collects_valid_indices() -> None:
    turns = [_turn("strong signal in [1] and [3]"), _turn("risk noted in [9]")]
    assert _parse_used_markers(turns, n_chunks=15) == {1, 3, 9}


def test_parse_markers_drops_out_of_range() -> None:
    # [99] exceeds n_chunks; [0] is below 1-indexed floor — both dropped.
    turns = [_turn("see [2], [99], [0] and a date [2024]")]
    # [2024] -> _CITATION_MARKER_RE caps at 2 digits, never matches a 4-digit run.
    assert _parse_used_markers(turns, n_chunks=15) == {2}


def test_parse_markers_empty_when_no_markers() -> None:
    assert _parse_used_markers([_turn("no citations here at all")], n_chunks=15) == set()


# --- select_emitted_citations: used-only ----------------------------------


def test_used_only_selects_referenced_subset() -> None:
    chunks = _retrieval_set()
    # Turns reference protocol_native [1],[2],[3] AND canon [10] (a Berkshire
    # chunk a turn actually drew on) AND canon [11] (canon_marks).
    turns = [
        _turn("entry thesis grounded in [1] and [2]"),
        _turn("counterpoint from [3]"),
        _turn("framing per [10] and [11]"),
    ]
    emitted = select_emitted_citations(turns, chunks)
    ids = {c["id"] for c in emitted}
    # used subset = {1,2,3,10,11}. Coverage floor adds one chunk for each
    # canon kind NOT yet covered: canon_macro, canon_damodaran, canon_mauboussin.
    # canon_berkshire(10) + canon_marks(11) already covered.
    assert {"chunk-1", "chunk-2", "chunk-3", "chunk-10", "chunk-11"} <= ids
    kinds = {c["provider_kind"] for c in emitted}
    assert kinds == {
        "protocol_native",
        "canon_berkshire",
        "canon_marks",
        "canon_macro",
        "canon_damodaran",
        "canon_mauboussin",
    }
    # Trimmed, not the whole 15.
    assert len(emitted) < len(chunks)


def test_used_only_preserves_retrieval_order() -> None:
    chunks = _retrieval_set()
    turns = [_turn("out of order refs [5] then [2] then [9]")]
    emitted = select_emitted_citations(turns, chunks)
    pn_ids = [c["id"] for c in emitted if c["provider_kind"] == "protocol_native"]
    # Emitted list preserves retrieval (index) order regardless of marker order.
    assert pn_ids == sorted(pn_ids, key=lambda s: int(s.split("-")[1]))


# --- select_emitted_citations: coverage floor -----------------------------


def test_coverage_floor_readds_dropped_provider_kind() -> None:
    chunks = _retrieval_set()
    # Turns ONLY cite protocol_native — used-only would drop ALL 6 canon kinds.
    turns = [_turn("everything in [1] [2] [4]")]
    emitted = select_emitted_citations(turns, chunks)
    kinds = {c["provider_kind"] for c in emitted}
    # Every provider_kind present in retrieval must still be in the envelope.
    assert kinds == {c["provider_kind"] for c in chunks}


def test_coverage_floor_picks_highest_score_chunk_for_missing_kind() -> None:
    chunks = _retrieval_set()
    turns = [_turn("only [1]")]
    emitted = select_emitted_citations(turns, chunks)
    # canon_berkshire has two chunks: chunk-10 (score 0.40) and chunk-15
    # (score 0.35). The floor must re-add the higher-scored one (chunk-10).
    berkshire = [c["id"] for c in emitted if c["provider_kind"] == "canon_berkshire"]
    assert berkshire == ["chunk-10"]


# --- select_emitted_citations: fallback -----------------------------------


def test_no_markers_falls_back_to_rank_trim_with_coverage_floor() -> None:
    chunks = _retrieval_set()
    turns = [_turn("the panel cited nothing by index this run")]
    emitted = select_emitted_citations(turns, chunks)
    # Fallback seeds the top _CITATION_TRIM_TARGET by score (the 7 highest are
    # all protocol_native: 0.81..0.89), THEN the coverage floor re-adds one
    # chunk per missing canon kind (5 distinct canon kinds) — so the emitted
    # count is the seed plus the floor additions, NOT the whole 15.
    assert _CITATION_TRIM_TARGET < len(emitted) < len(chunks)
    # The locked dimension still holds: every retrieval provider_kind present.
    assert {c["provider_kind"] for c in emitted} == {c["provider_kind"] for c in chunks}


def test_empty_chunks_returns_empty() -> None:
    assert select_emitted_citations([_turn("[1]")], []) == []
