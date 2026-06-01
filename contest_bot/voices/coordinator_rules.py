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
import time
from collections import deque
from typing import Literal

from voices.base import VoiceOpinion

LocalAction = Literal["act", "decline"]

# Per-voice confidence thresholds (spec §4.3). The chart 0.6 mirrors
# the PRD's DEFAULT_GATE_MIN_CONFIDENCE from gecko_wrap.py:58 for
# symmetry across substrates. The memory 0.6 is set by the spec; risk
# 0.8 is the hard-veto bar.
_RISK_VETO_CONFIDENCE = 0.8
_CHART_MIN_CONFIDENCE = float(
    os.environ.get("GECKO_CHART_MIN_CONF", "0.85")
)  # env-overridable (2026-05-23 overnight tuning). Default 0.85: only cleanest momentum setups pass. Override via GECKO_CHART_MIN_CONF for paper experiments.
_MEMORY_CONTRADICT_CONFIDENCE = 0.6
# B6 (S40) — 5m regime gate-modulator. The backtest proved breakout is -EV in
# chop. So in a confirmed CHOP regime we RAISE the chart floor (only the
# very cleanest setups pass); in TREND/neutral/abstain we use the normal
# floor. This is a MODULATOR, not a veto — it never bans a symbol, it makes
# us selective in chop. (DRIFT in a trend trades at 0.85; DRIFT in chop must
# clear 0.92 — selective, not "never".)
_CHART_CHOP_FLOOR = float(
    os.environ.get("GECKO_CHART_CHOP_FLOOR", "0.92")
)  # chart confidence required to act in a confirmed-chop regime (env-overridable)
_REGIME_CHOP_CONFIDENCE = 0.6  # regime must be this confident it's chop to raise the bar

# Wave-2b (S42) — multi-timeframe 1h regime modulator.
# If the 1h tape is CHOP or TREND-DOWN, raise the chart floor to this value
# (same as the 5m chop floor). TREND-DOWN means the higher-TF tape is
# distributing; taking 5m longs into a TREND-DOWN 1h is the falling-knife
# scenario the strategist diagnosed. This is still a MODULATOR not a hard ban:
# a very high-conviction 5m breakout (chart >= 0.92) can still fire in a
# 1h chop/downtrend — we just require much stronger confirmation.
_CHART_1H_ADVERSE_FLOOR = float(
    os.environ.get("GECKO_CHART_ADVERSE_FLOOR", "0.92")
)  # chart confidence required when 1h is CHOP or TREND-DOWN (env-overridable)

# 2026-05-23 overnight experiment: bypass the chart gate (Rules 2 + 3) to measure
# the RAW breakout signal's EV in PAPER. When ON, a fired breakout enters subject
# ONLY to risk-veto (Rule 1) + memory-contradict (Rule 4); the chart_analyst's
# bullish-requirement + confidence floor are skipped. Default OFF — never ship on.
_CHART_GATE_OFF = os.environ.get("GECKO_CHART_GATE_OFF", "").strip().lower() in ("1", "true", "yes")


