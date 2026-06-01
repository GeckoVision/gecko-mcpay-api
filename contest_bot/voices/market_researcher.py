"""Sprint 28 — market_researcher voice.

The 6th voice in the local panel. Reads the new `market_news` Mongo
collection (DATA-2, commit 780cbf9) and grades whether RECENT NEWS on
the current symbol supports / opposes / is silent on a candidate long
entry. The only voice that reads EXOGENOUS TEXT — an axis the other
five voices structurally cannot see.

Architecture: **HYBRID — deterministic confidence + cached LLM sentiment.**

Why hybrid: per `private/strategy/2026-05-31-s24-s-voice-fix-plan.md`,
gpt-4o-mini at temperature=0 snaps to printed anchor numbers (only 3
unique conf values observed across chart/memory/strategist). regime_analyst
(pure-deterministic math) gets 37 unique values. So:

* The sentiment classification (the LLM-needs part) is done ONCE at
  ingest time and stored as `classification.bias_score` on the news row.
  See `scripts/data/classify_news_rows.py` (S28-AI-2).
* This voice's `grade()` is pure Python aggregation over the cached
  scores. **Voice grade path = ZERO LLM calls.** Confidence is a
  continuous function of (n_rows, recency_weights, abs(agg_bias)).

Default state: `GECKO_MARKET_RESEARCHER_ENABLED=0` (OFF). Voice is not
added to the panel unless the founder flips. Bot behavior unchanged
when off — `bootstrap.py` skips construction at the env check.
"""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from voices.base import VoiceOpinion

logger = logging.getLogger("voices.market_researcher")

# Cold-start floor — mirrors memory_voice._COLD_START_MIN_ROWS. A single
# sensational headline must not be allowed to move the panel.
_COLD_START_MIN_ROWS = 3

# Default window + half-life (env-overridable). See design doc §7.
_DEFAULT_WINDOW_HOURS = 6.0
_DEFAULT_HALF_LIFE_HOURS = 6.0

# Bias thresholds for verdict mapping. agg_bias ∈ [-1, +1].
# >+0.2 bullish, <-0.2 bearish, else neutral. Symmetric.
_BIAS_BULLISH_THRESHOLD = 0.2


def _resolve_instrument(market_state: dict[str, Any]) -> str:
    """Mirror memory_voice.py:151-154 — `instrument` field first, then
    `symbol` split + uppercase. Empty string when both missing."""
    raw = (market_state.get("instrument") or "").strip()
    if raw:
        return raw.upper()
    sym = (market_state.get("symbol", "") or "").strip()
    if sym:
        return sym.split("-")[0].upper()
    return ""


def _window_hours() -> float:
    """Read GECKO_MARKET_RESEARCHER_WINDOW_HOURS — lookback bound."""
    try:
        return float(
            os.environ.get("GECKO_MARKET_RESEARCHER_WINDOW_HOURS", _DEFAULT_WINDOW_HOURS)
        )
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW_HOURS


def _half_life_hours() -> float:
    """Read GECKO_MARKET_RESEARCHER_HALF_LIFE_HOURS — recency-weight decay."""
    try:
        return float(
            os.environ.get(
                "GECKO_MARKET_RESEARCHER_HALF_LIFE_HOURS", _DEFAULT_HALF_LIFE_HOURS
            )
        )
    except (TypeError, ValueError):
        return _DEFAULT_HALF_LIFE_HOURS


def _abstain(reasoning: str, observations: list[str], elapsed_ms: int) -> VoiceOpinion:
    """Build a standardized abstain opinion — never raises."""
    return VoiceOpinion(
        voice_name="market_researcher",
        verdict="abstain",
        confidence=0.0,
        reasoning=reasoning[:400],
        observations=[o[:120] for o in observations][:10],
        raw_response="",
        elapsed_ms=elapsed_ms,
        cost_usd=None,
    )


def _parse_published(row: dict[str, Any]) -> datetime | None:
    """Best-effort ISO-8601 → tz-aware datetime. None on malformed."""
    raw = row.get("published_at")
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _aggregate(
    rows: list[dict[str, Any]],
    now: datetime,
    half_life_hours: float,
) -> tuple[float, int, list[float]]:
    """Compute (agg_bias, n_classified, weights) over the rows.

    Pure function — no I/O. Rows missing `classification.bias_score`
    are SKIPPED (they don't count toward floor or aggregation). agg_bias
    is the recency-weighted average of bias_scores; weights decay
    exponentially with age_hours and the given half-life.

    Returns:
        (agg_bias, n_classified_rows, weights_list).
        Empty rows → (0.0, 0, []).
    """
    n_classified = 0
    total_w = 0.0
    weighted_sum = 0.0
    weights: list[float] = []
    decay = math.log(2.0) / max(half_life_hours, 0.1)
    for r in rows:
        cls = r.get("classification") or {}
        bias = cls.get("bias_score")
        if bias is None:
            continue
        try:
            bias_f = float(bias)
        except (TypeError, ValueError):
            continue
        # Clamp defensively — classifier should already constrain.
        bias_f = max(-1.0, min(1.0, bias_f))
        pub_dt = _parse_published(r)
        if pub_dt is None:
            # Row had bias but unparseable timestamp: include with weight 1.0
            # (treat as "no recency penalty"). Rare; logged but not fatal.
            w = 1.0
        else:
            age_h = max(0.0, (now - pub_dt).total_seconds() / 3600.0)
            w = math.exp(-decay * age_h)
        weights.append(w)
        weighted_sum += w * bias_f
        total_w += w
        n_classified += 1
    if n_classified == 0 or total_w <= 0:
        return (0.0, 0, [])
    return (weighted_sum / total_w, n_classified, weights)


