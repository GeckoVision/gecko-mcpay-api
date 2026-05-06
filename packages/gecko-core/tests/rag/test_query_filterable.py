"""S20-RAG-02 — assertions on the $vectorSearch filter pushdown.

Tests the pure pipeline-builder so we don't need a fake Mongo collection.
"""

from __future__ import annotations

from gecko_core.db.mongo import VECTOR_INDEX_NAME
from gecko_core.db.mongo_reads import build_filterable_pipeline


def _vs(pipeline: list[dict]) -> dict:
    assert pipeline and "$vectorSearch" in pipeline[0]
    stage = pipeline[0]["$vectorSearch"]
    assert isinstance(stage, dict)
    return stage


def test_vertical_and_categories_are_pushed_into_vector_search() -> None:
    pipe = build_filterable_pipeline(
        query_embedding=[0.0] * 1024,
        vertical="neobank",
        categories=["business_financial"],
        match_count=5,
    )
    stage = _vs(pipe)
    assert stage["index"] == VECTOR_INDEX_NAME
    f = stage["filter"]
    assert f["vertical"] == {"$eq": "neobank"}
    assert f["category"] == {"$in": ["business_financial"]}
    # No standalone $match for these fields — they live INSIDE $vectorSearch.
    assert all("$match" not in stg for stg in pipe)


def test_no_vertical_means_cross_vertical() -> None:
    pipe = build_filterable_pipeline(
        query_embedding=[0.0] * 1024,
        vertical=None,
        categories=["product"],
    )
    stage = _vs(pipe)
    f = stage.get("filter", {})
    assert "vertical" not in f
    assert f["category"] == {"$in": ["product"]}


def test_include_legacy_false_excludes_deprecated() -> None:
    pipe = build_filterable_pipeline(
        query_embedding=[0.0] * 1024,
        vertical="dex",
        include_legacy=False,
    )
    stage = _vs(pipe)
    f = stage["filter"]
    assert f["metadata.deprecated"] == {"$ne": True}


def test_include_legacy_true_omits_deprecated_filter() -> None:
    pipe = build_filterable_pipeline(
        query_embedding=[0.0] * 1024,
        vertical="dex",
        include_legacy=True,
    )
    stage = _vs(pipe)
    f = stage.get("filter", {})
    assert "metadata.deprecated" not in f


def test_sources_filter_uses_in_clause() -> None:
    pipe = build_filterable_pipeline(
        query_embedding=[0.0] * 1024,
        vertical="neobank",
        sources=["bazaar", "twit_sh"],
    )
    stage = _vs(pipe)
    assert stage["filter"]["source"] == {"$in": ["bazaar", "twit_sh"]}


def test_no_filters_at_all_when_unscoped_and_legacy_included() -> None:
    pipe = build_filterable_pipeline(
        query_embedding=[0.0] * 1024,
        vertical=None,
        categories=None,
        sources=None,
        include_legacy=True,
    )
    stage = _vs(pipe)
    # No filter clause should be emitted at all.
    assert "filter" not in stage


def test_num_candidates_scales_with_match_count() -> None:
    pipe = build_filterable_pipeline(
        query_embedding=[0.0] * 1024,
        vertical="neobank",
        match_count=20,
    )
    stage = _vs(pipe)
    assert stage["numCandidates"] >= 200
    assert stage["limit"] == 20
    # ANN, not exhaustive scan.
    assert stage["exact"] is False
