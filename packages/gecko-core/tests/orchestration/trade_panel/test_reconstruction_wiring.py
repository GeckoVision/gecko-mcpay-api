"""S39-#134 — `run_trade_panel_with_retrieval` reconstruction-merge wiring.

Phase 2 design: when both ``pool`` AND ``as_of`` are set, the wrapper calls
``reconstruct_pool_chunks`` and appends the result to the gated retrieval
slate before the panel call. Either parameter missing => no reconstruction
(production no-op). The reconstruction module itself is exercised by its
own test file; here we only assert the wiring contract.

Light fakes per ``feedback_lighter_tests`` — no AG2, no Mongo, no HTTP.
"""

from __future__ import annotations

from typing import Any

import pytest
from gecko_core.orchestration.trade_panel import (
    TradePanelVerdict,
    run_trade_panel_with_retrieval,
)

_CANON_CHUNKS: list[dict[str, Any]] = [
    {"id": f"canon-{i}", "text": f"canon snippet {i}", "provider_kind": "canon_marks"}
    for i in range(3)
]
_RECON_CHUNKS: list[dict[str, Any]] = [
    {
        "id": f"recon-{i}",
        "text": f"recon snippet {i}",
        "provider_kind": "market_data",
        "freshness_tier": "hot",
        "as_of_date": "2026-01-15",
    }
    for i in range(2)
]


def _stub_verdict() -> TradePanelVerdict:
    return TradePanelVerdict(verdict="defer", confidence=0.5, turns=[])


@pytest.fixture
def panel_seam(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub out retrieval + panel + reconstruction.

    Returns a dict ``seam`` populated as the wrapper runs:
      * ``seam["recon_calls"]`` — list of (pool, as_of, protocol) tuples
      * ``seam["panel_chunks"]`` — the ``retrieved_chunks`` ``run_trade_panel`` saw
    """
    seam: dict[str, Any] = {"recon_calls": [], "panel_chunks": None}

    async def fake_retrieve(**_kwargs: Any) -> list[dict[str, Any]]:
        return list(_CANON_CHUNKS)

    async def fake_reconstruct(pool: str, *, as_of: str, protocol: str) -> list[dict[str, Any]]:
        seam["recon_calls"].append((pool, as_of, protocol))
        return list(_RECON_CHUNKS)

    async def fake_run_panel(
        *, idea: str, protocol: str, retrieved_chunks: list[dict[str, Any]], **_kw: Any
    ) -> TradePanelVerdict:
        seam["panel_chunks"] = retrieved_chunks
        return _stub_verdict()

    monkeypatch.setattr(
        "gecko_core.orchestration.trade_panel.retrieve_trade_corpus_chunks",
        fake_retrieve,
    )
    monkeypatch.setattr("gecko_core.orchestration.trade_panel.run_trade_panel", fake_run_panel)
    # reconstruct_pool_chunks is lazy-imported inside the wrapper — patch on
    # the source module so the import sees the fake.
    monkeypatch.setattr(
        "gecko_core.orchestration.trade_panel.backtest.reconstruction.reconstruct_pool_chunks",
        fake_reconstruct,
    )
    return seam


@pytest.mark.asyncio
async def test_production_no_op_no_pool_no_as_of(panel_seam: dict[str, Any]) -> None:
    """Default call — neither ``pool`` nor ``as_of`` set => no reconstruction.

    This is the production-byte-identical guarantee. Any reconstruction call
    here is a leak surface: it means the production path is *capable* of
    reconstructing without the explicit backtest opt-in.
    """
    await run_trade_panel_with_retrieval(idea="x", protocol="kamino")
    assert panel_seam["recon_calls"] == []
    assert panel_seam["panel_chunks"] == _CANON_CHUNKS


@pytest.mark.asyncio
async def test_pool_alone_skips_reconstruction(panel_seam: dict[str, Any]) -> None:
    """``pool`` without ``as_of`` => no reconstruction (no point-in-time)."""
    await run_trade_panel_with_retrieval(idea="x", protocol="kamino", pool="pool-abc")
    assert panel_seam["recon_calls"] == []
    assert panel_seam["panel_chunks"] == _CANON_CHUNKS


@pytest.mark.asyncio
async def test_as_of_alone_skips_reconstruction(panel_seam: dict[str, Any]) -> None:
    """``as_of`` without ``pool`` => no reconstruction (no target pool)."""
    await run_trade_panel_with_retrieval(idea="x", protocol="kamino", as_of="2026-01-15")
    assert panel_seam["recon_calls"] == []
    assert panel_seam["panel_chunks"] == _CANON_CHUNKS


@pytest.mark.asyncio
async def test_both_set_merges_reconstructed_chunks(
    panel_seam: dict[str, Any],
) -> None:
    """Both ``pool`` AND ``as_of`` set => reconstruction called, chunks merged.

    Asserts:
      * reconstruction was called exactly once with the normalized as_of string,
      * the panel saw canon + reconstructed (append order; canon first),
      * the reconstructed chunks carry their original tags through the merge.
    """
    await run_trade_panel_with_retrieval(
        idea="should I deposit", protocol="kamino", as_of="2026-01-15", pool="pool-abc"
    )
    assert panel_seam["recon_calls"] == [("pool-abc", "2026-01-15", "kamino")]
    seen = panel_seam["panel_chunks"]
    assert seen[: len(_CANON_CHUNKS)] == _CANON_CHUNKS, "canon must precede recon"
    assert seen[len(_CANON_CHUNKS) :] == _RECON_CHUNKS
    assert len(seen) == len(_CANON_CHUNKS) + len(_RECON_CHUNKS)


@pytest.mark.asyncio
async def test_reconstruction_failure_falls_back_to_canon(
    monkeypatch: pytest.MonkeyPatch, panel_seam: dict[str, Any]
) -> None:
    """Reconstruction raising must not break the panel call; chunks = canon."""

    async def boom(pool: str, *, as_of: str, protocol: str) -> list[dict[str, Any]]:
        raise RuntimeError("defillama unreachable")

    monkeypatch.setattr(
        "gecko_core.orchestration.trade_panel.backtest.reconstruction.reconstruct_pool_chunks",
        boom,
    )

    verdict = await run_trade_panel_with_retrieval(
        idea="x", protocol="kamino", as_of="2026-01-15", pool="pool-abc"
    )
    assert isinstance(verdict, TradePanelVerdict)
    assert panel_seam["panel_chunks"] == _CANON_CHUNKS


@pytest.mark.asyncio
async def test_as_of_datetime_normalized_for_reconstruction(
    panel_seam: dict[str, Any],
) -> None:
    """A non-string ``as_of`` (date/datetime) is normalized to YYYY-MM-DD
    before being forwarded to reconstruction — the reconstruction module's
    contract is a day-bucket string."""
    from datetime import date

    await run_trade_panel_with_retrieval(
        idea="x", protocol="kamino", as_of=date(2026, 3, 7), pool="pool-abc"
    )
    assert panel_seam["recon_calls"] == [("pool-abc", "2026-03-07", "kamino")]
