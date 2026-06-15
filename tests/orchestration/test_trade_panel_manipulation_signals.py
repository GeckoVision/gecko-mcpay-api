"""feat/safety-manipulation-signals — manipulation-signal reachability tests.

Two claims, both proven against the ACTUAL production verdict path
(`run_trade_panel_with_retrieval`), per Pattern E ("'wired' != 'reaches the
model'"):

  1. The mint-firing fix: a query carrying an explicit ``mint`` produces
     ``safety.checked is True`` — it no longer depends on cramming the mint
     into the ``protocol`` field (the live BrCA re-run found ``protocol="brca"``
     is not base58, so the check never fired).

  2. The manipulation signals: the BrCA fixture with the REAL on-chain numbers
     (mcap $26.31M, liquidity $22.4K => ratio 0.085%) surfaces a populated
     ``safety.liquidity_to_mcap_pct`` AND a ``fake_market_cap`` flag — the
     signal a venue "Normal" rating missed.

No live network: QuickNode + CoinGecko on-chain responses are served through
`httpx.MockTransport` (vcr-style); retrieval is monkeypatched to skip Mongo; the
panel runs canned repliers, so no LLM call.
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
from gecko_core.sources.coingecko import CoinGeckoClient
from gecko_core.sources.quicknode import QuickNodeClient

_FIX = Path(__file__).parent / "fixtures"

# A valid base58 32-byte SPL mint. The contract-safety read needs the address it
# checks to decode to 32 bytes (is_spl_mint); the fixture JSON content is what
# the mocked transport returns regardless of the address string.
_BRCA_MINT = "BRcaUSDC11111111111111111111111111111111111"


def _load(name: str) -> Any:
    return json.loads((_FIX / name).read_text())


def _qn_handler(request: httpx.Request) -> httpx.Response:
    """Clean (renounced) mint so the test isolates the manipulation signal from
    the honeypot signal — only mcap-vs-liquidity should flag here."""
    body = json.loads(request.content)
    method = body["method"]
    if method == "getAccountInfo":
        return httpx.Response(200, json=_load("quicknode_mint_clean.json"))
    if method == "getTokenLargestAccounts":
        return httpx.Response(200, json=_load("quicknode_largest_clean.json"))
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})


def _safety_client() -> QuickNodeClient:
    transport = httpx.MockTransport(_qn_handler)
    return QuickNodeClient("https://rpc.example/qn", client=httpx.AsyncClient(transport=transport))


def _cg_handler(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_load("coingecko_onchain_brca.json"))


def _market_client() -> CoinGeckoClient:
    transport = httpx.MockTransport(_cg_handler)
    return CoinGeckoClient(client=httpx.AsyncClient(transport=transport))


# --- canned panel (no LLM) -------------------------------------------------

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
    """Skip Mongo — retrieval is orthogonal to the manipulation-signal claim."""

    async def _empty(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        "gecko_core.orchestration.trade_panel.retrieve_trade_corpus_chunks",
        _empty,
    )


def _run(*, protocol: str, mint: str | None) -> Any:
    return asyncio.run(
        run_trade_panel_with_retrieval(
            idea="is this token a good buy right now?",
            protocol=protocol,
            mint=mint,
            agent_factory=_agent_factory,
            safety_client=_safety_client(),
            safety_market_client=_market_client(),
        )
    )


# --- the firing fix --------------------------------------------------------


def test_mint_param_fires_safety_check() -> None:
    """An explicit ``mint`` produces safety.checked=true even when ``protocol``
    is a non-base58 name (the BrCA live-re-run failure mode)."""
    verdict = _run(protocol="brca", mint=_BRCA_MINT)
    assert verdict.safety is not None
    assert isinstance(verdict.safety, SafetyBlock)
    assert verdict.safety.checked is True
    assert verdict.safety.source.startswith("quicknode")


def test_protocol_string_alone_does_not_fire() -> None:
    """Without a mint, a non-base58 protocol name fails OPEN — this is the
    seam the firing fix closes (regression guard)."""
    verdict = _run(protocol="brca", mint=None)
    assert verdict.safety is not None
    assert verdict.safety.checked is False
    assert "not_a_token_mint" in verdict.safety.rug_flags


# --- the manipulation signal (BrCA real numbers) ---------------------------


def test_brca_real_numbers_flag_fake_market_cap() -> None:
    """mcap $26.31M / liquidity $22.4K = 0.085% => fake_market_cap.

    This is the case DexView rated "Normal". The verdict envelope must surface
    both the computed ratio AND the explicit flag.
    """
    verdict = _run(protocol="brca", mint=_BRCA_MINT)
    safety = verdict.safety
    assert safety is not None

    # The ratio is populated (reaches the model), not None.
    assert safety.market_cap_usd == pytest.approx(26_310_000.0)
    assert safety.liquidity_usd == pytest.approx(22_400.0)
    assert safety.liquidity_to_mcap_pct is not None
    assert safety.liquidity_to_mcap_pct == pytest.approx(0.0851, abs=1e-3)

    # Both manipulation flags fire (fake_market_cap implies thin_liquidity too).
    assert "fake_market_cap" in safety.rug_flags
    assert "thin_liquidity_vs_mcap" in safety.rug_flags

    # A confirmed fake_market_cap floors confidence + prepends a loud driver +
    # blocker — same amplification pattern as honeypot, verdict literal intact.
    assert verdict.confidence == 0.0
    assert any("fake market cap" in d.lower() for d in verdict.key_drivers)
    assert any("liquidity" in q.lower() for q in verdict.blocker_questions)
    assert verdict.verdict == "act"  # literal NOT flipped


def test_market_source_unavailable_fails_open() -> None:
    """No market client + chain read still returns => manipulation signals None,
    explicit ``manipulation_check_unavailable``, chain rug read preserved."""

    def _no_market(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": [{"status": "404"}]})

    verdict = asyncio.run(
        run_trade_panel_with_retrieval(
            idea="is this token a good buy right now?",
            protocol="brca",
            mint=_BRCA_MINT,
            agent_factory=_agent_factory,
            safety_client=_safety_client(),
            safety_market_client=CoinGeckoClient(
                client=httpx.AsyncClient(transport=httpx.MockTransport(_no_market))
            ),
        )
    )
    safety = verdict.safety
    assert safety is not None
    assert safety.checked is True  # chain read still ran
    assert safety.liquidity_to_mcap_pct is None
    assert "manipulation_check_unavailable" in safety.rug_flags
    assert "fake_market_cap" not in safety.rug_flags
