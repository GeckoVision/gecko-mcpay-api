"""S39-#140 — `_ABSTAIN_TOKENS` calibration tests.

Pins the narrowed abstain set per the ai-ml-engineer diagnosis at commit
6da037a (`docs/strategy/2026-05-19-skill-side-trading-improvements.md`
§1). `sentiment_analyst: neutral` and `risk_manager: elevated` are
directional reads under their persona prompts in `_default_prompts.json`
— not abstentions. Counting them as abstains over-triggered the
abstain-floor rule in `_build_verdict_from_coordinator` and rewrote
coordinator `pass` into `defer` (the 2026-05-19 JTO/JUP/PYTH demo polls).

These tests are light fakes — they feed `TradePanelTurn` lists directly
into the pure helpers, no AG2, no LLM calls.
"""

from __future__ import annotations

from gecko_core.orchestration.trade_panel import (
    _ABSTAIN_TOKENS,
    _build_verdict_from_coordinator,
    _count_abstains,
)
from gecko_core.orchestration.trade_panel.models import TradePanelTurn

# --- Abstain-set membership pins ----------------------------------------


def test_sentiment_neutral_is_not_an_abstain_token() -> None:
    """Per `_default_prompts.json` line 6: *'neutral' ... is NOT an
    abstain signal.* The CODE must agree with the persona prompt."""
    assert "sentiment_analyst" not in _ABSTAIN_TOKENS


def test_risk_elevated_is_not_an_abstain_token() -> None:
    """Per `_default_prompts.json` line 8: `elevated` = above-baseline
    named risks (size down / tighter stops) — a real directional read.
    Only `unacceptable` is a structural veto, and that's handled by the
    S37-WS2 Rule 1 risk-veto path, not the abstain floor."""
    assert "risk_manager" not in _ABSTAIN_TOKENS


def test_technical_mixed_remains_an_abstain() -> None:
    """Genuine no-directional-call token per the macro_regime prompt."""
    assert "mixed" in _ABSTAIN_TOKENS["technical_analyst"]


def test_fundamental_stable_remains_an_abstain() -> None:
    """`stable` stays a true abstain — the fundamental prompt's
    abstain-protocol honest default when the corpus is empty."""
    assert "stable" in _ABSTAIN_TOKENS["fundamental_analyst"]


# --- _count_abstains observable behavior --------------------------------


def _turn(agent: str, key: str, value: str) -> TradePanelTurn:
    return TradePanelTurn(
        agent=agent,
        content=f"{key}: {value}",
        parsed_verdict={key: value},
    )


def test_count_abstains_does_not_count_neutral_or_elevated() -> None:
    """Sentiment neutral + risk elevated were the two mis-classified
    tokens. With both fired together, the count must be 0."""
    turns = [
        _turn("sentiment_analyst", "sentiment_band", "neutral"),
        _turn("risk_manager", "risk_band", "elevated"),
    ]
    assert _count_abstains(turns) == 0


def test_count_abstains_still_catches_real_abstains() -> None:
    """Mixed + stable still count — the rule's signal is preserved."""
    turns = [
        _turn("technical_analyst", "trend_verdict", "mixed"),
        _turn("fundamental_analyst", "protocol_health", "stable"),
    ]
    assert _count_abstains(turns) == 2


# --- End-to-end: the JTO/JUP demo bug ----------------------------------


def _coord_content(verdict: str) -> str:
    return (
        "The panel reviewed the proposal.\n\n"
        "```json\n"
        "{\n"
        f'  "verdict": "{verdict}",\n'
        '  "confidence": 0.65,\n'
        '  "key_drivers": ["panel review"],\n'
        '  "dissent_count": 0,\n'
        '  "blocker_questions": []\n'
        "}\n"
        "```\n\n"
        f"Final verdict: {verdict}"
    )


def test_coordinator_pass_with_neutral_and_elevated_stays_pass() -> None:
    """The falsifiable case behind the 2026-05-19 JTO/JUP demo polls.

    Pre-fix: coordinator emits `pass`; abstain-floor (sentiment=neutral,
    fundamental=stable, risk=elevated) counts 3 → rewrites to `defer`.
    Post-fix: only `fundamental=stable` counts (1 abstain) → `pass`
    survives. risk=elevated is NOT `unacceptable`, so Rule 1 does not
    fire; framing carries no rotation tokens, so Rule 2 does not fire.
    """
    turns = [
        TradePanelTurn(
            agent="technical_analyst",
            content="Trend verdict: bearish",
            parsed_verdict={"trend_verdict": "bearish"},
        ),
        TradePanelTurn(
            agent="sentiment_analyst",
            content="Sentiment band: neutral",
            parsed_verdict={"sentiment_band": "neutral"},
        ),
        TradePanelTurn(
            agent="fundamental_analyst",
            content="Protocol health: stable",
            parsed_verdict={"protocol_health": "stable"},
        ),
        TradePanelTurn(
            agent="risk_manager",
            content="Risk band: elevated",
            parsed_verdict={"risk_band": "elevated"},
        ),
        TradePanelTurn(
            agent="strategist",
            content="Strategic intent: observe spot for now.",
            parsed_verdict={"strategic_intent": "observe spot for now."},
        ),
        TradePanelTurn(
            agent="bull_bear_debater",
            content="Decisive question: Does momentum reverse this week?",
            parsed_verdict={"decisive_question": "Does momentum reverse this week?"},
        ),
        TradePanelTurn(
            agent="coordinator",
            content=_coord_content("pass"),
            parsed_verdict={"verdict": "pass"},
        ),
    ]
    verdict = _build_verdict_from_coordinator(turns)
    assert verdict.verdict == "pass", (
        f"expected pass, got {verdict.verdict} — abstain-floor narrowing regressed"
    )


def test_coordinator_pass_still_defers_on_three_real_abstains() -> None:
    """Sanity check: if THREE primary analysts genuinely abstain (mixed +
    stable; sentiment_analyst absent entirely), the abstain-floor STILL
    fires on a coordinator `pass`. We narrowed the SET, not the rule.

    Construction: 3 'fundamental_analyst' turns each emitting `stable` so
    `_count_abstains` returns 3 against the surviving abstain set. This
    is a structural pin — proving the rule still has teeth after the
    narrowing — not a fixture of any real panel shape.
    """
    turns = [
        _turn("technical_analyst", "trend_verdict", "mixed"),
        _turn("fundamental_analyst", "protocol_health", "stable"),
        # Two extra fundamental turns to push the count to 3 without
        # leaning on the dropped sentiment/risk tokens.
        _turn("fundamental_analyst", "protocol_health", "stable"),
        _turn("fundamental_analyst", "protocol_health", "stable"),
        TradePanelTurn(
            agent="coordinator",
            content=_coord_content("pass"),
            parsed_verdict={"verdict": "pass"},
        ),
    ]
    verdict = _build_verdict_from_coordinator(turns)
    assert verdict.verdict == "defer"
    assert any("abstained" in b for b in verdict.blocker_questions)
