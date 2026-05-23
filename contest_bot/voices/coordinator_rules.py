"""Local-panel coordinator rules. Pinned in code, NEVER in a prompt.

Per ``feedback-prompt-iteration-plateau``: coordinator verdict logic
lives in CODE because gpt-4o-mini rounds toward caution on any
defer-related instruction (4 iterations observed in S24:
1.0 -> 0.20 -> 0.50 -> 0.90).

The literal rule set, transcribed from spec §4 + wave-2b multi-TF extension:

  0. [Wave-2b] 1h regime pre-check: if regime_1h is TREND-DOWN → raise
     chart floor to _CHART_1H_DOWNTREND_FLOOR (0.92); if CHOP, use the
     existing chop-floor logic (Rule 3 below). This modulator runs BEFORE
     the voice rules.
  1. risk.verdict == "bearish" AND risk.confidence >= 0.8
     -> ("decline", "risk_veto")
  2. chart.verdict != "bullish" OR chart.confidence < 0.6
     -> ("decline", "chart_below_threshold")
  3. memory.verdict == "bearish" AND memory.confidence >= 0.6
     -> ("decline", "memory_contradicts")
  4. else -> ("act", "all_voices_aligned")

Voice lookup is by ``opinion.voice_name`` — defensive against
order-of-opinions changes.

Defensive defaults:

* A missing chart_analyst voice falls straight through to
  ``("decline", "chart_voice_missing")`` because chart is the only
  positive-signal source.
* A missing risk_voice or memory_voice is treated as an abstain — the
  rules that key on those voices simply do not fire to ``decline``;
  the chain falls through to the next rule.
* ``regime_1h`` is optional (None = unknown = don't raise the bar).
  Fail-open: a missing 1h regime uses the existing 5m regime path.

See ``docs/strategy/lab-validated/2026-05-20-local-panel-voices-spec.md``
§4 and wave-2b design notes.
"""

from __future__ import annotations

import os
from typing import Literal

from voices.base import VoiceOpinion

LocalAction = Literal["act", "decline"]

# Per-voice confidence thresholds (spec §4.3). The chart 0.6 mirrors
# the PRD's DEFAULT_GATE_MIN_CONFIDENCE from gecko_wrap.py:58 for
# symmetry across substrates. The memory 0.6 is set by the spec; risk
# 0.8 is the hard-veto bar.
_RISK_VETO_CONFIDENCE = 0.8
_CHART_MIN_CONFIDENCE = float(os.environ.get("GECKO_CHART_MIN_CONF", "0.85"))  # env-overridable (2026-05-23 overnight tuning). Default 0.85: only cleanest momentum setups pass. Override via GECKO_CHART_MIN_CONF for paper experiments.
_MEMORY_CONTRADICT_CONFIDENCE = 0.6
# B6 (S40) — 5m regime gate-modulator. The backtest proved breakout is -EV in
# chop. So in a confirmed CHOP regime we RAISE the chart floor (only the
# very cleanest setups pass); in TREND/neutral/abstain we use the normal
# floor. This is a MODULATOR, not a veto — it never bans a symbol, it makes
# us selective in chop. (DRIFT in a trend trades at 0.85; DRIFT in chop must
# clear 0.92 — selective, not "never".)
_CHART_CHOP_FLOOR = float(os.environ.get("GECKO_CHART_CHOP_FLOOR", "0.92"))  # chart confidence required to act in a confirmed-chop regime (env-overridable)
_REGIME_CHOP_CONFIDENCE = 0.6  # regime must be this confident it's chop to raise the bar

# Wave-2b (S42) — multi-timeframe 1h regime modulator.
# If the 1h tape is CHOP or TREND-DOWN, raise the chart floor to this value
# (same as the 5m chop floor). TREND-DOWN means the higher-TF tape is
# distributing; taking 5m longs into a TREND-DOWN 1h is the falling-knife
# scenario the strategist diagnosed. This is still a MODULATOR not a hard ban:
# a very high-conviction 5m breakout (chart >= 0.92) can still fire in a
# 1h chop/downtrend — we just require much stronger confirmation.
_CHART_1H_ADVERSE_FLOOR = float(os.environ.get("GECKO_CHART_ADVERSE_FLOOR", "0.92"))  # chart confidence required when 1h is CHOP or TREND-DOWN (env-overridable)

