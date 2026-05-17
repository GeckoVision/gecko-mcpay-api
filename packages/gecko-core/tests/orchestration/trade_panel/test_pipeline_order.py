"""S35-#83 — pipeline invariant tests for retrieve_trade_corpus_chunks.

Rewritten against the *current* S33-#79/#82 + S34-#85/#87 pipeline. The
superseded shape these tests used to pin — `_provider_quota_floor` running
before a single `cohere_rerank`, with `top_k==10` and a `top_k*2` candidate
floor — no longer exists. The current pipeline is:

    main $vectorSearch leg (protocol_native + cross-cutting)
      -> _apply_retrieval_boosts
    _retrieve_canon_floor: one $vectorSearch PER canon provider_kind,
      round-robin merged into a kind-balanced canon pool
    voyage_rerank_dicts on each leg INDEPENDENTLY
    post-rerank quota: canon_quota = min(_CANON_FLOOR_COUNT, top_k // 2)
      protocol_slots = top_k - canon_quota
    assemble protocol head + canon quota, back-fill from protocol tail
    truncate to top_k

Invariants pinned here (vs the old superseded ones):

1. `_DEFAULT_TRADE_TOP_K == 15` (S34-#87) — unchanged from the old file.
2. Canon-floor guarantee — canon chunks reach the output when the canon
   leg returns rows (the S33-#82 dedicated-leg fix). Old tests had no
   canon leg at all.
3. protocol_native majority at small top_k — the S34-#85 fix: canon is
   clamped to `<= top_k // 2`, so protocol_native always holds a
   `>= ceil(top_k/2)` majority. Old tests asserted only ">=2 distinct
   kinds" with no majority guarantee — they would have passed the
   2026-05-16 5/5-canon regression.
4. Graceful rerank degrade — when `voyage_rerank_dicts` no-ops (flag
   off / empty), the pipeline still returns a `top_k`-length slate with
   the canon quota honoured.
5. Final output length == top_k.

Light fakes only (repo memory `feedback_lighter_tests`): a per-pipeline
fake Mongo `aggregate` that distinguishes the main leg from the per-kind
canon legs by the `$vectorSearch.filter` shape, and a no-op embedder. The
Voyage reranker is left flag-off (`GECKO_RERANKER` unset) so it degrades
to the vector-order slate — that *is* the degrade path under test, and it
keeps the suite free + deterministic (no API key, no network).
"""

from __future__ import annotations

from typing import Any

import pytest
from gecko_core.orchestration import trade_panel as tp


def _chunk(score: float, provider_kind: str, idx: int) -> dict[str, Any]:
    """A raw Mongo-doc-shaped row. `idx` keeps `_id` unique across the pool."""
    is_canon = provider_kind.startswith("canon_")
    return {
        "_id": f"id_{provider_kind}_{idx}",
        "text": "x" * 400,
        "source_url": f"https://example/{provider_kind}/{idx}",
        "source": provider_kind,
        "provider_kind": provider_kind,
        "freshness_tier": "static",
        # Canon chunks carry protocol=[] (cross-cutting); protocol_native
        # chunks carry the exact protocol tag so they survive the $match.
        "protocol": [] if is_canon else ["kamino"],
        "vertical": "dex",
        "metadata": {},
        "score": score,
    }


def _canon_kind_of_pipeline(pipeline: list[dict[str, Any]]) -> str | None:
    """Return the canon provider_kind a per-kind canon leg filters on.

    The canon leg (`_retrieve_canon_floor`) issues one `$vectorSearch` per
    canon kind with `filter.provider_kind.$eq == <kind>`. The main leg uses
    a `$or` filter and has no `provider_kind.$eq`. This lets the fake route
    each `aggregate` call to the right row subset.
    """
    for stage in pipeline:
        vs = stage.get("$vectorSearch")
        if not vs:
            continue
        filt = vs.get("filter") or {}
        pk = filt.get("provider_kind")
        if isinstance(pk, dict) and "$eq" in pk:
            return str(pk["$eq"])
    return None


