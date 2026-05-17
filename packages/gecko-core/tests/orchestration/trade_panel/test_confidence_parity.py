"""S34-#70 — coordinator confidence parity.

A prod smoke returned a verdict envelope with confidence 0.4 while the
coordinator's own turn prose stated 0.70 — two numbers for one verdict.
``_build_verdict_from_coordinator`` parses two surfaces (the ```json```
fenced block + the prose body) independently and they can disagree.

Per repo memory ``feedback_prompt_iteration_plateau`` the reconciliation
lives in CODE, not a prompt instruction. These tests exercise the pure
helpers directly (light fakes, no panel run) plus one end-to-end check
that the disagreement case collapses to the lower surface.
"""

from __future__ import annotations

from typing import Any

import pytest
from gecko_core.orchestration.trade_panel import (
    _CONF_PARITY_EPSILON,
    REQUIRED_AGENTS,
    _extract_prose_confidence,
    _reconcile_confidence,
    run_trade_panel,
)

# --- _extract_prose_confidence — pure string parsing ---------------------


def test_prose_confidence_fraction_form() -> None:
    assert _extract_prose_confidence("My confidence is 0.70 given the dissent.") == 0.70


def test_prose_confidence_percentage_form() -> None:
    assert _extract_prose_confidence("Confidence: 70% — risk caveat noted.") == 0.70


def test_prose_confidence_bare_integer_treated_as_percent() -> None:
    # A bare ">1" number reads as a percentage, not a [0,1] fraction.
    assert _extract_prose_confidence("Confidence 65 out of 100.") == 0.65


def test_prose_confidence_absent_returns_none() -> None:
    assert _extract_prose_confidence("The panel aligns on a constructive call.") is None


def test_prose_confidence_last_stated_wins() -> None:
    # A coordinator may revise mid-prose; the closing summary number wins.
    text = "Initial read confidence 0.80, but after the risk turn, confidence 0.50."
    assert _extract_prose_confidence(text) == 0.50


# --- _reconcile_confidence — the parity rule -----------------------------


def test_reconcile_no_prose_trusts_block() -> None:
    conf, disagreed = _reconcile_confidence(0.70, None)
    assert conf == 0.70
    assert disagreed is False


def test_reconcile_within_epsilon_is_not_a_conflict() -> None:
    # 0.70 vs 0.72 is rounding noise — block value, no conflict flagged.
    conf, disagreed = _reconcile_confidence(0.70, 0.72)
    assert conf == 0.70
    assert disagreed is False


def test_reconcile_disagreement_takes_lower_surface() -> None:
    """The fix: block says 0.70, prose says 0.40 — envelope must NOT
    inherit the higher number. A split self-report is low-conviction."""
    conf, disagreed = _reconcile_confidence(0.70, 0.40)
    assert conf == 0.40
    assert disagreed is True


def test_reconcile_disagreement_symmetric() -> None:
    # Lower wins regardless of which surface is higher.
    conf, disagreed = _reconcile_confidence(0.30, 0.85)
    assert conf == 0.30
    assert disagreed is True


def test_reconcile_boundary_at_epsilon() -> None:
    # A gap == epsilon is treated as agreement (the rule uses `<=`).
    assert _CONF_PARITY_EPSILON == 0.05
    conf, disagreed = _reconcile_confidence(0.70, 0.65)
    assert disagreed is False
    assert conf == 0.70


def test_reconcile_just_past_epsilon_is_a_conflict() -> None:
    # A gap strictly greater than epsilon flips to conflict → lower wins.
    conf, disagreed = _reconcile_confidence(0.70, 0.60)
    assert disagreed is True
    assert conf == 0.60


# --- end-to-end: the disagreement collapses through the panel ------------


class _FakeReplier:
    def __init__(self, content: str) -> None:
        self._content = content

    async def a_generate_reply(self, messages: list[dict[str, Any]]) -> str:
        return self._content


def _conflicting_coordinator_turns() -> dict[str, str]:
    """7 canned replies where the coordinator's JSON block (0.70) and its
    prose body (0.40) disagree on confidence. All 4 analysts align 'act'
    so no dissent/abstain penalty muddies the assertion."""
    return {
        "technical_analyst": "Clean accumulation.\n\nTrend verdict: bullish",
        "sentiment_analyst": "Builder voices dominate.\n\nSentiment band: greed",
        "fundamental_analyst": "TVL up 12% MoM.\n\nProtocol health: growing",
        "risk_manager": "Risks named and bounded.\n\nRisk band: acceptable",
        "strategist": (
            "Restated thesis.\n\nStrategic intent: open small long, normal stop, weeks horizon"
        ),
        "bull_bear_debater": (
            "BULL CASE: aligned panel.\n\nBEAR CASE: oracle risk.\n\n"
            "Decisive question: Does Pyth uptime hold?"
        ),
        "coordinator": (
            "The panel aligns on a constructive call. On reflection my "
            "confidence is 0.40 — thinner corpus than ideal.\n\n"
            "```json\n"
            "{\n"
            '  "verdict": "act",\n'
            '  "confidence": 0.70,\n'
            '  "key_drivers": ["technical alignment"],\n'
            '  "dissent_count": 0,\n'
            '  "blocker_questions": []\n'
            "}\n"
            "```\n\n"
            "Final verdict: act"
        ),
    }


@pytest.mark.asyncio
async def test_panel_envelope_uses_lower_surface_on_confidence_conflict() -> None:
    canned = _conflicting_coordinator_turns()

    def _factory(_cfg: dict[str, Any]) -> dict[str, Any]:
        return {n: _FakeReplier(canned[n]) for n in REQUIRED_AGENTS}

    verdict = await run_trade_panel(
        idea="Should I open a small JTO long?",
        protocol="jito",
        retrieved_chunks=[],
        agent_factory=_factory,
    )
    assert verdict.verdict == "act"
    # Block said 0.70, prose said 0.40 — envelope must land at the lower
    # surface (the disagreement is itself a low-conviction signal). The
    # S24 band-normalization may clamp further but never inflate past it.
    assert verdict.confidence <= 0.40
