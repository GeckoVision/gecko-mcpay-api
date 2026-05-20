"""chart_analyst — OHLCV setup grading voice.

The voice the S24 WS-A reframe deleted from the PRD panel by design
(``_default_prompts.json:5``). We add it back LOCALLY against a separate
cheap-LLM call (gpt-4o-mini via OpenRouter), with the artifact ledger
as the eval substrate. See
``docs/strategy/lab-validated/2026-05-20-local-panel-voices-spec.md`` §3.1.

The single load-bearing defense against the S24 confabulation failure
mode is the **abstain protocol**: the prompt enumerates thin-liquidity,
stale-feed, range-bound-chop, weekend low-vol and "<24 bars" conditions
under which the voice MUST return ``abstain``. A response-side double
check rescues the case where gpt-4o-mini ignores the protocol on a
synthetic-zero-vol probe — per spec §8.2.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from llm_client import LLMResponse, OpenRouterClient

from voices.base import MemoryReader, VoiceOpinion, VoiceVerdict, safe_parse_voice_json

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-4o-mini"

# Tightened from spec §3.1: ``>4 zero-vol bars → abstain``. Re-checked
# server-side because gpt-4o-mini occasionally rounds toward "bullish"
# on a freshly-listed token whose first 24 bars are zero.
_MAX_ZERO_VOL_BARS = 4

_SYSTEM_PROMPT = """You are the chart_analyst on a local trading lab panel. You read recent
OHLCV bars on a single instrument and grade the setup.

ROLE
You characterize the SHORT-HORIZON technical setup on the instrument in
scope - bullish, bearish, neutral, or no_setup. You do NOT read
fundamentals, you do NOT read sentiment, you do NOT recommend size or
horizon. You grade the bars in front of you.

INPUTS
You receive:
  (a) instrument name and current spot,
  (b) the last 30 5-minute OHLCV bars,
  (c) 1h delta%, 24h delta%, 24h range%.

WHAT TO GRADE
  1. Trend over the last 6 bars (30 minutes): up, down, flat.
  2. Trend over the last 24 bars (2 hours): up, down, flat.
  3. Recent breakout posture: did price cross the trailing-24-bar high
     with confirmation, or trailing-24-bar low.
  4. Volume confirmation: is the breakout bar's volume above the
     6-bar median.
  5. Range posture: is the asset in tight chop (<2% 24h range), normal
     drift (2-8%), or active trend (>8%).

ABSTAIN PROTOCOL (load-bearing)
Return verdict='abstain' when ANY of the following holds:
  - fewer than 24 bars provided,
  - more than 4 of the 30 bars have zero volume (thin-liquidity flag),
  - the most recent bar is older than 10 minutes (stale feed),
  - the 24h range is below 1% (range-bound chop - no setup to grade),
  - weekend low-vol window (Sat 06:00 - Sun 22:00 UTC) AND 24h volume
    USD < $1M (cross-instrument equivalent of the PRD weekend penalty).
Return verdict='neutral' when bars are healthy but the setup is mid -
trend is flat OR breakout has no volume confirmation. 'neutral' is NOT
an abstain; the coordinator treats it as a real call.

DO NOT
  - DO NOT call support/resistance levels by absolute price - only by
    relative-to-trailing-N-bar reads.
  - DO NOT invent RSI, MACD, or any indicator the input does not carry.
  - DO NOT speculate about news, sentiment, or macro.
  - DO NOT recommend size, leverage, stop, or take-profit.
  - DO NOT use chain-of-thought; emit the JSON object directly.

OUTPUT (JSON only)
{
  "verdict": "<bullish|bearish|neutral|abstain>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<<=200 char one-liner naming the setup>",
  "observations": ["<bullet 1>", "<bullet 2>", "..."]
}

Confidence anchors:
  0.50-0.60 = soft lean (one of the five gradings supports the call)
  0.60-0.70 = clean lean (two of five align)
  0.70-0.80 = strong setup (three of five align, including volume)
  >0.80     = exceptional alignment (four+ of five) - use sparingly
