"""memory_voice — realized-outcome continuity check (B4 fix, S40).

Grades whether the current proposed entry is supported or contradicted by
the bot's REALIZED OUTCOMES on this instrument — wins vs losses on closed
trades, NOT prior decisions.

THE BUG THIS FIXES (2026-05-20 → S40 B4): the prior version read
``local_decision`` rows (act/decline) and voted bearish when recent
decisions on an instrument were declines. That is a self-reinforcing
feedback loop: declines → bearish memory vote → more declines. Reading
*decisions* makes the voice echo the panel's own caution.

THE FIX: read ONLY ``position_close`` rows (realized PnL outcomes). A
decline is not an outcome and never feeds back. With fewer than 3 closed
outcomes on the instrument, abstain (true cold-start — no loop possible).
Net-positive recent outcomes → mild confirm (bullish); net-negative →
mild contradict (bearish, capped ≤0.6 so it can't dominate). Recency-
weighted (newer closes matter more).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from llm_client import LLMResponse, OpenRouterClient

from voices.base import MemoryReader, VoiceOpinion, VoiceVerdict, safe_parse_voice_json

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-4o-mini"

# Per spec §3.2 ABSTAIN PROTOCOL — fewer than this many rows = cold start.
_COLD_START_MIN_ROWS = 3
_MEMORY_WINDOW = 20

_SYSTEM_PROMPT = """You are the memory_voice on a local trading lab panel. You read the
bot's REALIZED TRADE OUTCOMES (closed positions with PnL) and grade
whether a new proposed entry is supported or contradicted by how
similar trades have actually RESOLVED.

ROLE
You are NOT a market analyst and NOT a decision-echo. You grade
realized history: did closed trades on this instrument tend to WIN or
LOSE recently? You never read declines or pending decisions — only
outcomes that actually happened.

INPUTS
You receive:
  (a) the current proposed action (long entry on the in-scope instrument),
  (b) up to 20 prior CLOSED-TRADE rows, each as:
        { "ts": "...", "instrument": "...",
          "pnl_pct": <float>, "exit_reason": "take_profit|stop_loss|trail|stall|time_stop" }

VERDICT MAPPING (based on REALIZED outcomes, recency-weighted)
  - 'bullish'  = recent closed trades on this instrument were net-POSITIVE
                  (>=3 closes, weighted-avg pnl > +0.5%). History supports re-entry.
  - 'bearish'  = recent closed trades were net-NEGATIVE
                  (>=3 closes, weighted-avg pnl < -0.5%). History contradicts re-entry.
  - 'neutral'  = >=3 closes but roughly flat (weighted-avg pnl within ±0.5%).
  - 'abstain'  = fewer than 3 closed outcomes on this instrument (cold-start)
                  OR all outcomes older than 48h (stale).

WEIGHTING
Newer closes matter more (recency weight, ~24h half-life). Do not let one
old win/loss dominate. Weight by recency, then average the pnl_pct.

CONFIDENCE CAP
Cap 'bearish' confidence at 0.6 — memory contradicts, it does not veto.
'bullish' may go higher with more consistent wins.

