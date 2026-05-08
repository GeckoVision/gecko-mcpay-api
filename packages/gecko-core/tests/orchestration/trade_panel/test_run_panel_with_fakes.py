"""End-to-end run_trade_panel tests with a fake LLM client.

Per CLAUDE.md feedback_lighter_tests: don't fire AG2 to test the driver.
We inject a per-agent fake replier through the ``agent_factory`` hook —
no autogen import, no network, deterministic.
"""

from __future__ import annotations

from typing import Any

import pytest
from gecko_core.orchestration.trade_panel import (
    REQUIRED_AGENTS,
    TradePanelVerdict,
    run_trade_panel,
)


class _FakeReplier:
    """Returns a canned string when AG2's a_generate_reply is called."""

    def __init__(self, content: str) -> None:
        self._content = content

    async def a_generate_reply(self, messages: list[dict[str, Any]]) -> str:
        return self._content


def _canned_turns(*, verdict: str = "act", dissent: int = 1) -> dict[str, str]:
    """Build the 7 canned per-agent replies.

    ``dissent`` controls how many of the 4 primary analysts point opposite
    the coordinator's verdict. Range 0-4.
    """
    primary_align_act = ["bullish", "greed", "growing", "acceptable"]
    primary_align_pass = ["bearish", "fear", "degraded", "unacceptable"]
    align = primary_align_act if verdict == "act" else primary_align_pass
    oppose = primary_align_pass if verdict == "act" else primary_align_act

    # First `dissent` analysts emit the opposing token, the rest align.
    chosen: list[str] = []
    for i in range(4):
        chosen.append(oppose[i] if i < dissent else align[i])
    trend, sentiment, fundamental, risk = chosen

    return {
        "technical_analyst": (
            "The chart shows a clean accumulation pattern over the last 7d "
            "with volume confirming the move. Support at the prior breakout. "
            "Volatility regime is normal.\n\n"
            f"Trend verdict: {trend}"
        ),
        "sentiment_analyst": (
            "Narrative is constructive — builder voices dominate, retail "
            "framing is muted. No major narrative pivot in the window.\n\n"
            f"Sentiment band: {sentiment}"
        ),
        "fundamental_analyst": (
            "TVL up 12% MoM, fee revenue tracking. Audit posture is clean "
            "post the Mar review. Integrations expanding.\n\n"
            f"Protocol health: {fundamental}"
        ),
        "risk_manager": (
            "Named risks: oracle dependency on Pyth (medium severity, low "
            "likelihood), concentration in top-3 LPs (medium/medium). "
            "Position-size cap recommended at 1%.\n\n"
            f"Risk band: {risk}"
        ),
        "strategist": (
            "Restated: open a directional position. Alignment is broadly "
            "constructive with an elevated-risk caveat. Falsifier: TVL "
            "drops below the Mar floor.\n\n"
            "Strategic intent: open small long, normal stop, weeks horizon"
        ),
        "bull_bear_debater": (
            "BULL CASE: every analyst points the same direction; size could "
            "be doubled.\n\n"
            "BEAR CASE: oracle risk under-weighted; one Pyth incident "
            "unwinds the thesis in minutes.\n\n"
            "Decisive question: Does Pyth's oracle uptime stay above 99.9% "
            "through the next CPI print?"
        ),
        "coordinator": (
            "The panel broadly aligns on a constructive call with a meaningful "
            "risk caveat. Primary drivers are technical alignment and TVL "
            "expansion; the risk_manager's named oracle dependency is the key "
            "blocker question.\n\n"
            "```json\n"
            "{\n"
            f'  "verdict": "{verdict}",\n'
            '  "confidence": 0.7,\n'
            '  "key_drivers": ["technical_analyst alignment", "fundamental TVL growth", "risk_manager oracle caveat"],\n'
            f'  "dissent_count": {dissent},\n'
            '  "blocker_questions": ["Does Pyth uptime hold through CPI?"]\n'
            "}\n"
            "```\n\n"
            f"Final verdict: {verdict}"
        ),
    }


def _factory_for(canned: dict[str, str]):
    def _factory(_llm_config: dict[str, Any]) -> dict[str, Any]:
        return {name: _FakeReplier(canned[name]) for name in REQUIRED_AGENTS}

    return _factory


