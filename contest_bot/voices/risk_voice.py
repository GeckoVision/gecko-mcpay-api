"""risk_voice — bot's operational floor.

v0.1 keeps the LLM call for *contract uniformity* across the panel
(spec §3.3 / §7.5). The deterministic logic lives in
:func:`_compute_risk_band_deterministic` so v0.2 can collapse this voice
to a pure-Python ``RiskGuard`` via ``model_construct(...)`` without
touching the coordinator. See
``docs/strategy/lab-validated/2026-05-20-local-panel-voices-spec.md`` §3.3.

Hard veto rule (Rule 1 in the coordinator): when this voice returns
``bearish`` with ``confidence >= 0.8`` the panel MUST skip the trade.
The veto checks are deterministic — the LLM is asked only to *ratify*
the precomputed band so we still pay the OpenRouter round-trip in v0.1.
The next sprint can swap to ``model_construct`` without disturbing
the coordinator code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal

from llm_client import LLMResponse, OpenRouterClient

from voices.base import MemoryReader, VoiceOpinion, VoiceVerdict, safe_parse_voice_json

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-4o-mini"

# Veto thresholds — kept here so v0.2's RiskGuard can import them
# directly. Tuned to the spec §3.3 priorities, but tightened to match
# the bot's actual config knobs (MAX_DAILY_TRADES, MAX_BUDGET_USD).
_HOURLY_BREAKER_BAND = -3.0
_BUDGET_HEADROOM_USD = 25.0
_HARD_VETO_CONFIDENCE = 0.85
_HEALTHY_CONFIDENCE = 0.70

_SYSTEM_PROMPT = """You are the risk_voice on a local trading lab panel. You hold a soft
veto: when you return verdict='bearish' AND confidence >= 0.8, the
coordinator MUST skip the trade.

You DO NOT grade the market. You do NOT grade the ledger continuity.
You grade ONE thing: is the bot's operational floor clean enough to
permit a new entry right now?

INPUTS
You receive a risk_band already computed deterministically by the
voice's helper, plus the raw risk_state for context. Your job is to
ratify the band against the raw state — confirm if it looks right,
or escalate to a wider veto if you see a check the helper missed.

INPUT JSON:
{
  "precomputed_band": "<bullish|bearish|neutral|abstain>",
  "precomputed_confidence": <float>,
  "precomputed_reason": "<short string>",
  "risk_state": {
    "daily_trades": <int>,
    "max_daily_trades": <int>,
    "consec_losses": <int>,
    "session_loss_pause_threshold": <int>,
    "hourly_pnl_delta": <float>,
    "breaker_threshold_usd": <float>,
    "total_spent_usd": <float>,
    "max_budget_usd": <float>,
    "open_position_count": <int>,
    "max_concurrent": <int>
  }
}

PRIORITY ORDER FOR VETO
  1. daily_trades >= max_daily_trades         -> bearish 0.9
  2. open_position_count >= max_concurrent    -> bearish 0.9
  3. total_spent_usd within $25 of budget cap -> bearish 0.85
  4. hourly_pnl_delta <= breaker_threshold    -> bearish 0.95 (hard)
  5. consec_losses >= session_loss_pause      -> bearish 0.9
  6. none of the above triggered              -> bullish 0.7
  7. malformed state JSON                     -> abstain 0.0

RULE
  - If precomputed_band already says 'bearish' at >= 0.8, keep it.
  - If you see one of the priority checks the helper missed, ESCALATE.
  - DO NOT downgrade a veto. The helper's veto is correct; the LLM
    cannot soften it.
  - DO NOT use chain-of-thought; emit the JSON object directly.