DO NOT
  - DO NOT read or count declines/decisions — only closed outcomes.
  - DO NOT predict price direction (that's chart_analyst).
  - DO NOT fabricate an outcome pattern from fewer than 3 closes.
  - DO NOT use chain-of-thought; emit the JSON object directly.

OUTPUT (JSON only)
{
  "verdict": "<bullish|bearish|neutral|abstain>",
  "confidence": <float 0.0-1.0, bearish capped at 0.6>,
  "reasoning": "<<=200 char one-liner: N closes, weighted-avg pnl%>",
  "observations": ["<close summary 1>", "..."]
}

Confidence anchors:
  0.50-0.60 = 3 closed outcomes, consistent direction
  0.60-0.75 = 4-6 closed outcomes, consistent (bullish only; bearish caps 0.6)
  >0.75     = 7+ closed outcomes, very consistent wins - use sparingly
"""


class MemoryVoice:
    """LocalVoice that grades continuity against the local JSONL ledger."""

    voice_name: str = "memory_voice"

    def __init__(
        self,
        client: OpenRouterClient,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = client
        self._model = model

    async def grade(
        self,
        market_state: dict[str, Any],
        memory: MemoryReader,
    ) -> VoiceOpinion:
        started = time.monotonic()

        # B4 fix: read ONLY position_close (realized outcomes). Decisions
        # (local_decision act/decline) are deliberately NOT read — reading
        # them created the decline→bearish→decline feedback loop. A decline
        # is not an outcome.
        try:
            rows = memory.recent(
                event_filter=("position_close",),
                limit=_MEMORY_WINDOW,
            )
        except Exception as exc:
            logger.warning("memory_voice: memory.recent raised %s", type(exc).__name__)
            return _abstain(
                reasoning=f"memory_error:{type(exc).__name__}",
                raw_response="",
                elapsed_ms=int((time.monotonic() - started) * 1000),
                cost_usd=None,
            )

        # Hard cold-start floor — abstain WITHOUT calling the LLM. Per
        # spec §3.2: "Three is the minimum for a pattern call."
        if len(rows) < _COLD_START_MIN_ROWS:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return VoiceOpinion(
                voice_name=self.voice_name,
                verdict="abstain",
                confidence=0.0,
                reasoning="cold_start_insufficient_history",
                observations=[f"only {len(rows)} rows; need >= {_COLD_START_MIN_ROWS}"],
                raw_response="",
                elapsed_ms=elapsed_ms,
                cost_usd=None,
            )

        user_prompt = _build_user_prompt(market_state, rows)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response: LLMResponse = await asyncio.to_thread(
                self._client.chat,
                model=self._model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
            )
        except Exception as exc:
            logger.warning("memory_voice: openrouter error %s", type(exc).__name__)
            return _abstain(
                reasoning=f"openrouter_error:{type(exc).__name__}",
                raw_response="",
                elapsed_ms=int((time.monotonic() - started) * 1000),
                cost_usd=None,
            )

        elapsed_ms = response.elapsed_ms or int((time.monotonic() - started) * 1000)
        parsed = safe_parse_voice_json(response.content, self.voice_name)
        if parsed is None:
            return _abstain(
                reasoning="parse_error",
                raw_response=response.content,
                elapsed_ms=elapsed_ms,
                cost_usd=response.cost_usd,
            )

        return VoiceOpinion(
            voice_name=self.voice_name,
            verdict=_coerce_verdict(parsed.get("verdict")),
            confidence=_coerce_confidence(parsed.get("confidence")),
            reasoning=_coerce_str(parsed.get("reasoning"), 200),
            observations=_coerce_observations(parsed.get("observations")),
            raw_response=response.content,
            elapsed_ms=elapsed_ms,
            cost_usd=response.cost_usd,
        )


def _build_user_prompt(market_state: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """Compact a list of ledger rows into a prompt-friendly summary.

    Keeps input small (<1k tokens target per spec §3.2). We pull only
    the fields the prompt's verdict mapping needs — ts / event /
    instrument / action / reason. Full row content stays in the
    ledger for audit.
    """
    instrument = str(market_state.get("instrument") or market_state.get("symbol") or "?")
    rows_for_model: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload") or {}
        rows_for_model.append(
            {
                "ts": row.get("ts_iso", ""),
                "instrument": payload.get("symbol") or payload.get("token", "")[:12],
                "pnl_pct": payload.get("pnl_pct"),
                "exit_reason": payload.get("exit_reason", ""),
            }
        )

    table_json = json.dumps(rows_for_model, separators=(",", ":"))
    return (
        f"Proposed action: long entry on {instrument}.\n\n"
        f"Last {len(rows_for_model)} CLOSED-TRADE outcomes (newest-first):\n{table_json}\n\n"
        f"Grade by realized outcomes on {instrument} (recency-weighted). "
        f"Fewer than 3 closes on this instrument → abstain."
    )


_ALLOWED_VERDICTS: frozenset[VoiceVerdict] = frozenset(("bullish", "bearish", "neutral", "abstain"))


def _coerce_verdict(value: Any) -> VoiceVerdict:
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in _ALLOWED_VERDICTS:
            return lower
    return "abstain"


def _coerce_confidence(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _coerce_str(value: Any, max_len: int) -> str:
    if not isinstance(value, str):
        return ""
    return value[:max_len]


def _coerce_observations(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:5]:
        if isinstance(item, str):
            out.append(item[:200])
        else:
            out.append(str(item)[:200])
    return out


def _abstain(
    *,
    reasoning: str,
    raw_response: str,
    elapsed_ms: int,
    cost_usd: float | None,
) -> VoiceOpinion:
    return VoiceOpinion(
        voice_name="memory_voice",
        verdict="abstain",
        confidence=0.0,
        reasoning=reasoning[:200],
        observations=[],
        raw_response=raw_response,
        elapsed_ms=elapsed_ms,
        cost_usd=cost_usd,
    )


__all__ = ["DEFAULT_MODEL", "MemoryVoice"]
