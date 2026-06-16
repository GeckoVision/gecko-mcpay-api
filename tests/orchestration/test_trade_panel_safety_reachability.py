"""feat/verdict-contract-safety — reachability test (Pattern E).

The WHOLE POINT: prove the contract-safety signal reaches the SOLD verdict
envelope, not just that the QuickNode client works in isolation. Per Pattern E
("'wired' != 'reaches the model'"), per-layer unit tests on `quicknode.py` are
necessary but NOT sufficient — this test calls the actual production verdict
path (`run_trade_panel_with_retrieval`) with a token-mint question and asserts
`verdict.safety.honeypot is not None` (populated from the source).

No live network: a recorded-fixture QuickNode response is served through an
`httpx.MockTransport` (vcr-style), and retrieval is monkeypatched to skip Mongo.
The panel itself runs through an `agent_factory` of canned repliers, so no LLM
call either. The test FAILS if the safety signal is absent from the envelope.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
from gecko_core.orchestration.trade_panel import (
    SafetyBlock,
    run_trade_panel_with_retrieval,
)
from gecko_core.orchestration.trade_panel.personas import (
    BULL_BEAR_DEBATER,
    COORDINATOR,
    FUNDAMENTAL_ANALYST,
    RISK_MANAGER,
    SENTIMENT_ANALYST,
    STRATEGIST,
    TECHNICAL_ANALYST,
)
from gecko_core.sources.coingecko import OnchainTokenMarket
from gecko_core.sources.quicknode import QuickNodeClient

_FIX = Path(__file__).parent / "fixtures"

# A valid base58 32-byte SPL mint with mint+freeze authority PRESENT (the
# honeypot fixture) — the dev can dilute/freeze => rug_risk True => honeypot.
_HONEYPOT_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


def _load(name: str) -> Any:
    return json.loads((_FIX / name).read_text())


def _qn_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    method = body["method"]
    if method == "getAccountInfo":
        return httpx.Response(200, json=_load("quicknode_mint_honeypot.json"))
    if method == "getTokenLargestAccounts":
        return httpx.Response(200, json=_load("quicknode_largest_honeypot.json"))
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})


def _safety_client() -> QuickNodeClient:
    transport = httpx.MockTransport(_qn_handler)
    return QuickNodeClient("https://rpc.example/qn", client=httpx.AsyncClient(transport=transport))


class _NoMarketClient:
    """Offline market client — keeps this reachability test off the network.

    The manipulation (mcap/liquidity) read is out of scope here: this test
    asserts the *contract-safety* (QuickNode) signal reaches the envelope, so
    the market client returns None and ``source`` stays ``"quicknode"``. Without
    this, the default client would hit the live GeckoTerminal endpoint for the
    fixture mint, breaking the "No live network" guarantee in the docstring.
    """

    async def onchain_token_market(self, *_args: Any, **_kwargs: Any) -> None:
        return None


# --- canned panel (no LLM) -------------------------------------------------

# Each persona's closing line matches CLOSING_LINE_PATTERNS so the panel parses
# a clean verdict without touching a model.
_CANNED: dict[str, str] = {
    TECHNICAL_ANALYST: "Read is mixed.\nTrend verdict: mixed",
    SENTIMENT_ANALYST: "Chatter is muted.\nSentiment band: neutral",
    FUNDAMENTAL_ANALYST: "Mechanics ok.\nProtocol health: stable",
    RISK_MANAGER: "Risk is fine on paper.\nRisk band: acceptable",
    STRATEGIST: "Thesis.\nStrategic intent: enter small with a tight stop",
    BULL_BEAR_DEBATER: "Both sides.\nDecisive question: is the contract safe?",
    COORDINATOR: (
        '{"verdict": "act", "confidence": 0.7, "key_drivers": ["structurally fine"]}\n'
        "Final verdict: act"
    ),
}


class _CannedReplier:
    def __init__(self, text: str) -> None:
        self._text = text

    async def a_generate_reply(self, *, messages: list[dict[str, Any]]) -> str:
        return self._text


def _agent_factory(_llm_config: dict[str, Any]) -> dict[str, Any]:
    return {name: _CannedReplier(text) for name, text in _CANNED.items()}


@pytest.fixture(autouse=True)
def _no_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip Mongo — retrieval is orthogonal to the safety-reachability claim."""

    async def _empty(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        "gecko_core.orchestration.trade_panel.retrieve_trade_corpus_chunks",
        _empty,
    )


