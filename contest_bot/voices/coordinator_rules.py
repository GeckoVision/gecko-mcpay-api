"""Local-panel coordinator rules. Pinned in code, NEVER in a prompt.

Per ``feedback-prompt-iteration-plateau``: coordinator verdict logic
lives in CODE because gpt-4o-mini rounds toward caution on any
defer-related instruction (4 iterations observed in S24:
1.0 -> 0.20 -> 0.50 -> 0.90).

The literal rule set, transcribed from spec §4:

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

See ``docs/strategy/lab-validated/2026-05-20-local-panel-voices-spec.md``
§4.
"""

from __future__ import annotations

from typing import Literal

from voices.base import VoiceOpinion

LocalAction = Literal["act", "decline"]

# Per-voice confidence thresholds (spec §4.3). The chart 0.6 mirrors
# the PRD's DEFAULT_GATE_MIN_CONFIDENCE from gecko_wrap.py:58 for
# symmetry across substrates. The memory 0.6 is set by the spec; risk
# 0.8 is the hard-veto bar.
_RISK_VETO_CONFIDENCE = 0.8
_CHART_MIN_CONFIDENCE = 0.6
_MEMORY_CONTRADICT_CONFIDENCE = 0.6

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


def coordinator(opinions: list[VoiceOpinion]) -> tuple[LocalAction, str | None]:
    """Decide ``act`` / ``decline`` from the three voice opinions.

    Pure Python, five if-statements, no prompt. See module docstring
    for the exact rule list.
    """
    by_name = {o.voice_name: o for o in opinions}
    chart = by_name.get("chart_analyst")
    memory = by_name.get("memory_voice", _ABSTAIN_PLACEHOLDER)
    risk = by_name.get("risk_voice", _ABSTAIN_PLACEHOLDER)

    # Defensive special-case: chart is the only positive-signal source.
    # Without it we cannot ever say 'act'. Decline early so downstream
    # rules don't accidentally fall through to act-mode.
    if chart is None:
        return ("decline", "chart_voice_missing")

    # Rule 1 — risk hard veto. ALWAYS first.
    if risk.verdict == "bearish" and risk.confidence >= _RISK_VETO_CONFIDENCE:
        return ("decline", "risk_veto")

    # Rule 2 — chart must be bullish above the confidence threshold.
    if chart.verdict != "bullish" or chart.confidence < _CHART_MIN_CONFIDENCE:
        return ("decline", "chart_below_threshold")

    # Rule 3 — memory must not contradict.
    if memory.verdict == "bearish" and memory.confidence >= _MEMORY_CONTRADICT_CONFIDENCE:
        return ("decline", "memory_contradicts")

    # All gates passed.
    return ("act", "all_voices_aligned")


__all__ = ["coordinator"]