OUTPUT (JSON only)
{
  "verdict": "<bullish|bearish|neutral|abstain>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<<=200 char one-liner naming the check that fired>",
  "observations": ["<check 1>", "..."]
}
"""


class RiskVoice:
    """LocalVoice that grades the bot's operational floor.

    v0.1 calls the LLM for contract uniformity; v0.2 will collapse
    into a pure-Python band via :func:`_compute_risk_band_deterministic`
    + ``VoiceOpinion.model_construct``. Both code paths produce the
    same shape — the seam is intentional.
    """

    voice_name: str = "risk_voice"

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

        # Deterministic veto computation — runs FIRST, NO LLM. If we
        # already see a hard veto, return without calling OpenRouter.
        # This guarantees the load-bearing safety checks never depend
        # on network availability or model nondeterminism.
        band, conf, reason = _compute_risk_band_deterministic(market_state, memory)
        elapsed_ms_local = int((time.monotonic() - started) * 1000)

        # 2026-05-20 founder patch: deterministic-only — no LLM ratify.
        # The LLM ratify path was over-vetoing on market sentiment (down
        # moves on JTO/JUP/PYTH at first poll → bearish despite zero real
        # risk signal). Trusted deterministic band is the right behavior:
        # risk_voice's job is hard-veto threshold checks, not market mood
        # reading (that's chart_analyst's job). The v0.2 collapse path
        # from the spec (§7.5) is now functionally complete.
        return VoiceOpinion(
            voice_name=self.voice_name,
            verdict=band,
            confidence=conf,
            reasoning=reason[:200],
            observations=[],
            raw_response="",
            elapsed_ms=elapsed_ms_local,
            cost_usd=None,
        )

        # NOTE: LLM ratify path below is preserved as dead code for the
        # contract-uniformity story in the spec. Re-enable by gating the
        # early return above behind a feature flag if we ever want it
        # back. As-is, the lines below never execute.

        # Non-veto path: still call the LLM for contract uniformity.
        # The model may escalate (helper missed a check) but never
        # downgrade per the prompt's RULE block.
        user_prompt = _build_user_prompt(market_state, band, conf, reason)
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
            logger.warning(
                "risk_voice: openrouter error %s; falling back to deterministic band",
                type(exc).__name__,
            )
            return VoiceOpinion(
                voice_name=self.voice_name,
                verdict=band,
                confidence=conf,
                reasoning=f"openrouter_error_fallback:{reason}"[:200],
                observations=[],
                raw_response="",
                elapsed_ms=int((time.monotonic() - started) * 1000),
                cost_usd=None,
            )

        elapsed_ms = response.elapsed_ms or int((time.monotonic() - started) * 1000)
        parsed = safe_parse_voice_json(response.content, self.voice_name)
        if parsed is None:
            # Parse failure: degrade to the deterministic band rather
            # than abstain — risk surface is always observable.
            return VoiceOpinion(
                voice_name=self.voice_name,
                verdict=band,
                confidence=conf,
                reasoning=f"parse_error_fallback:{reason}"[:200],
                observations=[],
                raw_response=response.content,
                elapsed_ms=elapsed_ms,
                cost_usd=response.cost_usd,
            )

        llm_verdict = _coerce_verdict(parsed.get("verdict"))
        llm_confidence = _coerce_confidence(parsed.get("confidence"))

        # Enforce the "NEVER downgrade a veto" rule on the server side
        # in case the LLM ignored its own prompt. If the helper said
        # bearish at high confidence, the LLM cannot soften it.
        if (
            band == "bearish"
            and conf >= _HEALTHY_CONFIDENCE
            and (llm_verdict != "bearish" or llm_confidence < conf)
        ):
            llm_verdict = "bearish"
            llm_confidence = max(llm_confidence, conf)

        return VoiceOpinion(
            voice_name=self.voice_name,
            verdict=llm_verdict,
            confidence=llm_confidence,
            reasoning=_coerce_str(parsed.get("reasoning"), 200),
            observations=_coerce_observations(parsed.get("observations")),
            raw_response=response.content,
            elapsed_ms=elapsed_ms,
            cost_usd=response.cost_usd,
        )


def _compute_risk_band_deterministic(
    market_state: dict[str, Any],
    memory: MemoryReader,
) -> tuple[Literal["bullish", "bearish", "neutral", "abstain"], float, str]:
    """Pure-Python risk band computation. v0.2 promote path.

    Returns ``(verdict, confidence, reason)`` with the same vocabulary
    as :class:`VoiceOpinion`. v0.2 wires this directly into
    ``VoiceOpinion.model_construct`` to skip the LLM round-trip entirely.

    Vetoes (in priority order):
      1. daily_trades >= max_daily_trades         -> ('bearish', 0.90, ...)
      2. open_position_count >= max_concurrent    -> ('bearish', 0.90, ...)
      3. total_spent_usd within $25 of cap        -> ('bearish', 0.85, ...)
      4. hourly_pnl_delta <= breaker threshold    -> ('bearish', 0.95, ...)
      5. consec_losses >= session_loss_pause      -> ('bearish', 0.90, ...)
      6. healthy                                  -> ('bullish', 0.70, ...)
    """
    # ``memory`` is unused in v0.1 but reserved — v0.2 can read the
    # last 5 ``position_close`` rows for a richer floor read.
    del memory

    if not isinstance(market_state, dict):
        return "abstain", 0.0, "malformed_risk_state"

    daily_trades = _safe_int(market_state.get("daily_trades"))
    max_daily = _safe_int(market_state.get("max_daily_trades"))
    open_pos = _safe_int(market_state.get("open_position_count"))
    max_conc = _safe_int(market_state.get("max_concurrent"))
    total_spent = _safe_float(market_state.get("total_spent_usd"))
    max_budget = _safe_float(market_state.get("max_budget_usd"))
    hourly_pnl = _safe_float(market_state.get("hourly_pnl_delta"))
    breaker_threshold = _safe_float(
        market_state.get("breaker_threshold_usd"), default=_HOURLY_BREAKER_BAND
    )
    consec_losses = _safe_int(market_state.get("consec_losses"))
    session_pause = _safe_int(market_state.get("session_loss_pause_threshold"))

    # Rule 1: daily-trade cap
    if max_daily > 0 and daily_trades >= max_daily:
        return "bearish", 0.90, f"daily_trades_cap_hit:{daily_trades}/{max_daily}"

    # Rule 2: concurrency cap
    if max_conc > 0 and open_pos >= max_conc:
        return "bearish", 0.90, f"concurrent_cap_hit:{open_pos}/{max_conc}"

    # Rule 3: budget headroom — within $25 of cap
    if max_budget > 0 and total_spent >= (max_budget - _BUDGET_HEADROOM_USD):
        return (
            "bearish",
            0.85,
            f"budget_headroom_low:${total_spent:.2f}/${max_budget:.2f}",
        )

    # Rule 4: hourly circuit breaker
    if hourly_pnl <= breaker_threshold:
        return (
            "bearish",
            0.95,
            f"hourly_breaker_tripped:pnl=${hourly_pnl:.2f}<=${breaker_threshold:.2f}",
        )

    # Rule 5: session loss pause
    if session_pause > 0 and consec_losses >= session_pause:
        return (
            "bearish",
            0.90,
            f"session_loss_pause:{consec_losses}/{session_pause}",
        )

    # Healthy floor.
    return "bullish", _HEALTHY_CONFIDENCE, "operational_floor_clean"


def _build_user_prompt(
    market_state: dict[str, Any],
    band: str,
    conf: float,
    reason: str,
) -> str:
    payload = {
        "precomputed_band": band,
        "precomputed_confidence": conf,
        "precomputed_reason": reason,
        "risk_state": {
            "daily_trades": _safe_int(market_state.get("daily_trades")),
            "max_daily_trades": _safe_int(market_state.get("max_daily_trades")),
            "consec_losses": _safe_int(market_state.get("consec_losses")),
            "session_loss_pause_threshold": _safe_int(
                market_state.get("session_loss_pause_threshold")
            ),
            "hourly_pnl_delta": _safe_float(market_state.get("hourly_pnl_delta")),
            "breaker_threshold_usd": _safe_float(
                market_state.get("breaker_threshold_usd"),
                default=_HOURLY_BREAKER_BAND,
            ),
            "total_spent_usd": _safe_float(market_state.get("total_spent_usd")),
            "max_budget_usd": _safe_float(market_state.get("max_budget_usd")),
            "open_position_count": _safe_int(market_state.get("open_position_count")),
            "max_concurrent": _safe_int(market_state.get("max_concurrent")),
        },
    }
    return f"Risk state:\n{json.dumps(payload, separators=(',', ':'))}\n\nRatify the band."


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


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


__all__ = [
    "DEFAULT_MODEL",
    "RiskVoice",
    "_compute_risk_band_deterministic",
]
