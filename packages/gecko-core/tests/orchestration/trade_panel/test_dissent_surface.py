"""Sprint 18 #3 — structured ``dissent`` surface on TradePanelVerdict.

Per the 2026-05-28 Sprint 18 design synthesis + the business-manager /
product-manager moat docs: the wedge (surviving dissent vs consensus mush)
must be visible at the BASIC tier of the verdict envelope. Today the only
surface is ``dissent_count: int`` — that surface tells you SOMETHING
disagreed but not WHO or WHAT. The structured ``dissent`` list closes that.

These tests verify:
  1. The extractor returns ``[]`` on a unanimous run (no voice opposes,
     no voice abstains) — empty is the honest default.
  2. ``oppose`` entries fire when a primary analyst's directional token
     points opposite to the coordinator's verdict.
  3. ``abstain`` entries fire when technical='mixed' or fundamental='stable'.
  4. The verbatim is the closing-line token VALUE (never the prose body,
     never paraphrased).
  5. The ``on_topic`` carries the per-voice short summary.
  6. Strategist + bull_bear_debater + coordinator are never in the surface
     (they have no directional closing-line token to disagree on).
  7. Verdict assembly populates the ``dissent`` field on the envelope.

Light fakes only per ``feedback_lighter_tests``; no LLM calls, no DB.
"""

from __future__ import annotations