def _confidence(n_classified: int, agg_bias: float) -> float:
    """Deterministic confidence per design doc §4. Continuous → ≥5
    unique values guaranteed across realistic input variation."""
    n_term = 0.35 * min(n_classified, 5) / 5.0
    bias_term = 0.20 * abs(agg_bias)
    raw = 0.45 + n_term + bias_term
    return max(0.0, min(0.90, raw))


def _verdict(agg_bias: float) -> str:
    """Map agg_bias → verdict. Symmetric thresholds."""
    if agg_bias > _BIAS_BULLISH_THRESHOLD:
        return "bullish"
    if agg_bias < -_BIAS_BULLISH_THRESHOLD:
        return "bearish"
    return "neutral"


class MarketResearcherVoice:
    """Sixth voice. Reads market_news, grades news-based bias.

    Injectable `news_lookup` callable for tests — defaults to the
    decision_store.news_query.by_symbol wrapper. The voice itself
    never raises and never makes an LLM call.
    """

    voice_name: str = "market_researcher"

    def __init__(
        self,
        *,
        news_lookup: Any = None,
        window_hours: float | None = None,
        half_life_hours: float | None = None,
        now_fn: Any = None,
    ) -> None:
        # Lazy default: import here so test fixtures can pre-patch
        # news_query without paying the import cost when the voice is
        # OFF (env-gated panel construction skips this whole module).
        if news_lookup is None:
            from decision_store.news_query import by_symbol as _default_lookup

            news_lookup = _default_lookup
        self._news_lookup = news_lookup
        self._window_hours = (
            window_hours if window_hours is not None else _window_hours()
        )
        self._half_life_hours = (
            half_life_hours
            if half_life_hours is not None
            else _half_life_hours()
        )
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    async def grade(
        self,
        market_state: dict[str, Any],
        memory: Any,  # noqa: ARG002 — unused; this voice doesn't read the JSONL
    ) -> VoiceOpinion:
        started = time.monotonic()

        # 1. Resolve symbol. Refuse the universe-wide fallback (S24-S 2b
        # lesson: that's how memory_voice was bleeding cross-instrument).
        instrument = _resolve_instrument(market_state)
        if not instrument:
            return _abstain(
                "symbol_unresolved",
                ["market_state missing both 'instrument' and 'symbol'"],
                int((time.monotonic() - started) * 1000),
            )

        # 2. Window query. by_symbol() filters tickers ∋ instrument
        # AND published_at ≥ now-window. Returns [] on Mongo unavailable
        # (best-effort by design — see news_query.by_symbol).
        now = self._now_fn()
        since = now - timedelta(hours=self._window_hours)
        try:
            rows = self._news_lookup(instrument, since=since, limit=200)
        except Exception as exc:
            # Defensive — by_symbol already swallows internally, but
            # injected test lookups might raise.
            logger.warning(
                "market_researcher: news_lookup raised %s", type(exc).__name__
            )
            return _abstain(
                f"news_lookup_error:{type(exc).__name__}",
                [f"window={self._window_hours}h", f"symbol={instrument}"],
                int((time.monotonic() - started) * 1000),
            )

        if not rows:
            return _abstain(
                "no_news_in_window",
                [f"window={self._window_hours}h", f"symbol={instrument}"],
                int((time.monotonic() - started) * 1000),
            )

        # 3. Aggregate — skips rows missing classification.bias_score.
        agg_bias, n_classified, _weights = _aggregate(
            rows, now, self._half_life_hours
        )

        # 4. Cold-start: enough CLASSIFIED rows to grade?
        if n_classified < _COLD_START_MIN_ROWS:
            return _abstain(
                "cold_start_insufficient_news",
                [
                    f"rows_total={len(rows)}",
                    f"rows_classified={n_classified}",
                    f"floor={_COLD_START_MIN_ROWS}",
                    f"symbol={instrument}",
                ],
                int((time.monotonic() - started) * 1000),
            )

        # 5. Verdict + deterministic confidence.
        verdict = _verdict(agg_bias)
        confidence = _confidence(n_classified, agg_bias)
        reasoning = (
            f"n={n_classified} rows in {self._window_hours}h window; "
            f"weighted-avg bias={agg_bias:+.2f}; verdict={verdict}"
        )
        observations = [
            f"symbol={instrument}",
            f"rows_total={len(rows)}",
            f"rows_classified={n_classified}",
            f"agg_bias={agg_bias:+.3f}",
            f"window_h={self._window_hours}",
            f"half_life_h={self._half_life_hours}",
        ]
        return VoiceOpinion(
            voice_name="market_researcher",
            verdict=verdict,  # type: ignore[arg-type]
            confidence=confidence,
            reasoning=reasoning[:400],
            observations=observations[:10],
            raw_response="",
            elapsed_ms=int((time.monotonic() - started) * 1000),
            cost_usd=None,
        )


__all__ = ["MarketResearcherVoice"]