def _run(target: str) -> Any:
    return asyncio.run(
        run_trade_panel_with_retrieval(
            idea="should I buy this token right now?",
            protocol=target,
            agent_factory=_agent_factory,
            safety_client=_safety_client(),
            safety_market_client=_NoMarketClient(),
        )
    )


# --- the reachability assertion (Pattern E) --------------------------------


def test_safety_block_reaches_verdict_envelope_for_token_mint() -> None:
    """A token-mint query MUST surface a populated safety block on the verdict.

    This is the failing-if-unwired guard: if the safety signal is dropped
    anywhere between the QuickNode client and the assembled envelope, either
    `verdict.safety is None` or `verdict.safety.honeypot is None` and the test
    fails — exactly the Pattern E gap this work closes.
    """
    verdict = _run(_HONEYPOT_MINT)

    assert verdict.safety is not None, "safety block missing from verdict envelope"
    assert isinstance(verdict.safety, SafetyBlock)
    # The whole point: the signal is POPULATED from the source, not a placeholder.
    assert verdict.safety.honeypot is not None
    assert verdict.safety.checked is True
    assert verdict.safety.source == "quicknode"


def test_honeypot_mint_flags_and_amplifies() -> None:
    """Un-renounced authorities => honeypot True, loud on the envelope."""
    verdict = _run(_HONEYPOT_MINT)
    safety = verdict.safety
    assert safety is not None
    assert safety.honeypot is True
    assert safety.mint_mutable is True
    assert safety.freeze_mutable is True
    # Holder concentration (60% top holder in the fixture) is flagged.
    assert safety.top_holder_pct is not None and safety.top_holder_pct > 0.5
    assert "mint_not_renounced" in safety.rug_flags
    assert "high_holder_concentration" in safety.rug_flags
    # A hard honeypot is amplified: confidence floored + leading driver/blocker.
    assert verdict.confidence == 0.0
    assert any("CONTRACT SAFETY" in d for d in verdict.key_drivers)
    assert any("safety check" in q.lower() for q in verdict.blocker_questions)


def test_known_protocol_fails_open_explicitly() -> None:
    """A non-mint protocol name yields an explicit fail-OPEN block (not None)."""
    verdict = _run("kamino")
    safety = verdict.safety
    assert safety is not None
    assert safety.checked is False
    assert safety.honeypot is None
    assert "not_a_token_mint" in safety.rug_flags


# --- Phase 0.2: the safety read REACHES the panel + grounds (Pattern E) -----
#
# The post-hoc-only attach left the live on-chain numbers out of the prompt AND
# out of the grounding snippet corpus, so a voice that mentioned them got
# REDACTED (the "BrCA redaction"). These tests prove the synthetic onchain_live
# chunk now (a) is built into the chunk slate, (b) reaches the model's prompt,
# (c) surfaces as a real citation — so the numbers are grounded-by-construction.

# BrCA-like thin-liquidity market: $26.65M mcap / $160K liquidity = 0.600%.
# Below the 1.0% thin threshold AND below the $500K absolute floor =>
# thin_liquidity_vs_mcap (a venue "Normal" rating would miss this).
_BRCA_MCAP = 26_650_000.0
_BRCA_LIQUIDITY = 160_000.0


class _ThinLiquidityMarketClient:
    """Offline market client returning BrCA-like thin-liquidity numbers.

    Keeps the test off the network while populating the manipulation signal so
    the synthetic onchain_live chunk carries real liquidity/mcap figures.
    """

    async def onchain_token_market(self, *_args: Any, **_kwargs: Any) -> OnchainTokenMarket:
        return OnchainTokenMarket(
            market_cap_usd=_BRCA_MCAP,
            fdv_usd=_BRCA_MCAP,
            total_reserve_in_usd=_BRCA_LIQUIDITY,
        )