def _install_fake_mongo(monkeypatch: pytest.MonkeyPatch, pool: list[dict[str, Any]]) -> None:
    """Wire a per-pipeline fake chunk-store, embedder, and Mongo collection.

    The fake `aggregate` inspects the pipeline: a per-kind canon leg yields
    only that kind's rows; the main leg yields ONLY non-canon rows. That
    mirrors the real S33-#81 finding — canon loses the single-pool ANN race
    outright (0/75), which is precisely why the dedicated per-kind canon leg
    exists. If the main leg also returned canon, the id-dedup in
    `retrieve_trade_corpus_chunks` would strip the canon leg's rows.
    """
    import gecko_core.db as db_mod
    import gecko_core.db.mongo as mongo_mod
    import gecko_core.ingestion.embedder as embedder_mod

    class _FakeCollection:
        def aggregate(self, pipeline: list[dict[str, Any]]) -> Any:
            canon_kind = _canon_kind_of_pipeline(pipeline)

            async def _aiter() -> Any:
                for row in pool:
                    pk = str(row["provider_kind"])
                    if canon_kind is not None:
                        # Per-kind canon leg: only that kind's rows.
                        if pk != canon_kind:
                            continue
                    elif pk.startswith("canon_"):
                        # Main leg: canon loses the single-pool ANN race.
                        continue
                    yield dict(row)

            return _aiter()

    fake_coll = _FakeCollection()
    monkeypatch.setattr(db_mod, "get_chunk_store", lambda: "mongo")
    monkeypatch.setattr(mongo_mod, "chunks_collection", lambda: fake_coll)
    monkeypatch.setattr(mongo_mod, "VECTOR_INDEX_NAME", "test_index", raising=False)

    async def _fake_embed(
        texts: list[str], *, input_type: str | None = None
    ) -> tuple[list[list[float]], int]:
        return ([[0.0] * 1536 for _ in texts], 0)

    monkeypatch.setattr(embedder_mod, "embed", _fake_embed)


def _build_pool() -> list[dict[str, Any]]:
    """A wide pool: protocol_native majority + a balanced canon mix.

    protocol_native rows score above canon (a trade-idea query is closer to
    API text than to investor prose — the real S33-#81 finding) so the
    vector-order slate has protocol_native at the head.
    """
    pool: list[dict[str, Any]] = []
    idx = 0
    for _ in range(40):
        pool.append(_chunk(score=0.9 - idx * 0.0005, provider_kind="protocol_native", idx=idx))
        idx += 1
    for kind in ("canon_marks", "canon_damodaran", "canon_berkshire", "canon_macro"):
        for _ in range(4):
            pool.append(_chunk(score=0.55 - idx * 0.0005, provider_kind=kind, idx=idx))
            idx += 1
    return pool


def _canon_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for r in rows if str(r.get("provider_kind") or "").startswith("canon_"))


def test_default_top_k_constant_is_15() -> None:
    """S34-#87 raised the production default to 15 — the retrieval eval found
    provider_kind_coverage=0.567 at top_k=5 (fails the 0.8 gate) vs 0.967 at
    top_k=15. Pin it. See docs/eval/2026-05-17-s34-topk-cost-model.md."""
    assert tp._DEFAULT_TRADE_TOP_K == 15


def test_canon_floor_constant_is_6() -> None:
    """`_CANON_FLOOR_COUNT` sizes the canon retrieval leg + the post-rerank
    quota ceiling. 6 of top_k=15 is the 40%-canon split the floor was
    designed for (S34-#85 comment block)."""
    assert tp._CANON_FLOOR_COUNT == 6