# Synthetic abstain we substitute when a named voice is missing from
# the opinions list — keeps the rule chain branch-free.
_ABSTAIN_PLACEHOLDER = VoiceOpinion(
    voice_name="__missing__",
    verdict="abstain",
    confidence=0.0,
    reasoning="missing_voice_placeholder",
    observations=[],
    raw_response="",
    elapsed_ms=0,
    cost_usd=None,
)


def coordinator(
    opinions: list[VoiceOpinion],
    regime_1h: str | None = None,
) -> tuple[LocalAction, str | None]:
    """Decide ``act`` / ``decline`` from the voice opinions + optional 1h regime.

    Pure Python, no prompt. See module docstring for the exact rule list.

    Args:
        opinions:   Voice opinions from the local panel.
        regime_1h:  Optional 1h regime string from ``indicators.compute_regime_1h``.
                    Values: "TREND-UP" | "TREND-DOWN" | "CHOP" | None.
                    None means unknown — fail-open (don't raise the bar).
    """
    by_name = {o.voice_name: o for o in opinions}
    chart = by_name.get("chart_analyst")
    memory = by_name.get("memory_voice", _ABSTAIN_PLACEHOLDER)
    risk = by_name.get("risk_voice", _ABSTAIN_PLACEHOLDER)
    regime = by_name.get("regime_analyst", _ABSTAIN_PLACEHOLDER)

    # Defensive special-case: chart is the only positive-signal source.
    # Without it we cannot ever say 'act'. Decline early so downstream
    # rules don't accidentally fall through to act-mode.
    if chart is None:
        return ("decline", "chart_voice_missing")

    # Rule 1 — risk hard veto. ALWAYS first.
    if risk.verdict == "bearish" and risk.confidence >= _RISK_VETO_CONFIDENCE:
        return ("decline", "risk_veto")

    # Rule 2 — chart must be bullish at all.
    if chart.verdict != "bullish":
        return ("decline", "chart_below_threshold")

    # Rule 3a (Wave-2b) — multi-timeframe 1h modulator. If the 1h tape is
    # TREND-DOWN or CHOP, raise the chart floor to _CHART_1H_ADVERSE_FLOOR.
    # TREND-DOWN: the higher-TF tape is distributing — 5m longs face structural
    # headwind. CHOP: 1h context confirms 5m indecision is regime-wide.
    # Fail-open on None (unknown 1h state doesn't tighten the bar).
    in_1h_adverse = regime_1h in ("TREND-DOWN", "CHOP")

    # Rule 3b (B6) — 5m regime-modulated floor (existing logic).
    # regime_analyst "bearish" covers both chop and downtrend on 5m.
    in_5m_chop = regime.verdict == "bearish" and regime.confidence >= _REGIME_CHOP_CONFIDENCE

    # Combined floor: take the most restrictive applicable bar.
    # Both 1h adverse AND 5m chop → still 0.92 (same value; can't go higher).
    if in_1h_adverse:
        floor = _CHART_1H_ADVERSE_FLOOR
        floor_reason = "1h_adverse_below_high_bar"
    elif in_5m_chop:
        floor = _CHART_CHOP_FLOOR
        floor_reason = "chop_below_high_bar"
    else:
        floor = _CHART_MIN_CONFIDENCE
        floor_reason = "chart_below_threshold"

    if chart.confidence < floor:
        return ("decline", floor_reason)

    # Rule 4 — memory must not contradict (realized-outcome based, B4).
    if memory.verdict == "bearish" and memory.confidence >= _MEMORY_CONTRADICT_CONFIDENCE:
        return ("decline", "memory_contradicts")

    # All gates passed. Surface context in the rule label.
    if in_1h_adverse:
        rule_label = "1h_adverse_high_conviction"
    elif in_5m_chop:
        rule_label = "chop_high_conviction"
    else:
        rule_label = "all_voices_aligned"
    return ("act", rule_label)


__all__ = ["coordinator"]
