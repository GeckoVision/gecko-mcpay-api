"""regime_analyst — chop/trend/direction classifier (S40 Track B3, direction fix S41).

The axis the chart_analyst can't express. Backtest proved breakout entries
are -EV in CHOP and only work in TREND — but no voice modelled *whether
the regime even permits momentum trading*. regime_analyst fills that gap.

Deterministic-first (like risk_voice — no LLM): reads the latest indicators
(ADX = trend strength, +DI/−DI = direction) from the candles the bot
already passes in ``market_state["candles"]`` and emits:

  - verdict='bullish'  → UPTREND  (adx >= 25 AND +DI > −DI):
                          momentum trading is permitted; a genuine uptrend.
  - verdict='bearish'  → CHOP or DOWNTREND:
                            adx <= 18 (chop: momentum -EV), OR
                            adx >= 25 AND −DI > +DI (downtrend: longs blocked).
  - verdict='neutral'  → TRANSITIONAL (18 < adx < 25): direction uncertain.
  - verdict='abstain'  → not enough candle history to classify.

Confidence is ADX-derived (how far past the threshold). The coordinator (B6)
reads this as a GATE MODULATOR: regime 'bearish' (chop OR downtrend) raises
chart's required floor / routes to defer; trend leaves the panel as-is.

S41 direction fix:
  Before this fix ADX >= 25 unconditionally → 'bullish', meaning a strong
  downtrend was mis-labelled "momentum permitted". The +DI/−DI directional
  components are now surfaced by indicators.compute_latest() and used here
  to distinguish up- from down-trend. Both chop and downtrend correctly
  raise the coordinator floor and block longs.

Pattern D justification (why this isn't redundant with chart_analyst):
chart says *direction* (is this setup bullish); regime says *whether
direction-trading applies at all*. A bullish chart read in a chop regime
is exactly the fakeout the backtest showed loses. Different axis, real
separation.
"""

from __future__ import annotations

import time
from typing import Any

import indicators
from voices.base import MemoryReader, VoiceOpinion

# Thresholds mirror the backtest's regime segmentation (REGIME_ADX_CHOP/TREND).
_ADX_TREND = 25.0  # adx >= this ⇒ meaningful trend (direction decides up/down)
_ADX_CHOP = 18.0   # adx <= this ⇒ chop, momentum -EV regardless of direction
# 2026-05-30: lowered 30→25. Bot's get_candles(token, TIMEFRAME, limit=30)
# returns 29 bars in practice (current-bar exclusion). With _MIN_BARS=30 the
# voice abstained 351/351 times in the recent 10h window. ADX(14) is stable
# from ~22 bars onward; 25 keeps a small safety buffer while letting the
# voice actually grade live snapshots. See diagnostic 2026-05-30.
_MIN_BARS = 25     # need enough candles for a meaningful ADX(14)


class RegimeAnalystVoice:
    """Deterministic chop/trend/direction classifier. No LLM call."""

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
        adx_v = snap.get("adx")
        plus_di = snap.get("plus_di")
        minus_di = snap.get("minus_di")
        bb_width = snap.get("bb_width")

        if adx_v is None:
            return self._opinion(
                "abstain", 0.0, "adx_unavailable", [], started,
            )

        chop_v = snap.get("chop")
        # bb_width label: expansion >2% signals volatility opening; compression
        # <1% signals coiling (breakout potential or slow bleed — context-dependent).
        if bb_width is not None:
            if bb_width > 2.0:
                bb_label = f"bb_width {bb_width:.2f}% — expansion"
            elif bb_width < 1.0:
                bb_label = f"bb_width {bb_width:.2f}% — compression"
            else:
                bb_label = f"bb_width {bb_width:.2f}%"
        else:
            bb_label = "bb_width=n/a"

        # chop label for reasoning context (informational only — no gate)
        if chop_v is not None:
            if chop_v > 61.8:
                chop_label = f"chop={chop_v:.1f} (max chop)"
            elif chop_v < 38.2:
                chop_label = f"chop={chop_v:.1f} (trending)"
            else:
                chop_label = f"chop={chop_v:.1f}"
        else:
            chop_label = "chop=n/a"

        obs = [
            f"adx={adx_v:.1f}",
            f"+DI={plus_di:.1f}" if plus_di is not None else "+DI=n/a",
            f"-DI={minus_di:.1f}" if minus_di is not None else "-DI=n/a",
            bb_label,
            chop_label,
        ]

        if adx_v >= _ADX_TREND:
            # Strong trend — direction determines bull vs bear verdict.
            # Confidence scales with ADX distance past the threshold.
            conf = min(0.9, 0.55 + (adx_v - _ADX_TREND) / 50.0)
            if plus_di is not None and minus_di is not None:
                if plus_di > minus_di:
                    return self._opinion(
                        "bullish", conf,
                        f"uptrend: ADX {adx_v:.1f} +DI>{'-'}DI ({plus_di:.1f}>{minus_di:.1f}) — momentum permitted; {bb_label}; {chop_label}",
                        obs, started,
                    )
                else:
                    # Downtrend: strong ADX but sellers are in control.
                    # Block longs — same coordinator path as chop (bearish raises floor).
                    return self._opinion(
                        "bearish", conf,
                        f"downtrend: ADX {adx_v:.1f} {'-'}DI>+DI ({minus_di:.1f}>{plus_di:.1f}) — longs blocked; {bb_label}; {chop_label}",
                        obs, started,
                    )
            else:
                # DI unavailable but ADX strong — treat as uptrend (conservative
                # assumption: presence of trend without direction info).
                return self._opinion(
                    "bullish", conf,
                    f"TREND adx={adx_v:.1f}>={_ADX_TREND:.0f} (DI n/a) — momentum permitted; {bb_label}; {chop_label}",
                    obs, started,
                )

        if adx_v <= _ADX_CHOP:
            # Chop: weak trend regardless of direction — momentum is -EV.
            conf = min(0.85, 0.55 + (_ADX_CHOP - adx_v) / 40.0)
            return self._opinion(
                "bearish", conf,
                f"chop: ADX {adx_v:.1f}<={_ADX_CHOP:.0f} — momentum -EV here; {bb_label}; {chop_label}",
                obs, started,
            )

        # Dead-zone — transitional (18 < adx < 25).
        return self._opinion(
            "neutral", 0.4,
            f"transitional: ADX {adx_v:.1f} in ({_ADX_CHOP:.0f},{_ADX_TREND:.0f}); {bb_label}; {chop_label}",
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
