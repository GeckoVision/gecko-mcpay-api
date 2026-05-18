"""Issue #15 / S35-#99 — split structured citation arrays on the wire.

Pre-#15, the trade-oracle response exposed cites only as inline ``[N]``
markers inside ``turns[].content``. Issue #15 added a single top-level
``citations: list[Citation]`` array.

S35-#99 split that single array into two top-level lists so the eval
rubric's ``citation_relevance`` dimension stops being dragged down by
cross-cutting investor-canon prose:

- ``evidence_citations`` — "the data": protocol/market-data chunks a
  panel turn actually referenced (provider_kind in
  ``protocol_native`` / ``market_data`` / ``paysh_live`` /
  ``bazaar_live``). Relevance-trimmed.
- ``framework_context`` — "the lens": investor-canon chunks
  (``canon_*``). NOT relevance-trimmed — canon is cross-cutting.

This test pins the additive two-field contract:

- Each entry in BOTH lists carries ``{id, source, url, chunk_id,
  provider_kind, freshness_tier, snippet}``.
- ``id`` is 1-indexed *within each list* and matches the inline ``[N]``
  markers the panel injects.
- ``provider_kind`` and ``freshness_tier`` round-trip the canonical
  Literals from :mod:`gecko_core.sources.types` (Pattern A).
- Both envelopes (basic + pro) carry both lists — the wedge claim
  "grounded citations" applies to both tiers; only ``backtest`` is
  pro-only.
- The partition is enforced: ``canon_*`` chunks land in
  ``framework_context``, evidence-kind chunks in ``evidence_citations``
  — matching what ``partition_emitted_citations`` produces.

Mocks ``run_trade_panel_with_retrieval`` so this never fires AG2,
CoinGecko, or Mongo.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")


_REQUIRED_CITATION_KEYS = {
    "id",
    "source",
    "url",
    "chunk_id",
    "provider_kind",
    "freshness_tier",
    "snippet",
}

# S35-#99 — provider_kind buckets the wire split must honour. Mirrors
# partition_emitted_citations: canon_* -> framework_context, everything
# else (protocol/market data) -> evidence_citations.
_EVIDENCE_PROVIDER_KINDS = {
    "protocol_native",
    "market_data",
    "paysh_live",
    "bazaar_live",
}


def _decode_payment_required_header(value: str) -> dict:
    return json.loads(base64.b64decode(value).decode("utf-8"))


def _build_payment_payload_header(accepts_entry: dict) -> str:
    payload_obj = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
        "accepted": accepts_entry,
    }
    return base64.b64encode(json.dumps(payload_obj).encode("utf-8")).decode("utf-8")


def _paid_post(client: TestClient, *, path: str, body: dict) -> tuple[int, dict]:
    r0 = client.post(path, json=body)
    assert r0.status_code == 402, r0.text
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    payment_header = _build_payment_payload_header(accepts_entry)
    r = client.post(path, json=body, headers={"PAYMENT-SIGNATURE": payment_header})
    out: dict = {}
    try:
        out = r.json()
    except Exception:
        out = {}
    return r.status_code, out


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Patch the panel runner with a fake that attaches the two split lists.

    The fake mirrors what the real wrapper does post-S35-#99:
    ``run_trade_panel_with_retrieval`` projects the chunks-that-fed-the-
    panel into ``Citation`` lists, partitions them by provider_kind via
    ``partition_emitted_citations``, and attaches ``evidence_citations``
    (protocol/market data) + ``framework_context`` (investor canon) to
    the verdict.
    """
    os.environ["X402_NETWORK"] = "solana-devnet"
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)

    from gecko_api.main import app
    from gecko_core.orchestration.trade_panel import (
        Citation,
        TradePanelTurn,
        TradePanelVerdict,
    )

    # "The data" — protocol/market-data chunks. id is 1-indexed within
    # this list. partition_emitted_citations would route both of these
    # into evidence_citations (paysh_live / bazaar_live are evidence kinds).
    fake_evidence = [
        Citation(
            id=1,
            source="paysh",
            url="https://paysh.sh/listing/jito",
            chunk_id="chunk-jito-1",
            provider_kind="paysh_live",
            freshness_tier="daily",
            snippet="JTO TVL grew 12% over the trailing 7d window across mainnet.",
        ),
        Citation(
            id=2,
            source="bazaar",
            # No URL — ensure the gecko://chunk/<hash> fallback is acceptable
            # too. The real wrapper synthesizes it; here we exercise the
            # fully-populated path explicitly to assert the shape contract.
            url="gecko://chunk/abcd1234567890ef",
            chunk_id="chunk-jito-2",
            provider_kind="bazaar_live",
            freshness_tier="live_only",
            snippet="Coordinator transcript snippet about validator rotation.",
        ),
    ]

    # "The lens" — investor-canon chunks. id is 1-indexed *independently*
    # of evidence_citations. partition_emitted_citations would route this
    # into framework_context (canon_* is a framework kind, never trimmed).
    fake_framework = [
        Citation(
            id=1,
            source="damodaran",
            url="https://pages.stern.nyu.edu/~adamodar/risk-premium.pdf",
            chunk_id="chunk-canon-1",
            provider_kind="canon_damodaran",
            freshness_tier="static",
            snippet="Equity risk premia widen when macro uncertainty spikes around policy events.",
        ),
    ]

    base_turns = [
        TradePanelTurn(
            agent="technical_analyst",
            content="Bullish, citing [1] and [2].",
            parsed_verdict={"trend_verdict": "bullish"},
        ),
        TradePanelTurn(
            agent="coordinator",
            content='```json\n{"verdict": "act"}\n```',
            parsed_verdict={"verdict": "act"},
        ),
    ]

    async def fake_panel(
        *,
        idea: str,
        protocol: str,
        vertical: str = "dex",
        tier: str = "basic",
        top_k: int = 15,
        llm_config: dict | None = None,
        agent_factory: object | None = None,
        enable_backtest: bool = False,
        history_source: object | None = None,
    ) -> TradePanelVerdict:
        verdict = TradePanelVerdict(
            verdict="act",
            confidence=0.7,
            key_drivers=["technical alignment"],
            dissent_count=0,
            blocker_questions=[],
            turns=base_turns,
            evidence_citations=fake_evidence,
            framework_context=fake_framework,
        )
        if enable_backtest:
            from gecko_core.orchestration.trade_panel.backtest import BacktestReport

            verdict = verdict.model_copy(
                update={
                    "backtest": BacktestReport(
                        pnl_pct=4.2,
                        drawdown_pct=1.1,
                        n_similar_setups=1,
                        hit_rate=1.0,
                        source="coingecko",
                        unbacktestable=False,
                    )
                }
            )
        return verdict

    with (
        patch(
            "gecko_core.orchestration.trade_panel.run_trade_panel_with_retrieval",
            new=AsyncMock(side_effect=fake_panel),
        ),
        TestClient(app) as c,
    ):
        yield c