# Honesty-sprint Fix 5 (2026-05-27 backtest plan) — strict multi-TF defaults ON.
# Set env to "0" to revert to legacy fail-open on unknown 1h + chart punch-through.
def _treat_unknown_1h_as_adverse() -> bool:
    return os.environ.get("GECKO_TREAT_UNKNOWN_1H_AS_ADVERSE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _strict_multi_tf() -> bool:
    return os.environ.get("GECKO_STRICT_MULTI_TF", "1").strip().lower() in ("1", "true", "yes")


# Phase 3 hypothesis gates — default OFF; enable per backtest variant.
def _chop_filter_enabled() -> bool:
    return os.environ.get("GECKO_CHOP_FILTER", "0").strip().lower() in ("1", "true", "yes")


def _chop_filter_max() -> float:
    return float(os.environ.get("GECKO_CHOP_FILTER_MAX", "60"))


def _mfi_floor_enabled() -> bool:
    return os.environ.get("GECKO_MFI_FLOOR", "0").strip().lower() in ("1", "true", "yes")


def _mfi_floor_min() -> float:
    return float(os.environ.get("GECKO_MFI_FLOOR_MIN", "40"))


def _mfi_floor_chart_conf() -> float:
    return float(os.environ.get("GECKO_MFI_FLOOR_CHART_CONF", "0.92"))


# ── Variant G (S24-O, 2026-05-30) — weighted_quorum coordinator mode ───
#
# Architectural background: the legacy coordinator is a sequential
# decline-default chain anchored on chart_analyst as the SOLE positive
# signal. Post-Variant E + F (96 events) chart_analyst is bullish only 21%
# of the time and the 1h-adverse 0.92 floor is mathematically uncrossable
# against chart's hard-coded 0.85 ceiling → 0 fires/96 events.
#
# Variant G replaces the chart-anchor chain with a weighted score across
# all voices. Bullish +2, neutral +1, bearish -1, abstain 0. Act when the
# score clears GECKO_QUORUM_ACT_SCORE (default +2). Hard-veto when ≥ N
# voices are bearish (default 3) regardless of score. 1h-adverse becomes a
# bonus on the threshold (raise by +1) instead of a hard cutoff.
#
# Gate is opt-in: GECKO_COORDINATOR_MODE defaults to "legacy". Production
# behavior is unchanged until the founder explicitly flips the env.
_VOICE_SCORE_WEIGHTS: dict[str, int] = {
    "bullish": 2,
    "neutral": 1,
    "abstain": 0,
    "bearish": -1,
}


def _coordinator_mode() -> str:
    return os.environ.get("GECKO_COORDINATOR_MODE", "legacy").strip().lower()


def _quorum_act_score() -> int:
    return int(os.environ.get("GECKO_QUORUM_ACT_SCORE", "2"))


def _quorum_veto_bearish_count() -> int:
    return int(os.environ.get("GECKO_QUORUM_VETO_BEARISH", "3"))


def _quorum_adverse_bonus() -> int:
    return int(os.environ.get("GECKO_QUORUM_ADVERSE_BONUS", "1"))


# ── S24-V (2026-05-31, founder-gated) — Quant tightening gates ─────────
#
# Two env-gated discipline gates from the 2026-05-31 quant verdict
# (private/strategy/2026-05-31-quant-bot-situation.md). BOTH DEFAULT OFF.
# Production behavior is identical to S24-O until the founder explicitly
# flips the env vars in launch_setup_c.sh.
#
# Gate 1 — Non-risk bullish quorum.
#   risk_voice fired bullish 139/139 polls on 2026-05-31 (constant
#   yes-man). The current weighted_quorum effectively fires on 1B
#   (risk_voice + anyone). This gate requires k≥N bullish from the
#   OTHER voices (chart_analyst, memory_voice, regime_analyst,
#   strategist_voice — strategist NEVER bullish by design, so the
#   effective pool is 3). Default min = 2.
#
#   Env: GECKO_QUORUM_REQUIRE_NON_RISK_BULLISH=1 to enable
#        GECKO_QUORUM_NON_RISK_BULLISH_MIN=2 (default min)
#
# Gate 2 — Flat-stall circuit breaker.
#   When the last N closes are all flat_stall_exit with |mean| below a
#   threshold, the bot is grinding in unproductive chop. Suspend new
#   entries for SUSPEND_MIN minutes. Each new close re-evaluates.
#
#   Env: GECKO_CIRCUIT_BREAKER=1 to enable
#        GECKO_CIRCUIT_BREAKER_LOOKBACK=5      (last N closes)
#        GECKO_CIRCUIT_BREAKER_PNL_THRESHOLD=0.10  (|mean pnl_pct|)
#        GECKO_CIRCUIT_BREAKER_SUSPEND_MIN=240     (suspension window)
#
# State for the circuit breaker is held module-level — a deque of recent
# closes plus a suspension-until timestamp. Resets across bot restarts
# (acceptable: the breaker's signal is "what is happening RIGHT NOW",
# stale recent history would be misleading anyway).


def _require_non_risk_bullish() -> bool:
    return os.environ.get(
        "GECKO_QUORUM_REQUIRE_NON_RISK_BULLISH", "0"
    ).strip().lower() in ("1", "true", "yes")


def _non_risk_bullish_min() -> int:
    return int(os.environ.get("GECKO_QUORUM_NON_RISK_BULLISH_MIN", "2"))


def _circuit_breaker_enabled() -> bool:
    return os.environ.get("GECKO_CIRCUIT_BREAKER", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _circuit_breaker_lookback() -> int:
    return int(os.environ.get("GECKO_CIRCUIT_BREAKER_LOOKBACK", "5"))


def _circuit_breaker_pnl_threshold() -> float:
    return float(os.environ.get("GECKO_CIRCUIT_BREAKER_PNL_THRESHOLD", "0.10"))


def _circuit_breaker_suspend_min() -> int:
    return int(os.environ.get("GECKO_CIRCUIT_BREAKER_SUSPEND_MIN", "240"))


# Mutable module-level state for the circuit breaker. Bounded deque
# size matches the lookback window. `_suspend_until_monotonic` is a
# monotonic-clock timestamp (seconds) — None when not suspended.
_RECENT_CLOSES: deque[tuple[float, str]] = deque(maxlen=20)  # (pnl_pct, exit_reason)
_SUSPEND_UNTIL_MONOTONIC: float | None = None


def report_close(pnl_pct: float, exit_reason: str) -> None:
    """Public API for the bot's close-position path to report a close.

    Called regardless of whether the circuit breaker is enabled — the
    deque is cheap, and we want history available the moment the env
    flag flips ON without losing the prior window. Idempotent +
    fire-and-forget; NEVER raises.
    """
    global _RECENT_CLOSES
    try:
        _RECENT_CLOSES.append((float(pnl_pct), str(exit_reason)))
    except Exception:
        return


def _circuit_broken_now() -> tuple[bool, str | None]:
    """Return (broken, reason). Sets/clears the suspension timestamp
    as a side effect. Caller checks `broken` first, surfaces `reason`
    in the coordinator's decline label for traceability.

    Logic: when the last N closes (lookback) are ALL flat_stall_exit
    AND |mean(pnl_pct)| < pnl_threshold, trigger a suspension for
    suspend_min minutes. While suspended, return broken=True until
    monotonic clock passes the deadline.
    """
    global _SUSPEND_UNTIL_MONOTONIC
    if not _circuit_breaker_enabled():
        return (False, None)

    now = time.monotonic()
    # Active suspension still in effect?
    if _SUSPEND_UNTIL_MONOTONIC is not None and now < _SUSPEND_UNTIL_MONOTONIC:
        remaining = int((_SUSPEND_UNTIL_MONOTONIC - now) / 60)
        return (True, f"circuit_breaker_active:{remaining}min_remaining")

    # Suspension expired — clear it so the next trigger can fire.
    if _SUSPEND_UNTIL_MONOTONIC is not None and now >= _SUSPEND_UNTIL_MONOTONIC:
        _SUSPEND_UNTIL_MONOTONIC = None

    # Evaluate trigger condition on the last N closes.
    lookback = _circuit_breaker_lookback()
    if len(_RECENT_CLOSES) < lookback:
        return (False, None)
    window = list(_RECENT_CLOSES)[-lookback:]
    if not all(reason == "flat_stall_exit" for _, reason in window):
        return (False, None)
    mean_pct = sum(pnl for pnl, _ in window) / lookback
    if abs(mean_pct) >= _circuit_breaker_pnl_threshold():
        return (False, None)

    # Trigger: arm suspension and report.
    _SUSPEND_UNTIL_MONOTONIC = now + (_circuit_breaker_suspend_min() * 60)
    return (
        True,
        f"circuit_breaker_tripped:{lookback}x_flat_stall_mean_{mean_pct:+.3f}pct",
    )


def reset_circuit_breaker_state() -> None:
    """Test-only: clear deque + suspension. Bot must NEVER call this in
    the trading path — the state is the breaker's memory."""
    global _SUSPEND_UNTIL_MONOTONIC
    _RECENT_CLOSES.clear()
    _SUSPEND_UNTIL_MONOTONIC = None


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
    *,
    chop: float | None = None,
    mfi: float | None = None,
) -> tuple[LocalAction, str | None]:
    """Decide ``act`` / ``decline`` from the voice opinions + optional 1h regime.

    Dispatches on ``GECKO_COORDINATOR_MODE``:

    * ``"legacy"`` (default): the sequential decline-default chain anchored
      on chart_analyst — see module docstring for the exact rule list.
    * ``"weighted_quorum"``: Variant G — weighted score across all voices,
      with bearish-count veto + 1h-adverse threshold bonus. Designed to
      unblock structurally-2-voice events (see S24-O notes).

    Production default is unchanged until the founder flips the env.

    Args:
        opinions:   Voice opinions from the local panel.
        regime_1h:  Optional 1h regime string from ``indicators.compute_regime_1h``.
                    Values: "TREND-UP" | "TREND-DOWN" | "CHOP" | None.
                    None means unknown — fail-open (don't raise the bar).
    """
    mode = _coordinator_mode()
    if mode == "weighted_quorum":
        return _coordinator_weighted_quorum(opinions, regime_1h)
    return _coordinator_legacy(opinions, regime_1h, chop=chop, mfi=mfi)


def _coordinator_legacy(
    opinions: list[VoiceOpinion],
    regime_1h: str | None = None,
    *,
    chop: float | None = None,
    mfi: float | None = None,
) -> tuple[LocalAction, str | None]:
    """Legacy sequential decline-default chain — see module docstring."""
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

    # Rule 2 — chart must be bullish at all. (skipped when chart gate off — raw-breakout paper experiment)
    if not _CHART_GATE_OFF and chart.verdict != "bullish":
        return ("decline", "chart_below_threshold")

    # Rule 3a (Wave-2b) — multi-timeframe 1h modulator. If the 1h tape is
    # TREND-DOWN or CHOP, raise the chart floor to _CHART_1H_ADVERSE_FLOOR.
    # TREND-DOWN: the higher-TF tape is distributing — 5m longs face structural
    # headwind. CHOP: 1h context confirms 5m indecision is regime-wide.
    # Fail-open on None (unknown 1h state doesn't tighten the bar).
    in_1h_adverse = regime_1h in ("TREND-DOWN", "CHOP") or (
        regime_1h is None and _treat_unknown_1h_as_adverse()
    )

    # Phase 3 — CHOP filter: high chop_index predicts chop-trap losers.
    if _chop_filter_enabled() and chop is not None and chop > _chop_filter_max():
        return ("decline", "chop_filter")

    # Phase 3 — MFI floor: bullish chart + weak money flow needs extra conviction.
    if (
        _mfi_floor_enabled()
        and chart.verdict == "bullish"
        and mfi is not None
        and mfi < _mfi_floor_min()
        and chart.confidence < _mfi_floor_chart_conf()
    ):
        return ("decline", "mfi_floor")

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

    if not _CHART_GATE_OFF and chart.confidence < floor:
        return ("decline", floor_reason)

    # Fix 5 — hard block when BOTH timeframes are adverse (no punch-through).
    if _strict_multi_tf() and in_1h_adverse and in_5m_chop:
        return ("decline", "strict_multi_tf_adverse")

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


def _coordinator_weighted_quorum(
    opinions: list[VoiceOpinion],
    regime_1h: str | None = None,
) -> tuple[LocalAction, str | None]:
    """Variant G — weighted score across all voices.

    Rules:
      0. Defensive: missing chart_analyst → decline (parity with legacy).
      1. risk hard veto — unchanged (safety always wins).
      2. NEW: hard-veto when ≥ ``GECKO_QUORUM_VETO_BEARISH`` voices are bearish
         (default 3), regardless of score.
      3. NEW: weighted score across all voices using ``_VOICE_SCORE_WEIGHTS``.
         Act when ``score >= GECKO_QUORUM_ACT_SCORE`` (default +2).
      4. 1h-adverse becomes a SCORE MODIFIER: raise the act threshold by
         ``GECKO_QUORUM_ADVERSE_BONUS`` (default +1) instead of a hard floor.

    The weighted score is computed across the FULL opinions list — every
    voice contributes per ``_VOICE_SCORE_WEIGHTS``. Missing voices simply
    don't contribute.
    """
    by_name = {o.voice_name: o for o in opinions}
    chart = by_name.get("chart_analyst")
    risk = by_name.get("risk_voice", _ABSTAIN_PLACEHOLDER)

    # Defensive parity with legacy: chart absent → decline.
    if chart is None:
        return ("decline", "chart_voice_missing")

    # Rule 1 — risk hard veto. ALWAYS first.
    if risk.verdict == "bearish" and risk.confidence >= _RISK_VETO_CONFIDENCE:
        return ("decline", "risk_veto")

    # S24-V Gate 2 — Flat-stall circuit breaker (env-gated, default OFF).
    # Suspends new entries when the last N closes are all flat_stall with
    # |mean| below threshold. Checked BEFORE the bullish quorum gate so
    # the bot stops trying in unproductive chop. See module docstring +
    # _circuit_broken_now for the trigger logic.
    broken, breaker_reason = _circuit_broken_now()
    if broken:
        return ("decline", breaker_reason or "circuit_breaker")

    # S24-V Gate 1 — Non-risk bullish quorum (env-gated, default OFF).
    # Discounts risk_voice's constant-bull from the act-quorum because
    # risk_voice was 139/139 bullish on 2026-05-31 (quant verdict). Risk
    # still gates via Rule 1 veto; this gate ensures the ACT decision
    # has support from the other voices, not just risk's yes-man.
    if _require_non_risk_bullish():
        non_risk_bullish = sum(
            1
            for o in opinions
            if o.voice_name != "risk_voice" and o.verdict == "bullish"
        )
        min_required = _non_risk_bullish_min()
        if non_risk_bullish < min_required:
            return (
                "decline",
                f"non_risk_bullish_below_min:{non_risk_bullish}_lt_{min_required}",
            )

    # Rule 2 — bearish-count hard veto. If ≥ N voices say bearish, decline
    # regardless of how strongly the other voices buy. Default N=3 of 5.
    bearish_count = sum(1 for o in opinions if o.verdict == "bearish")
    if bearish_count >= _quorum_veto_bearish_count():
        return ("decline", "bearish_quorum_veto")

    # Rule 3 — weighted score.
    score = sum(_VOICE_SCORE_WEIGHTS.get(o.verdict, 0) for o in opinions)

    # Rule 4 — 1h-adverse threshold bonus (replaces the hard 0.92 floor).
    # Treat unknown 1h as adverse iff GECKO_TREAT_UNKNOWN_1H_AS_ADVERSE.
    in_1h_adverse = regime_1h in ("TREND-DOWN", "CHOP") or (
        regime_1h is None and _treat_unknown_1h_as_adverse()
    )
    threshold = _quorum_act_score()
    if in_1h_adverse:
        threshold += _quorum_adverse_bonus()

    if score >= threshold:
        rule_label = "weighted_quorum_adverse" if in_1h_adverse else "weighted_quorum"
        return ("act", rule_label)
    return ("decline", "weighted_quorum_below_threshold")


__all__ = [
    "coordinator",
    # S24-V — exposed for the bot's close-path to feed the breaker, and
    # for tests that need to reset module-level state.
    "report_close",
    "reset_circuit_breaker_state",
]
