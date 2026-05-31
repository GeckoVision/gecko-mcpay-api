"""strategist_voice — pre-execution devil's-advocate voice.

Sprint 20 #1 (2026-05-28). Closes the architectural hole the founder
flagged: when the chart_analyst delivers a bullish signal, the trade
executor effectively says "ok, sounds good" and acts. There is no voice
on the local panel whose JOB is to challenge the bull thesis BEFORE the
trade fires.

This is the L2 counterpart to the PRD L1 Oracle's ``bull_bear_debater``
persona (``packages/gecko-core/.../trade_panel/personas.py``). The
PRD-tier debater runs adversarially during the 7-voice debate; the
local-lab panel needs the SAME shape but adapted to the bot's narrower
3-voice context (chart + memory + risk).

The strategist's contract is intentionally narrow:

- It NEVER returns ``bullish``. The voice's job is to challenge, not
  confirm. The strongest signal it can emit is ``neutral`` with high
  confidence — that says "I tried hard to break this thesis and could
  not find a defensible bear case."
- It returns ``bearish`` only when it can name a SPECIFIC falsifier
  the chart_analyst's bullish read does not address.
- It abstains only on data-quality issues (thin liquidity / stale
  feed / fewer than 24 bars) — mirroring the chart_analyst protocol.

Coordinator integration (deferred to S20 follow-up): the strategist's
verdict is NOT YET consumed by ``coordinator_rules.py`` for gating —
the coordinator file has uncommitted parallel work and we ship the
voice as observable-first per Pattern E. The strategist's opinion
surfaces in the artifact log + the bot dashboard's Agent Voices panel
+ the Sprint 20 Dissent: terminal line. Wiring it into the
``majority_vote`` rule chain is a clean additive change once the WIP
on ``coordinator_rules.py`` lands.

See ``private/strategy/2026-05-28-prd-moat-v0.2.md`` §4 (Strategist
devil's advocate = highest-leverage V0.2 net-new) and
``private/strategy/2026-05-28-product-journey-validate-then-promise.md``
(adversarial-layer hole as the Marina-visible wedge).
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

# Mirrors chart_analyst — the abstain-on-thin-liquidity protocol must be
# symmetric, otherwise the strategist would still be "bearish" on a
# zero-volume feed when chart_analyst correctly abstains.
_MAX_ZERO_VOL_BARS = 4


_SYSTEM_PROMPT = """You are the strategist on a local trading lab panel — the DEVIL'S ADVOCATE.

ROLE
The chart_analyst proposes a setup. Your job is to stress-test it. You
do not recommend trades. You do not confirm trades. You either name a
SPECIFIC, FALSIFIABLE problem with the setup ('bearish'), or you report
that you tried and could not break it ('neutral'). Both are useful
signal — neutral is NOT a failure mode, it is the strategist's way of
saying "no defensible falsifier found, proceed at chart_analyst's read."

INPUTS
You receive the same market snapshot the chart_analyst sees:
  (a) instrument + spot price,
  (b) 1h / 24h deltas + 24h range,
  (c) recent OHLCV bars (5m),
  (d) computed indicators (ADX, RSI, MFI, EMA stack, BB-width) +
      regime classification (TREND / CHOP / transitional).

DEFAULT VERDICT IS 'neutral'. You only escalate to 'bearish' when at
least ONE concrete falsifier below FIRES on the evidence in front of
you. The falsifiers are checked AS DESCRIBED — you do not pattern-match
'choppy market' to bearish; you check the named precondition.