_BODY = {"idea": "Should I open a JTO long around the next FOMC?", "protocol": "jito"}


def _assert_citation_shape(citations: list[dict]) -> None:
    """Per-entry shape contract — shared by both split lists (S35-#99)."""
    assert isinstance(citations, list)
    assert len(citations) >= 1, "expected at least one citation entry"
    for entry in citations:
        assert isinstance(entry, dict), f"non-dict citation: {entry!r}"
        missing = _REQUIRED_CITATION_KEYS - entry.keys()
        assert not missing, f"citation missing keys {missing!r}: {entry!r}"
        assert isinstance(entry["id"], int) and entry["id"] >= 1
        assert isinstance(entry["snippet"], str)
        assert len(entry["snippet"]) <= 240


def test_basic_envelope_carries_split_citation_lists(client: TestClient) -> None:
    """Basic /trade_research must surface BOTH split lists (S35-#99)."""
    status, body = _paid_post(client, path="/trade_research", body=_BODY)
    assert status == 200, body
    assert "evidence_citations" in body, f"missing evidence_citations; keys={sorted(body)!r}"
    assert "framework_context" in body, f"missing framework_context; keys={sorted(body)!r}"
    # The old single citations[] is gone — #99 is a breaking rename.
    assert "citations" not in body, f"old single citations[] leaked: {body.get('citations')!r}"
    _assert_citation_shape(body["evidence_citations"])
    _assert_citation_shape(body["framework_context"])
    # Issue #15: basic still must NOT carry backtest (pro-only field).
    assert "backtest" not in body, f"basic leaked backtest: {body.get('backtest')!r}"


def test_pro_envelope_carries_split_citations_and_backtest(client: TestClient) -> None:
    """Pro envelope carries both split lists AND #14's backtest field."""
    status, body = _paid_post(client, path="/trade_research/pro", body=_BODY)
    assert status == 200, body
    assert "evidence_citations" in body
    assert "framework_context" in body
    _assert_citation_shape(body["evidence_citations"])
    _assert_citation_shape(body["framework_context"])
    assert body.get("backtest") is not None
    assert isinstance(body["backtest"], dict)


def test_split_partitions_evidence_vs_canon_by_provider_kind(client: TestClient) -> None:
    """S35-#99: evidence_citations holds protocol/market data, framework_context holds canon.

    Pins what ``partition_emitted_citations`` produces — ``canon_*`` chunks
    must never land in ``evidence_citations`` (or they drag the rubric's
    ``citation_relevance`` dimension), and evidence-kind chunks must never
    land in ``framework_context``.
    """
    from gecko_core.sources.types import FRESHNESS_TIER_VALUES, PROVIDER_KINDS

    status, body = _paid_post(client, path="/trade_research", body=_BODY)
    assert status == 200, body
    evidence = body["evidence_citations"]
    framework = body["framework_context"]

    # The partition must be non-trivial — both sides populated, so the
    # assertions below actually exercise the split.
    assert evidence, "evidence_citations unexpectedly empty"
    assert framework, "framework_context unexpectedly empty"

    for entry in evidence:
        assert entry["provider_kind"] in PROVIDER_KINDS
        assert entry["freshness_tier"] in FRESHNESS_TIER_VALUES
        assert not entry["provider_kind"].startswith("canon_"), (
            f"canon chunk {entry['provider_kind']!r} leaked into evidence_citations"
        )
        assert entry["provider_kind"] in _EVIDENCE_PROVIDER_KINDS, (
            f"non-evidence provider_kind {entry['provider_kind']!r} in evidence_citations"
        )

    for entry in framework:
        assert entry["provider_kind"] in PROVIDER_KINDS
        assert entry["freshness_tier"] in FRESHNESS_TIER_VALUES
        assert entry["provider_kind"].startswith("canon_"), (
            f"non-canon chunk {entry['provider_kind']!r} leaked into framework_context"
        )


def test_citation_ids_are_one_indexed_within_each_list(client: TestClient) -> None:
    """The 1-indexed id is contiguous *within each list* (S35-#99).

    ``build_citations_from_chunks`` re-indexes evidence and framework
    independently, so each list is 1..len(list) on its own — they do NOT
    share a global counter.
    """
    status, body = _paid_post(client, path="/trade_research", body=_BODY)
    assert status == 200, body
    evidence = body["evidence_citations"]
    framework = body["framework_context"]
    assert [c["id"] for c in evidence] == list(range(1, len(evidence) + 1))
    assert [c["id"] for c in framework] == list(range(1, len(framework) + 1))