from gecko_core.orchestration.trade_panel import (
    _build_verdict_from_coordinator,
    _extract_dissent_entries,
)
from gecko_core.orchestration.trade_panel.models import (
    DissentEntry,
    TradePanelTurn,
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


def _turn(agent: str, content: str, parsed: dict | None) -> TradePanelTurn:
    return TradePanelTurn(agent=agent, content=content, parsed_verdict=parsed)


def _unanimous_act_turns() -> list[TradePanelTurn]:
    """All four primaries align with 'act'; coordinator says act."""
    return [
        _turn(TECHNICAL_ANALYST, "...\nTrend verdict: bullish", {"trend_verdict": "bullish"}),
        _turn(SENTIMENT_ANALYST, "...\nSentiment band: greed", {"sentiment_band": "greed"}),
        _turn(FUNDAMENTAL_ANALYST, "...\nProtocol health: growing", {"protocol_health": "growing"}),
        _turn(RISK_MANAGER, "...\nRisk band: acceptable", {"risk_band": "acceptable"}),
        _turn(STRATEGIST, "...\nStrategic intent: open_long", {"strategic_intent": "open_long"}),
        _turn(
            BULL_BEAR_DEBATER,
            "...\nDecisive question: any catalysts?",
            {"decisive_question": "any catalysts?"},
        ),
        _turn(
            COORDINATOR,
            '```json\n{"verdict":"act","confidence":0.7,"key_drivers":["x"],"dissent_count":0,"blocker_questions":[]}\n```\nFinal verdict: act',
            {"verdict": "act"},
        ),
    ]


# ---- _extract_dissent_entries ----------------------------------------------


def test_unanimous_act_returns_empty():
    """No voice opposes or abstains → []."""
    out = _extract_dissent_entries(_unanimous_act_turns(), "act")
    assert out == []


def test_two_opposes_on_act_verdict():
    """Two primaries pointing 'pass' against an 'act' verdict surface as oppose entries."""
    turns = [
        _turn(TECHNICAL_ANALYST, "x\nTrend verdict: bullish", {"trend_verdict": "bullish"}),
        # Sentiment says 'fear' = points to 'pass'
        _turn(SENTIMENT_ANALYST, "x\nSentiment band: fear", {"sentiment_band": "fear"}),
        # Fundamental 'growing' = points to 'act' (aligns)
        _turn(FUNDAMENTAL_ANALYST, "x\nProtocol health: growing", {"protocol_health": "growing"}),
        # Risk 'unacceptable' = points to 'pass'
        _turn(RISK_MANAGER, "x\nRisk band: unacceptable", {"risk_band": "unacceptable"}),
    ]
    out = _extract_dissent_entries(turns, "act")
    assert len(out) == 2
    voices = {e.voice for e in out}
    assert voices == {SENTIMENT_ANALYST, RISK_MANAGER}
    by_voice = {e.voice: e for e in out}
    assert by_voice[SENTIMENT_ANALYST].stance == "oppose"
    assert by_voice[SENTIMENT_ANALYST].verbatim == "fear"
    assert by_voice[SENTIMENT_ANALYST].on_topic == "sentiment band"
    assert by_voice[RISK_MANAGER].stance == "oppose"
    assert by_voice[RISK_MANAGER].verbatim == "unacceptable"
    assert by_voice[RISK_MANAGER].on_topic == "risk band"


def test_oppose_on_pass_verdict():
    """A 'bullish' technical against a 'pass' verdict surfaces as oppose."""
    turns = [
        _turn(TECHNICAL_ANALYST, "x\nTrend verdict: bullish", {"trend_verdict": "bullish"}),
        _turn(SENTIMENT_ANALYST, "x\nSentiment band: fear", {"sentiment_band": "fear"}),
    ]
    out = _extract_dissent_entries(turns, "pass")
    assert len(out) == 1
    assert out[0].voice == TECHNICAL_ANALYST
    assert out[0].stance == "oppose"
    assert out[0].verbatim == "bullish"


def test_abstain_on_directional_verdict():
    """technical='mixed' + fundamental='stable' surface as abstain entries on 'act'."""
    turns = [
        _turn(TECHNICAL_ANALYST, "x\nTrend verdict: mixed", {"trend_verdict": "mixed"}),
        _turn(SENTIMENT_ANALYST, "x\nSentiment band: greed", {"sentiment_band": "greed"}),
        _turn(FUNDAMENTAL_ANALYST, "x\nProtocol health: stable", {"protocol_health": "stable"}),
        _turn(RISK_MANAGER, "x\nRisk band: acceptable", {"risk_band": "acceptable"}),
    ]
    out = _extract_dissent_entries(turns, "act")
    assert len(out) == 2
    voices = {e.voice: e for e in out}
    assert voices[TECHNICAL_ANALYST].stance == "abstain"
    assert voices[TECHNICAL_ANALYST].verbatim == "mixed"
    assert voices[FUNDAMENTAL_ANALYST].stance == "abstain"
    assert voices[FUNDAMENTAL_ANALYST].verbatim == "stable"


def test_defer_verdict_surfaces_abstains():
    """A 'defer' verdict has no clean opposite; abstain arm becomes the dominant signal."""
    turns = [
        _turn(TECHNICAL_ANALYST, "x\nTrend verdict: mixed", {"trend_verdict": "mixed"}),
        _turn(FUNDAMENTAL_ANALYST, "x\nProtocol health: stable", {"protocol_health": "stable"}),
        # Risk 'unacceptable' on a defer — has no "opposite" defined, so should NOT
        # appear as oppose; also doesn't satisfy abstain tokens, so doesn't appear.
        _turn(RISK_MANAGER, "x\nRisk band: unacceptable", {"risk_band": "unacceptable"}),
    ]
    out = _extract_dissent_entries(turns, "defer")
    voices = {e.voice for e in out}
    # Only the two abstainers should surface.
    assert voices == {TECHNICAL_ANALYST, FUNDAMENTAL_ANALYST}
    assert all(e.stance == "abstain" for e in out)


def test_strategist_and_debater_never_in_dissent():
    """Strategist + bull_bear_debater have no directional token; never surface."""
    turns = [
        _turn(TECHNICAL_ANALYST, "x\nTrend verdict: bullish", {"trend_verdict": "bullish"}),
        _turn(STRATEGIST, "x\nStrategic intent: observe", {"strategic_intent": "observe"}),
        _turn(
            BULL_BEAR_DEBATER,
            "x\nDecisive question: priced in?",
            {"decisive_question": "priced in?"},
        ),
    ]
    out = _extract_dissent_entries(turns, "pass")
    # Only technical_analyst's bullish-vs-pass should surface.
    assert len(out) == 1
    assert out[0].voice == TECHNICAL_ANALYST
    # Strategist + debater are never in the result regardless of verdict.
    assert all(e.voice not in (STRATEGIST, BULL_BEAR_DEBATER, COORDINATOR) for e in out)


def test_verbatim_is_closing_line_token_not_prose():
    """The verbatim MUST be the parsed_verdict value, not the full content body."""
    long_body = "Lots of prose. The chart shows X. " * 30  # >300 chars
    turns = [
        _turn(
            TECHNICAL_ANALYST,
            long_body + "\nTrend verdict: bearish",
            {"trend_verdict": "bearish"},
        ),
    ]
    out = _extract_dissent_entries(turns, "act")
    assert len(out) == 1
    assert out[0].verbatim == "bearish"  # not the long body
    assert len(out[0].verbatim) <= 300


def test_oppose_and_abstain_dont_double_count_one_voice():
    """If a voice could surface in both arms, oppose wins; not both."""
    # technical='mixed' is an abstain token. On an 'act' verdict it has no
    # 'oppose' directional. So it should appear as abstain — never twice.
    turns = [
        _turn(TECHNICAL_ANALYST, "x\nTrend verdict: mixed", {"trend_verdict": "mixed"}),
    ]
    out = _extract_dissent_entries(turns, "act")
    assert len(out) == 1
    assert out[0].stance == "abstain"


def test_max_entries_bounds_envelope():
    """Cap at max_entries — protects the envelope size."""
    # 4 abstains is the theoretical max for primary analysts; cap at 2.
    turns = [
        _turn(TECHNICAL_ANALYST, "x\nTrend verdict: mixed", {"trend_verdict": "mixed"}),
        _turn(FUNDAMENTAL_ANALYST, "x\nProtocol health: stable", {"protocol_health": "stable"}),
    ]
    out = _extract_dissent_entries(turns, "act", max_entries=1)
    assert len(out) == 1


def test_malformed_parsed_verdict_skipped_not_guessed():
    """Empty or missing parsed_verdict on a primary → skip; do not synthesize."""
    turns = [
        _turn(TECHNICAL_ANALYST, "no closing line", None),
        _turn(SENTIMENT_ANALYST, "x\nSentiment band: fear", {"sentiment_band": "fear"}),
    ]
    out = _extract_dissent_entries(turns, "act")
    # Only the well-formed sentiment turn surfaces.
    assert len(out) == 1
    assert out[0].voice == SENTIMENT_ANALYST


# ---- _build_verdict_from_coordinator integration ---------------------------


def test_verdict_envelope_carries_dissent_field():
    """End-to-end: the assembled TradePanelVerdict has `dissent` populated."""
    turns = [
        _turn(TECHNICAL_ANALYST, "x\nTrend verdict: bearish", {"trend_verdict": "bearish"}),
        _turn(SENTIMENT_ANALYST, "x\nSentiment band: fear", {"sentiment_band": "fear"}),
        _turn(FUNDAMENTAL_ANALYST, "x\nProtocol health: growing", {"protocol_health": "growing"}),
        _turn(RISK_MANAGER, "x\nRisk band: acceptable", {"risk_band": "acceptable"}),
        _turn(STRATEGIST, "x\nStrategic intent: open_long", {"strategic_intent": "open_long"}),
        _turn(
            BULL_BEAR_DEBATER,
            "x\nDecisive question: priced in?",
            {"decisive_question": "priced in?"},
        ),
        _turn(
            COORDINATOR,
            '```json\n{"verdict":"act","confidence":0.65,"key_drivers":["x"],"dissent_count":2,"blocker_questions":[]}\n```\nFinal verdict: act',
            {"verdict": "act"},
        ),
    ]
    verdict = _build_verdict_from_coordinator(turns)
    assert verdict.verdict == "act"
    # Two opposers: technical (bearish) + sentiment (fear). Fundamental/risk align.
    assert len(verdict.dissent) == 2
    voices = {e.voice for e in verdict.dissent}
    assert voices == {TECHNICAL_ANALYST, SENTIMENT_ANALYST}
    # dissent_count surface still works — backward compat.
    assert verdict.dissent_count >= 2


def test_unanimous_envelope_has_empty_dissent_list():
    """No voice opposes or abstains → envelope.dissent == [] (consensus signal)."""
    verdict = _build_verdict_from_coordinator(_unanimous_act_turns())
    assert verdict.verdict == "act"
    assert verdict.dissent == []
    assert verdict.dissent_count == 0


def test_missing_coordinator_still_surfaces_abstains():
    """No coordinator turn (panel crashed late) — abstain entries still emit."""
    turns = [
        _turn(TECHNICAL_ANALYST, "x\nTrend verdict: mixed", {"trend_verdict": "mixed"}),
        _turn(FUNDAMENTAL_ANALYST, "x\nProtocol health: stable", {"protocol_health": "stable"}),
        # no coordinator turn
    ]
    verdict = _build_verdict_from_coordinator(turns)
    assert verdict.verdict == "defer"
    assert len(verdict.dissent) == 2
    assert all(e.stance == "abstain" for e in verdict.dissent)


def test_dissent_entry_shape_is_serializable():
    """DissentEntry round-trips through model_dump cleanly (wire-shape check)."""
    e = DissentEntry(
        voice=TECHNICAL_ANALYST,
        stance="oppose",
        verbatim="bearish",
        on_topic="trend read",
    )
    dumped = e.model_dump()
    assert dumped == {
        "voice": TECHNICAL_ANALYST,
        "stance": "oppose",
        "verbatim": "bearish",
        "on_topic": "trend read",
    }