@pytest.mark.asyncio
async def test_canon_floor_reaches_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """S33-#82 canon-floor guarantee: when the dedicated per-kind canon leg
    returns rows, canon chunks survive into the final top_k slate. The old
    single-pool pipeline returned 0/75 canon — this is the structural fix."""
    pool = _build_pool()
    _install_fake_mongo(monkeypatch, pool)

    out = await tp.retrieve_trade_corpus_chunks(
        idea="should I deposit into kamino jlp/usdc?",
        protocol="kamino",
        vertical="dex",
        top_k=15,
    )

    assert len(out) == 15
    # At top_k=15: canon_quota = min(6, 15//2) = 6.
    assert _canon_count(out) == 6, [r["provider_kind"] for r in out]
    # The canon mix is diverse — the per-kind leg + round-robin merge
    # guarantees the cross-encoder cannot collapse onto one canon kind.
    canon_kinds = {r["provider_kind"] for r in out if str(r["provider_kind"]).startswith("canon_")}
    assert len(canon_kinds) >= 2, canon_kinds


@pytest.mark.asyncio
async def test_protocol_native_majority_at_small_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S34-#85 fix: canon is clamped to `<= top_k // 2` so protocol_native
    always holds a `>= ceil(top_k/2)` majority. The 2026-05-16 regression
    was canon_quota=min(6, 5)=5 at top_k=5 — the canon FLOOR became a
    CEILING that consumed the whole slate and the panel saw 0 protocol
    chunks for a protocol-specific question."""
    pool = _build_pool()
    _install_fake_mongo(monkeypatch, pool)

    out = await tp.retrieve_trade_corpus_chunks(
        idea="kamino vault deposit?",
        protocol="kamino",
        vertical="dex",
        top_k=5,
    )

    assert len(out) == 5
    # canon_quota = min(_CANON_FLOOR_COUNT=6, 5 // 2) = 2.
    canon = _canon_count(out)
    assert canon <= 5 // 2, f"canon={canon} exceeds the top_k//2 clamp"
    protocol_native = sum(1 for r in out if r["provider_kind"] == "protocol_native")
    # protocol_native keeps the >= ceil(top_k/2) majority.
    assert protocol_native >= 3, [r["provider_kind"] for r in out]


@pytest.mark.asyncio
async def test_pipeline_survives_rerank_degrade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Graceful degrade: with `GECKO_RERANKER` unset, `voyage_rerank_dicts`
    no-ops to the vector-order slate. The pipeline must still return a
    `top_k`-length slate with the canon quota honoured — retrieval never
    breaks on a rerank failure."""
    monkeypatch.delenv("GECKO_RERANKER", raising=False)
    pool = _build_pool()
    _install_fake_mongo(monkeypatch, pool)

    out = await tp.retrieve_trade_corpus_chunks(
        idea="kamino deposit?",
        protocol="kamino",
        vertical="dex",
        top_k=15,
    )

    assert len(out) == 15
    # Canon quota still honoured on the degrade path.
    assert _canon_count(out) == 6
    # No rerank_score was attached (the reranker no-opped).
    assert all(r.get("rerank_score") is None for r in out)


@pytest.mark.asyncio
async def test_output_length_equals_top_k_when_canon_leg_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the canon leg returns nothing (no canon corpus ingested),
    `canon_quota` collapses to 0 and the protocol head back-fills the whole
    slate — output length is still exactly top_k."""
    # Pool with zero canon rows: every per-kind canon leg yields [].
    pool = [
        _chunk(score=0.9 - i * 0.0005, provider_kind="protocol_native", idx=i) for i in range(40)
    ]
    _install_fake_mongo(monkeypatch, pool)

    out = await tp.retrieve_trade_corpus_chunks(
        idea="kamino deposit?",
        protocol="kamino",
        vertical="dex",
        top_k=15,
    )

    assert len(out) == 15
    assert _canon_count(out) == 0
    assert all(r["provider_kind"] == "protocol_native" for r in out)


@pytest.mark.asyncio
async def test_empty_idea_and_nonpositive_top_k_short_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard rails: blank idea or top_k <= 0 return [] before any Mongo
    call. Pinned so a refactor cannot silently drop the early-out."""
    pool = _build_pool()
    _install_fake_mongo(monkeypatch, pool)

    assert await tp.retrieve_trade_corpus_chunks(idea="   ", protocol="kamino") == []
    assert await tp.retrieve_trade_corpus_chunks(idea="kamino?", protocol="kamino", top_k=0) == []
