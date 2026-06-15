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
from typing import Any

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
