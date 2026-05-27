"""Tests for memory_voice v2 — Sprint 6 Phase C.

Pure-Python deterministic voice; no LLM mocks needed. Lean fixtures per
`feedback_lighter_tests`: tiny synthetic market_state dicts + a fake
MemoryReader.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from voices.memory_voice_v2 import (  # noqa: E402
    COHORT_BEARISH_CONFIDENCE,
    COHORT_BULLISH_CONFIDENCE,
    EXHAUSTION_BEARISH_CONFIDENCE,
    MINUS_EV_COHORT,
    MemoryVoiceV2,
    PLUS_EV_COHORT,
    would_decline_for_backtest,
)


class FakeMemory:
    """Minimal MemoryReader for tests — returns canned recent rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def recent(
        self,
        event_filter: str | tuple[str, ...] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if event_filter is None:
            return self._rows[:limit]
        if isinstance(event_filter, str):
            event_filter = (event_filter,)
        return [r for r in self._rows if r.get("event") in event_filter][:limit]

    def outcomes_for(self, decision_id: str) -> list[dict[str, Any]]:
        return []


def _state(symbol: str, *, rsi: float | None = 50.0, mfi: float | None = 50.0) -> dict[str, Any]:
    return {
        "instrument": symbol,
        "indicators": {"rsi": rsi, "mfi": mfi},
    }


def _close_row(symbol: str, pnl_pct: float) -> dict[str, Any]:
    return {
        "event": "position_close",
        "payload": {"symbol": symbol, "pnl_pct": pnl_pct, "exit_reason": "take_profit"},
    }


def _grade(voice: MemoryVoiceV2, state: dict[str, Any], memory: FakeMemory):
    return asyncio.run(voice.grade(state, memory))


# ── cohort rules ────────────────────────────────────────────────────────


def test_chronic_minus_ev_cohort_votes_bearish() -> None:
    voice = MemoryVoiceV2()
    out = _grade(voice, _state("BCH"), FakeMemory())
    assert out.verdict == "bearish"
    assert out.confidence == COHORT_BEARISH_CONFIDENCE
    assert "chronic_minus_ev_cohort" in out.reasoning


def test_chronic_plus_ev_cohort_votes_bullish() -> None:
    voice = MemoryVoiceV2()
    out = _grade(voice, _state("RENDER"), FakeMemory())
    assert out.verdict == "bullish"
    assert out.confidence == COHORT_BULLISH_CONFIDENCE
    assert "chronic_plus_ev_cohort" in out.reasoning


def test_minus_ev_overrides_realized_positive() -> None:
    """Chronic -EV cohort vote wins even when this symbol's recent closes were wins."""
    voice = MemoryVoiceV2()
    mem = FakeMemory([_close_row("BCH", 2.0)] * 5)  # 5 recent +2% wins
    out = _grade(voice, _state("BCH"), mem)
    assert out.verdict == "bearish"  # chronic cohort wins
    assert "chronic_minus_ev" in out.reasoning


def test_neutral_symbol_no_realized_returns_abstain() -> None:
    """Symbol not in any cohort + no realized history + no exhaustion → abstain."""
    voice = MemoryVoiceV2()
    out = _grade(voice, _state("UNKNOWNCOIN"), FakeMemory())
    assert out.verdict == "abstain"
    assert out.confidence == 0.0


# ── indicator-exhaustion rule ───────────────────────────────────────────


def test_indicator_exhaustion_fires_bearish_on_autopsy_pyth_pattern() -> None:
    """Reproduce Phase A autopsy trade #14 (PYTH, scratch outcome)."""
    voice = MemoryVoiceV2()
    out = _grade(voice, _state("UNKNOWNCOIN", rsi=76.0, mfi=99.3), FakeMemory())
    assert out.verdict == "bearish"
    assert out.confidence == EXHAUSTION_BEARISH_CONFIDENCE
    assert "indicator_exhaustion" in out.reasoning


def test_exhaustion_overrides_plus_ev_cohort() -> None:
    """Even on a +EV symbol, extreme exhaustion votes bearish."""
    voice = MemoryVoiceV2()
    out = _grade(voice, _state("RENDER", rsi=85.0, mfi=99.0), FakeMemory())
    assert out.verdict == "bearish"  # exhaustion wins; it's higher confidence
    assert out.confidence == EXHAUSTION_BEARISH_CONFIDENCE


def test_rsi_high_alone_does_not_trigger_exhaustion() -> None:
    """WIF #12 pattern: RSI=82.4, MFI=63 was a WIN — no exhaustion fire."""
    voice = MemoryVoiceV2()
    out = _grade(voice, _state("UNKNOWNCOIN", rsi=82.4, mfi=63.0), FakeMemory())
    assert out.verdict == "abstain"  # both needed


def test_mfi_high_alone_does_not_trigger_exhaustion() -> None:
    """WIF #4 pattern: RSI=70.3, MFI=83.2 was a WIN — no exhaustion fire."""
    voice = MemoryVoiceV2()
    out = _grade(voice, _state("UNKNOWNCOIN", rsi=70.3, mfi=83.2), FakeMemory())
    assert out.verdict == "abstain"  # MFI 83 < 90 threshold


def test_none_indicators_skip_exhaustion_check() -> None:
    voice = MemoryVoiceV2()
    out = _grade(voice, _state("UNKNOWNCOIN", rsi=None, mfi=None), FakeMemory())
    assert out.verdict == "abstain"


# ── realized-outcomes rule ──────────────────────────────────────────────


def test_realized_outcomes_positive_votes_bullish_for_neutral_symbol() -> None:
    """3+ recent +1% closes on a neutral-cohort symbol → bullish."""
    voice = MemoryVoiceV2()
    mem = FakeMemory([_close_row("APT", 1.0)] * 4)
    out = _grade(voice, _state("APT"), mem)
    assert out.verdict == "bullish"
    assert "realized_outcomes_positive" in out.reasoning


def test_realized_outcomes_negative_votes_bearish_for_neutral_symbol() -> None:
    voice = MemoryVoiceV2()
    mem = FakeMemory([_close_row("APT", -1.5)] * 4)
    out = _grade(voice, _state("APT"), mem)
    assert out.verdict == "bearish"
    assert "realized_outcomes_negative" in out.reasoning


def test_fewer_than_3_realized_closes_abstains_on_realized() -> None:
    """Cold-start floor — 2 closes is not enough."""
    voice = MemoryVoiceV2()
    mem = FakeMemory([_close_row("APT", 1.0)] * 2)
    out = _grade(voice, _state("APT"), mem)
    assert out.verdict == "abstain"  # no cohort + insufficient realized


def test_realized_closes_filter_by_symbol() -> None:
    """Recent closes on OTHER symbols don't influence this symbol's vote."""
    voice = MemoryVoiceV2()
    mem = FakeMemory(
        [
            _close_row("WIF", 2.0),
            _close_row("WIF", 2.0),
            _close_row("WIF", 2.0),
            _close_row("APT", -0.1),  # only 1 APT close
        ]
    )
    out = _grade(voice, _state("APT"), mem)
    assert out.verdict == "abstain"


def test_realized_within_dust_band_abstains() -> None:
    """Weighted mean within ±0.5% (the dust band) → no signal."""
    voice = MemoryVoiceV2()
    mem = FakeMemory([_close_row("APT", 0.2), _close_row("APT", -0.1), _close_row("APT", 0.0)])
    out = _grade(voice, _state("APT"), mem)
    assert out.verdict == "abstain"


# ── output shape + safety ───────────────────────────────────────────────


def test_voice_name_matches_v1_for_wire_compatibility() -> None:
    """v2 must reuse 'memory_voice' so the panel/dashboard plumbing is unchanged."""
    assert MemoryVoiceV2.voice_name == "memory_voice"


def test_zero_llm_cost_always() -> None:
    voice = MemoryVoiceV2()
    out = _grade(voice, _state("BCH"), FakeMemory())
    assert out.cost_usd == 0.0
    assert out.raw_response == ""


def test_memory_exception_falls_through_to_abstain() -> None:
    """If memory.recent raises, the realized-rule path just skips; no crash."""

    class BrokenMemory:
        def recent(self, **kwargs):
            raise RuntimeError("disk full")

        def outcomes_for(self, decision_id):
            return []

    voice = MemoryVoiceV2()
    out = _grade(voice, _state("UNKNOWNCOIN"), BrokenMemory())
    # No cohort + no realized signal (exception) + no exhaustion → abstain
    assert out.verdict == "abstain"


def test_cohorts_are_disjoint() -> None:
    """Sanity: a symbol cannot be in BOTH cohorts (would be ambiguous)."""
    assert PLUS_EV_COHORT.isdisjoint(MINUS_EV_COHORT)


def test_cohort_sizes_match_phase_b_doc() -> None:
    """Regression: cohort lists must stay at 10 each per Phase B PR #54."""
    assert len(PLUS_EV_COHORT) == 10
    assert len(MINUS_EV_COHORT) == 10


@pytest.mark.parametrize(
    "symbol,expected_verdict",
    [
        ("RENDER", "bullish"),
        ("ZEC", "bullish"),
        ("BCH", "bearish"),
        ("EIGEN", "bearish"),
        ("BTC", "bearish"),
        ("UNKNOWNCOIN", "abstain"),
    ],
)
def test_known_cohort_membership(symbol: str, expected_verdict: str) -> None:
    voice = MemoryVoiceV2()
    out = _grade(voice, _state(symbol), FakeMemory())
    assert out.verdict == expected_verdict


# ── would_decline_for_backtest sync wrapper ─────────────────────────────


def test_would_decline_chronic_minus_ev_cohort() -> None:
    assert would_decline_for_backtest("BCH") is True
    assert would_decline_for_backtest("EIGEN") is True
    assert would_decline_for_backtest("BTC") is True


def test_would_decline_plus_ev_cohort_returns_false() -> None:
    """Plus-EV cohort gets a bullish vote, not bearish — should NOT decline."""
    assert would_decline_for_backtest("RENDER") is False
    assert would_decline_for_backtest("ZEC") is False


def test_would_decline_indicator_exhaustion() -> None:
    assert would_decline_for_backtest("UNKNOWN", rsi=76.0, mfi=99.3) is True
    assert would_decline_for_backtest("UNKNOWN", rsi=80.0, mfi=95.0) is True


def test_would_decline_neutral_indicators_returns_false() -> None:
    assert would_decline_for_backtest("UNKNOWN", rsi=50.0, mfi=50.0) is False


def test_would_decline_minus_ev_overrides_indicators() -> None:
    """Even neutral indicators on a -EV cohort symbol → decline."""
    assert would_decline_for_backtest("BCH", rsi=50.0, mfi=50.0) is True


def test_would_decline_handles_suffixed_symbol() -> None:
    """The function should strip -USDC suffix like the voice does."""
    assert would_decline_for_backtest("BCH-USDC") is True
    assert would_decline_for_backtest("RENDER-USDC") is False


def test_would_decline_handles_none_indicators() -> None:
    """No RSI/MFI data — only cohort can fire."""
    assert would_decline_for_backtest("UNKNOWN") is False
    assert would_decline_for_backtest("UNKNOWN", rsi=None, mfi=None) is False
    assert would_decline_for_backtest("BCH", rsi=None, mfi=None) is True