@pytest.mark.asyncio
async def test_run_panel_emits_seven_turns_and_final_verdict_act() -> None:
    canned = _canned_turns(verdict="act", dissent=1)
    verdict = await run_trade_panel(
        idea="Should I take a small JTO long into the next FOMC?",
        protocol="jito",
        retrieved_chunks=[
            {"text": "JTO TVL up 12% MoM per Zerion snapshot.", "source": "zerion"},
            {"text": "Recent governance proposal increases fee tier.", "source": "exa"},
        ],
        agent_factory=_factory_for(canned),
    )

    assert isinstance(verdict, TradePanelVerdict)
    assert verdict.verdict == "act"
    assert len(verdict.turns) == 7
    # Canonical order preserved.
    assert [t.agent for t in verdict.turns] == list(REQUIRED_AGENTS)
    # Every primary analyst's closing line was parsed.
    for t in verdict.turns:
        if t.agent in {
            "technical_analyst",
            "sentiment_analyst",
            "fundamental_analyst",
            "risk_manager",
            "coordinator",
        }:
            assert t.parsed_verdict is not None, t.agent


@pytest.mark.asyncio
async def test_dissent_count_trusts_coordinator_self_report() -> None:
    """When the coordinator's JSON block reports dissent_count, use it."""
    canned = _canned_turns(verdict="act", dissent=2)
    verdict = await run_trade_panel(
        idea="x",
        protocol="kamino",
        retrieved_chunks=[],
        agent_factory=_factory_for(canned),
    )
    assert verdict.dissent_count == 2


@pytest.mark.asyncio
async def test_pass_verdict_with_full_bear_panel_has_zero_dissent() -> None:
    """When coordinator says pass and all 4 primaries say pass, dissent=0."""
    canned = _canned_turns(verdict="pass", dissent=0)
    verdict = await run_trade_panel(
        idea="Should I open a Drift long?",
        protocol="drift",
        retrieved_chunks=[{"text": "Recent incident, sentiment soft.", "source": "exa"}],
        agent_factory=_factory_for(canned),
    )
    assert verdict.verdict == "pass"
    assert verdict.dissent_count == 0
    assert 0.0 <= verdict.confidence <= 1.0


@pytest.mark.asyncio
async def test_coordinator_json_block_drives_key_drivers_and_blockers() -> None:
    canned = _canned_turns(verdict="act", dissent=1)
    verdict = await run_trade_panel(
        idea="x", protocol="pyth", retrieved_chunks=[], agent_factory=_factory_for(canned)
    )
    assert verdict.key_drivers  # non-empty
    assert any("oracle" in q.lower() or "pyth" in q.lower() for q in verdict.blocker_questions)


@pytest.mark.asyncio
async def test_missing_closing_line_produces_unparsed_verdict() -> None:
    """A persona whose reply omits the closing line surfaces parsed_verdict=None."""
    canned = _canned_turns(verdict="act", dissent=0)
    # Strip the technical analyst's closing line entirely.
    canned["technical_analyst"] = "Some prose with no closing line at all."
    verdict = await run_trade_panel(
        idea="x",
        protocol="jupiter",
        retrieved_chunks=[],
        agent_factory=_factory_for(canned),
    )
    tech = next(t for t in verdict.turns if t.agent == "technical_analyst")
    assert tech.parsed_verdict is None
    # Coordinator still emits a clean verdict.
    assert verdict.verdict == "act"


@pytest.mark.asyncio
async def test_run_panel_requires_llm_config_or_factory() -> None:
    with pytest.raises(ValueError, match="llm_config"):
        await run_trade_panel(
            idea="x",
            protocol="jito",
            retrieved_chunks=[],
        )


@pytest.mark.asyncio
async def test_factory_missing_persona_raises() -> None:
    def _bad_factory(_cfg: dict[str, Any]) -> dict[str, Any]:
        # Drop the coordinator on purpose.
        return {n: _FakeReplier("") for n in REQUIRED_AGENTS if n != "coordinator"}

    with pytest.raises(ValueError, match="coordinator"):
        await run_trade_panel(
            idea="x",
            protocol="jito",
            retrieved_chunks=[],
            agent_factory=_bad_factory,
        )