CONCRETE FALSIFIER CLASSES (each requires BOTH listed conditions)
  1. CHOP-breakout fakeout: ADX <= 18 AND price closed above the
     trailing-24-bar high in the last 3 bars. Just "ADX is low" is NOT
     enough; the chart must show an actual breakout candle the
     chart_analyst could mistake for a setup. ADX low without a
     breakout candle = no setup proposed = nothing to challenge =
     verdict='neutral'.
  2. Exhausted momentum: RSI > 72 AND the last 5 bars are all green.
     A single elevated RSI print without a sustained up-streak is NOT
     exhaustion.
  3. Volume-divergence breakout: a breakout bar (new trailing-24-bar
     high in the last 3 bars) WHOSE volume is BELOW the 6-bar median.
     No breakout bar = falsifier does not apply.
  4. Structural downtrend: EMA9 < EMA21 < EMA50 (stacked DOWN) AND
     close is below EMA50. Just "EMAs not stacked up" is too weak;
     the stack must be inverted AND price below the longest EMA.
  5. Higher-timeframe contradiction: 1h regime is TREND-DOWN AND 5m
     shows a bullish breakout (rule 1's precondition). 1h CHOP alone
     is NOT a falsifier — it's just absence of higher-timeframe lift.
  6. Cohort risk: instrument is in a chronically losing cohort
     (mentioned in observations if memory_voice surfaced it).

If NONE of the six fire as described, return verdict='neutral'. Most
panel calls will land here — that is the correct behavior. The
strategist's value comes from being SELECTIVE about bearish; if you
fire bearish on every chop snapshot, you contribute no information
over chart_analyst's own chop-abstain.

CALL CONTRACT

Return JSON with this exact shape:
{
  "verdict":     "bearish" | "neutral" | "abstain",
  "confidence":  <float 0.0 to 1.0>,
  "reasoning":   "<=200 char one-liner naming the falsifier (or 'no defensible falsifier found')>",
  "observations": ["<bullet 1>", "<bullet 2>", "..."]
}

CRITICAL RULES:
  - You NEVER return verdict='bullish'. You are not a confirming voice.
  - verdict='neutral' is the DEFAULT. Use it whenever no specific
    falsifier fires AS DESCRIBED. Default-bearish is the failure mode.
  - verdict='bearish' MUST name which numbered falsifier fired AND
    quote the values that made it fire (e.g. "Falsifier 1: ADX=14.2
    + breakout candle at bar t-1 closed $0.182 above 24-bar high
    $0.180"). Vague unease does NOT justify bearish.
  - verdict='abstain' ONLY on data-quality. STRICT — abstain is the
    LAST resort, not a soft default. When in doubt, return 'neutral'.
    Abstain ONLY if ALL of the following are true:
      - fewer than 24 bars provided,
      - more than 4 of the 30 bars have zero volume (thin-liquidity flag),
      - the most recent bar is older than 10 minutes (stale feed),
      - ADX is unavailable for the entire snapshot.
    A SINGLE missing indicator (e.g. MFI is None but ADX/RSI/EMA are
    populated) is NOT abstain — return neutral and quote what you have.
    S24-S fix 2c: prior wording was being interpreted too liberally
    (41% abstain observed vs 24% neutral, violating the default-neutral
    contract).

Confidence anchors:
  bearish 0.55 - 0.65 = one falsifier fired, soft evidence
  bearish 0.65 - 0.75 = one falsifier fired, evidence quoted cleanly
  bearish 0.75 - 0.85 = multiple falsifiers converge — use sparingly
  >0.85               = structural rejection (regime + volume + timeframe
                        all adverse on the same bar) — very rare

  neutral 0.50 - 0.65 = no falsifier fires, but evidence is thin
  neutral 0.65 - 0.80 = no falsifier fires, evidence is clean
  neutral >0.80       = "I checked every falsifier; setup survives"
"""


class StrategistVoice:
    """LocalVoice — the panel's devil's advocate.

    Calls OpenRouter via the injected :class:`OpenRouterClient`. Mirrors
    the chart_analyst's sync-wrapped-async shape so the panel's
    ``asyncio.gather`` over voices stays honest.
    """

    voice_name: str = "strategist_voice"

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
        # memory unused (the strategist reads the same snapshot as the
        # chart_analyst — cohort lookups belong to memory_voice). The
        # Protocol still requires the arg.
        del memory

        started = time.monotonic()

        # Pre-LLM data-quality gate: if the indicator block can't be
        # computed (fewer than 30 bars or ADX unavailable), the
        # strategist has nothing to challenge — chart_analyst will
        # itself abstain on the same snapshot. Skip the LLM call and
        # abstain cleanly. Without this, the model invented falsifiers
        # from a thin candle table and returned bearish.
        if not _has_gradeable_indicators(market_state):
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return _abstain(
                reasoning="indicators_unavailable_or_insufficient_bars",
                raw_response="",
                elapsed_ms=elapsed_ms,
                cost_usd=None,
            )

        user_prompt = _build_user_prompt(market_state)
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
            logger.warning("strategist_voice: openrouter error %s", type(exc).__name__)
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

        verdict = _coerce_strategist_verdict(parsed.get("verdict"))
        confidence = _coerce_confidence(parsed.get("confidence"))
        reasoning = _coerce_str(parsed.get("reasoning"), max_len=200)
        observations = _coerce_observations(parsed.get("observations"))

        # Response-side double check on thin liquidity. Mirrors chart_analyst
        # §3.1 + §8.2 defense — without this, a strategist that returned
        # 'bearish' on a thin-feed setup would create a spurious veto.
        zero_vol_count = _count_zero_volume_bars(market_state)
        if zero_vol_count > _MAX_ZERO_VOL_BARS and verdict != "abstain":
            logger.info(
                "strategist_voice: model returned %s but %d zero-vol bars > %d; "
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
    """Build the strategist's adversarial prompt from the bot snapshot.

    Same input surface as chart_analyst — the strategist's challenge
    needs the same observable evidence the chart_analyst graded on.
    """
    instrument = str(market_state.get("instrument") or market_state.get("symbol") or "?")
    spot_price = _safe_float(market_state.get("spot_price"))
    change_1h = _safe_float(market_state.get("change_1h_pct"))
    change_24h = _safe_float(market_state.get("change_24h_pct"))
    range_24h = _safe_float(market_state.get("range_24h_pct"))

    bars = market_state.get("ohlcv_5m") or market_state.get("candles") or []
    bars = bars if isinstance(bars, list) else []
    ohlcv_table = _format_ohlcv_table(bars)
    indicators = _format_indicators(bars)
    regime_1h = market_state.get("regime_1h") or "?"

    return (
        f"Instrument: {instrument}\n"
        f"Spot: ${spot_price:.6f}\n"
        f"1h delta: {change_1h:+.2f}%\n"
        f"24h delta: {change_24h:+.2f}%\n"
        f"24h range: {range_24h:.2f}%\n"
        f"1h regime classification: {regime_1h}\n\n"
        f"{indicators}"
        f"Last 30 5m bars (oldest first):\n{ohlcv_table}\n\n"
        "Challenge the implicit bullish thesis. Cite a specific falsifier "
        "class if 'bearish'; return 'neutral' with high confidence if you "
        "tried hard and could not break the setup."
    )


def _format_indicators(bars: list[Any]) -> str:
    """Computed 5m indicators — same code path as chart_analyst's helper.

    Reusing chart_analyst's ``indicators`` module so the strategist
    reasons over the SAME numbers the chart_analyst graded on; otherwise
    the two voices could disagree on indicator math, which would be a
    confound disguised as adversarial value.
    """
    try:
        import indicators as _ind

        norm: list[dict] = []
        for b in bars:
            if isinstance(b, dict):
                norm.append(b)
            elif isinstance(b, (list, tuple)) and len(b) >= 6:
                norm.append(
                    {
                        "open": float(b[1]),
                        "high": float(b[2]),
                        "low": float(b[3]),
                        "close": float(b[4]),
                        "volume": float(b[5]),
                    }
                )
        if len(norm) < 30:
            return ""
        s = _ind.compute_latest(norm)
        if s.get("adx") is None or s.get("rsi") is None:
            return ""
        regime = "TREND" if s["adx"] >= 25 else ("CHOP" if s["adx"] <= 18 else "transitional")
        ema_stack = (
            "stacked-up (9>21>50)"
            if (
                s.get("ema9")
                and s.get("ema21")
                and s.get("ema50")
                and s["ema9"] > s["ema21"] > s["ema50"]
            )
            else "not-stacked"
        )
        mfi = s.get("mfi")
        bbw = s.get("bb_width")
        return (
            "Indicators (5m):\n"
            f"  ADX={s['adx']:.1f} ({regime})  RSI={s['rsi']:.1f}  "
            f"MFI={mfi:.1f}  EMA={ema_stack}  BBwidth={bbw:.2f}%\n"
            "  Falsifier guide: ADX<=18 = chop (breakouts fake); RSI>72 = "
            "exhausted (late entry); EMA not-stacked-up = structural downtrend; "
            "MFI<55 with a 'breakout' = no flow conviction.\n\n"
        )
    except Exception:
        return ""


def _format_ohlcv_table(bars: list[Any]) -> str:
    """Render bars as a compact table. Tolerates dict or sequence bars."""
    if not bars:
        return "(no bars provided)"

    rows: list[str] = ["ts                  open     high     low      close    volume"]
    for b in bars[-30:]:
        if isinstance(b, dict):
            ts = str(b.get("ts", b.get("timestamp", "")))[:19]
            o, h, low, c, v = (
                _safe_float(b.get("open")),
                _safe_float(b.get("high")),
                _safe_float(b.get("low")),
                _safe_float(b.get("close")),
                _safe_float(b.get("volume")),
            )
        elif isinstance(b, (list, tuple)) and len(b) >= 6:
            ts = str(b[0])[:19]
            o, h, low, c, v = (
                _safe_float(b[1]),
                _safe_float(b[2]),
                _safe_float(b[3]),
                _safe_float(b[4]),
                _safe_float(b[5]),
            )
        else:
            continue
        rows.append(f"{ts:<19} {o:<8.5f} {h:<8.5f} {low:<8.5f} {c:<8.5f} {v:.0f}")
    return "\n".join(rows)


def _has_gradeable_indicators(market_state: dict[str, Any]) -> bool:
    """Return True iff we have enough bars to compute ADX cleanly.

    S24-S fix 2c (2026-05-31): relaxed to require ADX-only. Previously
    required ADX AND RSI; the AND-gate combined with the prompt's
    over-liberal "indicator block missing or n/a" abstain clause to
    push the strategist to 41% abstain (vs the documented 24%-or-less
    target). A single missing indicator (e.g. RSI computation fluke on
    a thin bar) should NOT trigger abstain — let the LLM see what's
    available and return neutral. Only complete-ADX-failure (the load-
    bearing trend metric for the falsifier list) justifies skipping
    the LLM call.

    Mirrors the chart_analyst threshold (30 bars; the indicators module
    returns ``None`` for ADX until ~28 bars due to the smoothing).
    """
    bars = market_state.get("ohlcv_5m") or market_state.get("candles") or []
    if not isinstance(bars, list) or len(bars) < 24:
        return False
    try:
        import indicators as _ind

        norm: list[dict] = []
        for b in bars:
            if isinstance(b, dict):
                norm.append(b)
            elif isinstance(b, (list, tuple)) and len(b) >= 6:
                norm.append(
                    {
                        "open": float(b[1]),
                        "high": float(b[2]),
                        "low": float(b[3]),
                        "close": float(b[4]),
                        "volume": float(b[5]),
                    }
                )
        if len(norm) < 24:
            return False
        s = _ind.compute_latest(norm)
        # S24-S fix 2c — ADX-only (was ADX AND RSI). See docstring.
        return s.get("adx") is not None
    except Exception:
        return False


def _count_zero_volume_bars(market_state: dict[str, Any]) -> int:
    """Count zero-volume bars in the snapshot — for thin-liquidity defense."""
    bars = market_state.get("ohlcv_5m") or market_state.get("candles") or []
    if not isinstance(bars, list):
        return 0
    zero = 0
    for b in bars[-30:]:
        v: float = 0.0
        if isinstance(b, dict):
            v = _safe_float(b.get("volume"))
        elif isinstance(b, (list, tuple)) and len(b) >= 6:
            v = _safe_float(b[5])
        if v <= 0:
            zero += 1
    return zero


# ---- value coercions (mirror chart_analyst patterns) -----------------------


def _coerce_strategist_verdict(value: Any) -> VoiceVerdict:
    """Coerce a model-returned verdict, with the strategist-specific rule
    that 'bullish' is NEVER allowed — it gets downgraded to 'neutral'.

    The model's prompt forbids 'bullish' but gpt-4o-mini occasionally
    returns it anyway on cleanly-bullish setups (it pattern-matches to
    a normal analyst voice). Downgrade rather than reject — the model
    is signalling 'no falsifier found', which is exactly what 'neutral'
    means for the strategist.
    """
    if not isinstance(value, str):
        return "abstain"
    v = value.strip().lower()
    if v == "bullish":
        logger.info(
            "strategist_voice: model returned 'bullish' (forbidden for this voice); "
            "downgrading to 'neutral' — interpret as 'no falsifier found'"
        )
        return "neutral"
    if v in ("bearish", "neutral", "abstain"):
        return v  # type: ignore[return-value]
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
    text = value.strip()
    if len(text) > max_len:
        return text[:max_len]
    return text


def _coerce_observations(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:10]:
        s = str(item).strip()
        if s:
            out.append(s[:200])
    return out


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _abstain(
    *,
    reasoning: str,
    raw_response: str,
    elapsed_ms: int,
    cost_usd: float | None,
) -> VoiceOpinion:
    return VoiceOpinion(
        voice_name="strategist_voice",
        verdict="abstain",
        confidence=0.0,
        reasoning=reasoning,
        observations=[],
        raw_response=raw_response,
        elapsed_ms=elapsed_ms,
        cost_usd=cost_usd,
    )


__all__ = ["DEFAULT_MODEL", "StrategistVoice"]