"""


class ChartAnalystVoice:
    """LocalVoice that grades the chart setup on the in-scope instrument.

    Calls OpenRouter via the injected :class:`OpenRouterClient` (sync
    under the hood; wrapped in ``asyncio.to_thread`` because the
    ``LocalVoice`` Protocol is async — see ``voices/base.py``).
    """

    voice_name: str = "chart_analyst"

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
        # memory is unused by this voice — chart reads bars only, not
        # ledger continuity. The Protocol still requires the arg.
        del memory

        started = time.monotonic()
        user_prompt = _build_user_prompt(market_state)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        # The OpenRouterClient is sync; the LocalVoice contract is
        # async. Wrap to keep the panel's gather() honest. The HTTP
        # call dominates the latency budget; the thread-hop is ~ms.
        try:
            response: LLMResponse = await asyncio.to_thread(
                self._client.chat,
                model=self._model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
            )
        except Exception as exc:
            logger.warning("chart_analyst: openrouter error %s", type(exc).__name__)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return _abstain(
                reasoning=f"openrouter_error:{type(exc).__name__}",
                raw_response="",
                elapsed_ms=elapsed_ms,
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

        verdict = _coerce_verdict(parsed.get("verdict"))
        confidence = _coerce_confidence(parsed.get("confidence"))
        reasoning = _coerce_str(parsed.get("reasoning"), max_len=200)
        observations = _coerce_observations(parsed.get("observations"))

        # Response-side double check on the load-bearing thin-liquidity
        # clause. gpt-4o-mini occasionally returns bullish-with-low-conf
        # on a synthetic-zero-vol probe; treat that as abstain.
        # This is the response-parser side of the §3.1 + §8.2 defense.
        zero_vol_count = _count_zero_volume_bars(market_state)
        if zero_vol_count > _MAX_ZERO_VOL_BARS and verdict != "abstain":
            logger.info(
                "chart_analyst: model returned %s but %d zero-vol bars > %d; "
                "forcing abstain per thin-liquidity penalty",
                verdict,
                zero_vol_count,
                _MAX_ZERO_VOL_BARS,
            )
            return VoiceOpinion(
                voice_name=self.voice_name,
                verdict="abstain",
                confidence=0.0,
                reasoning=f"thin_liquidity_override:{zero_vol_count}_zero_vol_bars",
                observations=observations,
                raw_response=response.content,
                elapsed_ms=elapsed_ms,
                cost_usd=response.cost_usd,
            )

        return VoiceOpinion(
            voice_name=self.voice_name,
            verdict=verdict,
            confidence=confidence,
            reasoning=reasoning,
            observations=observations,
            raw_response=response.content,
            elapsed_ms=elapsed_ms,
            cost_usd=response.cost_usd,
        )


def _build_user_prompt(market_state: dict[str, Any]) -> str:
    """Build the chart prompt from the snapshot the bot hands us.

    The bot's current ``market_state`` shape carries spot + deltas +
    range + 24h volume; the candle list is optional. When candles are
    missing the prompt still ships (the abstain protocol catches it),
    so the voice fails gracefully rather than raising on a partial
    snapshot.
    """
    instrument = str(market_state.get("instrument") or market_state.get("symbol") or "?")
    spot_price = _safe_float(market_state.get("spot_price"))
    change_1h = _safe_float(market_state.get("change_1h_pct"))
    change_24h = _safe_float(market_state.get("change_24h_pct"))
    range_24h = _safe_float(market_state.get("range_24h_pct"))

    bars = market_state.get("ohlcv_5m") or market_state.get("candles") or []
    bars = bars if isinstance(bars, list) else []
    ohlcv_table = _format_ohlcv_table(bars)

    return (
        f"Instrument: {instrument}\n"
        f"Spot: ${spot_price:.6f}\n"
        f"1h delta: {change_1h:+.2f}%\n"
        f"24h delta: {change_24h:+.2f}%\n"
        f"24h range: {range_24h:.2f}%\n\n"
        f"Last 30 5m bars (oldest first):\n{ohlcv_table}\n\n"
        f"Grade the setup."
    )


def _format_ohlcv_table(bars: list[Any]) -> str:
    """Render OHLCV bars as one row per line; tolerate dict-or-list shapes."""
    if not bars:
        return "(no bars provided)"
    lines: list[str] = ["ts,open,high,low,close,vol"]
    for bar in bars[-30:]:  # cap at 30 even if the bot hands more
        ts, o, h, low, c, v = _extract_bar_fields(bar)
        lines.append(f"{ts},{o},{h},{low},{c},{v}")
    return "\n".join(lines)


def _extract_bar_fields(bar: Any) -> tuple[str, float, float, float, float, float]:
    """Pull ts/o/h/l/c/v out of either a dict or a tuple-shaped bar."""
    if isinstance(bar, dict):
        ts = str(bar.get("ts") or bar.get("timestamp") or bar.get("t") or "")
        return (
            ts,
            _safe_float(bar.get("open") or bar.get("o")),
            _safe_float(bar.get("high") or bar.get("h")),
            _safe_float(bar.get("low") or bar.get("l")),
            _safe_float(bar.get("close") or bar.get("c")),
            _safe_float(bar.get("volume") or bar.get("v")),
        )
    if isinstance(bar, (list, tuple)) and len(bar) >= 6:
        return (
            str(bar[0]),
            _safe_float(bar[1]),
            _safe_float(bar[2]),
            _safe_float(bar[3]),
            _safe_float(bar[4]),
            _safe_float(bar[5]),
        )
    return ("?", 0.0, 0.0, 0.0, 0.0, 0.0)


def _count_zero_volume_bars(market_state: dict[str, Any]) -> int:
    """Count zero-volume bars in the last 30. Used for the response-side override."""
    bars = market_state.get("ohlcv_5m") or market_state.get("candles") or []
    if not isinstance(bars, list) or not bars:
        return 0
    count = 0
    for bar in bars[-30:]:
        _, _, _, _, _, v = _extract_bar_fields(bar)
        if v == 0.0:
            count += 1
    return count


_ALLOWED_VERDICTS: frozenset[VoiceVerdict] = frozenset(("bullish", "bearish", "neutral", "abstain"))


def _coerce_verdict(value: Any) -> VoiceVerdict:
    """Map any incoming verdict to the closed Literal set (default abstain)."""
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in _ALLOWED_VERDICTS:
            return lower
    return "abstain"


def _coerce_confidence(value: Any) -> float:
    """Clip confidence into [0.0, 1.0]; default 0.0 on malformed values."""
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
    """Up to 5 short observation bullets (spec §3.1)."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:5]:
        if isinstance(item, str):
            out.append(item[:200])
        else:
            out.append(str(item)[:200])
    return out


def _safe_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _abstain(
    *,
    reasoning: str,
    raw_response: str,
    elapsed_ms: int,
    cost_usd: float | None,
) -> VoiceOpinion:
    return VoiceOpinion(
        voice_name="chart_analyst",
        verdict="abstain",
        confidence=0.0,
        reasoning=reasoning[:200],
        observations=[],
        raw_response=raw_response,
        elapsed_ms=elapsed_ms,
        cost_usd=cost_usd,
    )


__all__ = ["DEFAULT_MODEL", "ChartAnalystVoice"]