class _RecordingReplier:
    """Canned replier that records the prompt it was handed (for reachability)."""

    seen_prompts: ClassVar[list[str]] = []

    def __init__(self, text: str) -> None:
        self._text = text

    async def a_generate_reply(self, *, messages: list[dict[str, Any]]) -> str:
        for m in messages:
            content = m.get("content")
            if isinstance(content, str):
                _RecordingReplier.seen_prompts.append(content)
        return self._text


def _recording_agent_factory(_llm_config: dict[str, Any]) -> dict[str, Any]:
    return {name: _RecordingReplier(text) for name, text in _CANNED.items()}


def _run_with_market() -> Any:
    _RecordingReplier.seen_prompts = []
    return asyncio.run(
        run_trade_panel_with_retrieval(
            idea="is this token a good buy right now?",
            protocol="brca",
            mint=_HONEYPOT_MINT,
            agent_factory=_recording_agent_factory,
            safety_client=_safety_client(),
            safety_market_client=_ThinLiquidityMarketClient(),
        )
    )


def test_onchain_live_chunk_reaches_panel_prompt() -> None:
    """The live safety numbers reach the MODEL, not just the envelope (Pattern E).

    The synthetic onchain_live chunk must appear in the panel's opening prompt
    (the text every voice — incl. risk_manager — reads). Asserting the prompt
    contains the on-chain marker AND a live figure proves the read was fired
    BEFORE the panel and merged into the slate, not attached post-hoc.
    """
    _run_with_market()
    joined = "\n".join(_RecordingReplier.seen_prompts)
    assert "On-chain live read" in joined, "onchain_live chunk never reached the panel prompt"
    # A live figure is present in the prompt — liquidity/mcap ratio (0.600%).
    assert "liquidity/mcap" in joined
    assert "thin_liquidity_vs_mcap" in joined


def test_onchain_live_chunk_surfaces_as_grounded_citation() -> None:
    """The onchain_live chunk becomes a real citation => its numbers ground.

    The grounding gate's snippet corpus is built from the verdict's citation
    snippets. With the onchain_live chunk in the evidence path, its live figures
    are in that corpus — a voice citing them grounds by construction (no
    redaction). This asserts the citation surface, which IS the gate's input.
    """
    verdict = _run_with_market()
    onchain_cites = [c for c in verdict.evidence_citations if c.provider_kind == "onchain_live"]
    assert onchain_cites, "onchain_live chunk did not surface as an evidence citation"
    # The snippet (what the grounding gate reads) carries the live figures.
    snippet = onchain_cites[0].snippet
    assert "On-chain live read" in snippet
    assert "liquidity/mcap" in snippet


def test_onchain_live_chunk_in_grounding_snippet_corpus() -> None:
    """End-to-end: the gate's snippet corpus contains the live on-chain numbers.

    Directly traces the grounding gate's `_snippet_corpus` over the produced
    verdict and asserts the onchain_live figures are present — so a voice claim
    matching them is grounded, never redacted (the BrCA-redaction fix).
    """
    from gecko_core.orchestration.trade_panel.grounding_gate import _snippet_corpus

    verdict = _run_with_market()
    corpus = "\n".join(_snippet_corpus(verdict))
    assert "On-chain live read" in corpus
    assert "liquidity/mcap" in corpus


def test_safety_block_still_populated_with_market_read() -> None:
    """Existing contract intact: safety block still populated + amplified.

    Reuse-once means the SAME block feeds both the pre-panel chunk and the
    post-panel `_attach_safety`. The envelope must still carry the populated
    block (and the manipulation read), proving the pre-panel move did not lose
    the post-hoc amplifier.
    """
    verdict = _run_with_market()
    safety = verdict.safety
    assert safety is not None
    assert safety.checked is True
    assert safety.source == "quicknode+coingecko"
    assert safety.liquidity_to_mcap_pct is not None
    assert "thin_liquidity_vs_mcap" in safety.rug_flags
