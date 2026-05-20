"""memory_voice — local-ledger continuity check.

Reads the last 20 rows of the panel's own JSONL ledger and grades
whether the chart_analyst's current bullish read is a CONFIRM, a
CONTRADICTION, or NOVEL relative to recent bot behavior. The novel
surface of the panel — no PRD counterpart. See
``docs/strategy/lab-validated/2026-05-20-local-panel-voices-spec.md`` §3.2.

v0.1 cold-start note: the ledger has *decisions* but no realized
*outcomes* yet — outcomes land in v0.2 after the contest closes and a
week of ``position_close`` rows accumulates. The prompt tells the
model this explicitly so it doesn't fabricate an outcome-based read.
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
bot's local decision ledger and grade whether a new proposed entry
CONFIRMS, CONTRADICTS, or is NOVEL relative to recent behavior.

ROLE
You are NOT a market analyst. You are a continuity checker. Your job
is to surface whether the bot's pattern of recent decisions on this
instrument supports or contradicts the current proposed action.

IMPORTANT CONTEXT (v0.1)
You DO NOT yet have realized outcomes (win/loss PnL on closed trades).
The ledger contains DECISIONS ONLY (act / decline / open / block). Do
not speculate about whether prior decisions made money. Outcomes will
land in v0.2; for now, treat the ledger as a behavior log.

INPUTS
You receive:
  (a) the current proposed action (long entry on the in-scope instrument),
  (b) up to 20 prior ledger rows, each as:
        { "ts": "...", "event": "local_decision|position_close|...",
          "instrument": "...", "action": "act|decline",
          "reason": "..." }

VERDICT MAPPING
  - 'bullish'  = the proposed entry CONFIRMS recent panel behavior;
                  the bot has been graded similar setups recently and
                  acted (>=50% act rate on >=3 matching rows).
  - 'bearish'  = the proposed entry CONTRADICTS recent panel behavior;
                  the bot has been graded similar setups recently and
                  declined (<30% act rate on >=3 matching rows).
  - 'neutral'  = the ledger is mixed - some confirms, some declines
                  (act rate 30-50%).
  - 'abstain'  = NOVEL or COLD START - fewer than 3 matching rows in
                  the last 20; insufficient ledger to grade.

ABSTAIN PROTOCOL
Return 'abstain' when:
  - the ledger has fewer than 3 rows total (cold-start),
  - fewer than 3 matching rows on this instrument in the last 20,
  - all recent matching decisions are older than 24h (stale memory).
DO NOT fabricate a pattern from one matching row. Three is the minimum.

DO NOT
  - DO NOT use the ledger to predict price direction. That is the
    chart_analyst's job. You only grade continuity.
  - DO NOT speculate about realized PnL - you don't have outcomes.
  - DO NOT use chain-of-thought; emit the JSON object directly.

OUTPUT (JSON only)
{
  "verdict": "<bullish|bearish|neutral|abstain>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<<=200 char one-liner stating the matching count>",
  "observations": ["<row summary 1>", "<row summary 2>", "..."]
}

Confidence anchors:
  0.50-0.60 = 3 matching rows
  0.60-0.70 = 4-5 matching rows
  0.70-0.80 = 6+ matching rows, all within 12h
  >0.80     = 8+ matching rows, consistent verdict - use sparingly
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

        # Read up to 20 rows from the panel's own write surface +
        # position-close rows once outcomes land. v0.1 mostly sees
        # local_decision rows (the panel writes one per turn).
        try:
            rows = memory.recent(
                event_filter=("local_decision", "position_close"),
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
                "event": row.get("event", ""),
                "instrument": payload.get("market_state", {}).get("instrument")
                if isinstance(payload.get("market_state"), dict)
                else payload.get("instrument", ""),
                "action": payload.get("action", ""),
                "reason": payload.get("reason", "")[:80]
                if isinstance(payload.get("reason"), str)
                else "",
            }
        )

    table_json = json.dumps(rows_for_model, separators=(",", ":"))
    return (
        f"Proposed action: long entry on {instrument}.\n\n"
        f"Last {len(rows_for_model)} ledger rows (newest-first):\n{table_json}\n\n"
        f"Grade continuity. Remember: NO outcomes yet, decisions only."
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
