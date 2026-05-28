"""regime_analyst — chop-vs-trend classifier (S40 Track B3, NEW voice).

The axis the chart_analyst can't express. Tonight's backtest proved breakout
entries are -EV in CHOP and only work in TREND — but no voice models *whether
the regime even permits momentum trading*. regime_analyst fills that gap.

Deterministic-first (like risk_voice — no LLM): reads the latest indicators
(ADX = trend strength, Bollinger band-width = volatility expansion) from the
candles the bot already passes in ``market_state["candles"]`` and emits:

  - verdict='bullish'  → TREND (adx >= 25): momentum trading is permitted.
  - verdict='bearish'  → CHOP  (adx <= 18): momentum is -EV here; the
                          coordinator should raise the bar or defer.
  - verdict='neutral'  → TRANSITIONAL (18 < adx < 25): hold/uncertain.
  - verdict='abstain'  → not enough candle history to classify.

Confidence is ADX-derived (how far past the threshold). The coordinator (B6)
reads this as a GATE MODULATOR, not a veto: in chop it raises chart's required
floor / routes to defer_grid; in trend it leaves the panel as-is.

Pattern D justification (why this isn't redundant with chart_analyst): chart
says *direction* (is this setup bullish); regime says *whether direction-
trading applies at all*. A bullish chart read in a chop regime is exactly the
fakeout the backtest showed loses. Different axis, real separation.
"""

from __future__ import annotations

import time
from typing import Any

import indicators
from voices.base import MemoryReader, VoiceOpinion

# Thresholds mirror the backtest's regime segmentation (REGIME_ADX_CHOP/TREND).
_ADX_TREND = 25.0  # adx >= this ⇒ trend, momentum permitted
_ADX_CHOP = 18.0   # adx <= this ⇒ chop, momentum -EV
_MIN_BARS = 30     # need enough candles for a meaningful ADX(14)


class RegimeAnalystVoice:
    """Deterministic chop/trend classifier. No LLM call."""

    voice_name: str = "regime_analyst"

    def __init__(self, client: Any = None) -> None:
        # client accepted for a uniform constructor signature with the LLM
        # voices (bootstrap passes it); unused — this voice is deterministic.
        self._client = client

    async def grade(
        self,
        market_state: dict[str, Any],
        memory: MemoryReader,
    ) -> VoiceOpinion:
        started = time.monotonic()
        candles = market_state.get("candles") or []

        if len(candles) < _MIN_BARS:
            return self._opinion(
                "abstain", 0.0,
                f"insufficient_history:{len(candles)}bars",
                [], started,
            )

        snap = indicators.compute_latest(candles)
        adx = snap.get("adx")
        bb_width = snap.get("bb_width")
        if adx is None:
            return self._opinion(
                "abstain", 0.0, "adx_unavailable", [], started,
            )

        obs = [
            f"adx={adx:.1f}",
            f"bb_width={bb_width:.2f}%" if bb_width is not None else "bb_width=n/a",
        ]

        if adx >= _ADX_TREND:
            # Trend strength scales confidence: adx 25→0.55, 40→~0.85, cap 0.9.
            conf = min(0.9, 0.55 + (adx - _ADX_TREND) / 50.0)
            return self._opinion(
                "bullish", conf,
                f"TREND adx={adx:.1f}>= {_ADX_TREND:.0f} — momentum permitted",
                obs, started,
            )
        if adx <= _ADX_CHOP:
            # Deeper chop = more confident it's -EV for momentum.
            conf = min(0.85, 0.55 + (_ADX_CHOP - adx) / 40.0)
            return self._opinion(
                "bearish", conf,
                f"CHOP adx={adx:.1f}<= {_ADX_CHOP:.0f} — momentum -EV here",
                obs, started,
            )
        # Dead-zone — transitional.
        return self._opinion(
            "neutral", 0.4,
            f"TRANSITIONAL adx={adx:.1f} in ({_ADX_CHOP:.0f},{_ADX_TREND:.0f})",
            obs, started,
        )

    def _opinion(
        self,
        verdict: str,
        confidence: float,
        reasoning: str,
        observations: list[str],
        started: float,
    ) -> VoiceOpinion:
        return VoiceOpinion(
            voice_name=self.voice_name,
            verdict=verdict,  # type: ignore[arg-type]
            confidence=confidence,
            reasoning=reasoning[:400],
            observations=observations,
            raw_response="",  # deterministic — no model output
            elapsed_ms=int((time.monotonic() - started) * 1000),
            cost_usd=None,
        )


__all__ = ["RegimeAnalystVoice"]
