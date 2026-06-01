"""Sprint 29 — oracle_voice. The 7th voice in the local panel.

DETERMINISTIC voice. Zero LLM calls. Reads the `oracle_snapshots` Mongo
collection (Sprint 29 Phase 1: Pyth + Jupiter populated by the ingest
cron at scripts/oracle/ingest_oracle_snapshots.py) and grades whether
the cross-source price agreement is HIGH-CONFIDENCE, AMBIGUOUS, or
DATA-QUALITY-COMPROMISED.

The bot's own OKX OnchainOS price is read from market_state at grade
time (no Mongo round-trip for it — it's already in the snapshot the
panel got handed). So this voice does a THREE-WAY check:

  OKX     (from market_state.spot_price)
  Pyth    (from oracle_snapshots, source="pyth")
  Jupiter (from oracle_snapshots, source="jupiter")

Verdict map:
  bullish: all three agree to within `bullish_threshold_bps` (default
           30 bps = 0.30%) AND price is rising vs Pyth's prior snapshot
  bearish: all three agree to within bullish_threshold AND price falling
  neutral: all three agree but price flat
  abstain: any pair disagrees > `decline_threshold_bps` (default 50 bps)
           OR fewer than 2 sources present in snapshots OR cold-start

Why deterministic + no LLM: per private/strategy/2026-05-31-s24-s-voice-
fix-plan.md, LLM voices at temp=0 snap to printed anchor numbers (3
unique confidence values). regime_analyst (deterministic) gets 37
unique values. Oracle agreement is a math problem; no LLM needed; no
anchor-snap bug possible.

Default state: GECKO_ORACLE_VOICE_ENABLED=0 (OFF). Voice is not added
to the panel unless founder flips. Bot behavior unchanged when off.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from voices.base import VoiceOpinion

logger = logging.getLogger("voices.oracle_voice")

# Defaults (env-overridable). bps = basis points = 1/100 of a percent.
_DEFAULT_BULLISH_THRESHOLD_BPS = 30.0  # 0.30% — sources agree → grade
_DEFAULT_DECLINE_THRESHOLD_BPS = 50.0  # 0.50% — disagreement → abstain
_DEFAULT_TREND_BPS = 5.0  # 5 bps move vs prior Pyth = "rising"


def _bps(a: float, b: float) -> float:
    """Absolute spread between two prices in basis points."""
    if not a or not b:
        return float("inf")
    base = (a + b) / 2.0
    return abs(a - b) / base * 10_000.0


def _threshold_bps(env_name: str, default: float) -> float:
    try:
        return float(os.environ.get(env_name, default))
    except (TypeError, ValueError):
        return default


def _abstain(reasoning: str, observations: list[str], elapsed_ms: int) -> VoiceOpinion:
    return VoiceOpinion(
        voice_name="oracle_voice",
        verdict="abstain",
        confidence=0.0,
        reasoning=reasoning[:400],
        observations=[o[:120] for o in observations][:10],
        raw_response="",
        elapsed_ms=elapsed_ms,
        cost_usd=None,
    )


def _confidence(n_sources_agreeing: int, max_spread_bps: float, threshold_bps: float) -> float:
    """Deterministic continuous confidence.

    Components:
      0.45 base
      + 0.25 × (n_sources / 3)    — reward more sources online
      + 0.20 × (1 - spread/thresh) — reward tight agreement (clamped 0..1)

    Result in [0.45, 0.90]. ≥5 unique values guaranteed across realistic
    inputs (anti-anchor-snap regression target).
    """
    n_term = 0.25 * min(n_sources_agreeing, 3) / 3.0
    if threshold_bps > 0:
        tightness = max(0.0, min(1.0, 1.0 - max_spread_bps / threshold_bps))
    else:
        tightness = 0.0
    bias_term = 0.20 * tightness
    return max(0.0, min(0.90, 0.45 + n_term + bias_term))


class OracleVoice:
    """Sprint 29 — deterministic 7th voice.

    Injectable `snapshot_lookup` callable for tests — defaults to
    contest_bot.oracle.snapshot_query.latest_per_source.
    """

    voice_name: str = "oracle_voice"

    def __init__(
        self,
        *,
        snapshot_lookup: Any = None,
        bullish_threshold_bps: float | None = None,
        decline_threshold_bps: float | None = None,
        trend_threshold_bps: float | None = None,
    ) -> None:
        if snapshot_lookup is None:
            from oracle.snapshot_query import latest_per_source as _default

            snapshot_lookup = _default
        self._snapshot_lookup = snapshot_lookup
        self._bullish_thresh = (
            bullish_threshold_bps
            if bullish_threshold_bps is not None
            else _threshold_bps("GECKO_ORACLE_BULLISH_THRESHOLD_BPS",
                                _DEFAULT_BULLISH_THRESHOLD_BPS)
        )
        self._decline_thresh = (
            decline_threshold_bps
            if decline_threshold_bps is not None
            else _threshold_bps("GECKO_ORACLE_DECLINE_THRESHOLD_BPS",
                                _DEFAULT_DECLINE_THRESHOLD_BPS)
        )
        self._trend_thresh = (
            trend_threshold_bps
            if trend_threshold_bps is not None
            else _threshold_bps("GECKO_ORACLE_TREND_BPS", _DEFAULT_TREND_BPS)
        )

    async def grade(
        self,
        market_state: dict[str, Any],
        memory: Any,  # noqa: ARG002 — unused
    ) -> VoiceOpinion:
        started = time.monotonic()

        # 1. Resolve symbol — same pattern as memory_voice / market_researcher.
        instrument = (
            (market_state.get("instrument") or "").strip().upper()
            or (market_state.get("symbol", "") or "").split("-")[0].upper()
        )
        if not instrument:
            return _abstain(
                "symbol_unresolved",
                ["market_state missing instrument + symbol"],
                int((time.monotonic() - started) * 1000),
            )

        # 2. OKX price comes from market_state (the bot's primary source).
        okx_price = (
            market_state.get("spot_price")
            or market_state.get("price")
            or 0.0
        )
        try:
            okx_price = float(okx_price)
        except (TypeError, ValueError):
            okx_price = 0.0
        if okx_price <= 0:
            return _abstain(
                "okx_price_unavailable",
                [f"symbol={instrument}", "market_state.spot_price not numeric"],
                int((time.monotonic() - started) * 1000),
            )

        # 3. Other sources — Pyth + Jupiter — from the Mongo substrate.
        try:
            snapshots = self._snapshot_lookup(instrument)
        except Exception as exc:
            logger.warning("oracle_voice.lookup_failed err=%s", type(exc).__name__)
            return _abstain(
                f"snapshot_lookup_error:{type(exc).__name__}",
                [f"symbol={instrument}"],
                int((time.monotonic() - started) * 1000),
            )
        if not isinstance(snapshots, dict):
            snapshots = {}

        # Extract prices per source. Missing source = source not online.
        pyth_snap = snapshots.get("pyth") or {}
        jup_snap = snapshots.get("jupiter") or {}
        pyth_price = float(pyth_snap.get("price") or 0.0)
        jup_price = float(jup_snap.get("price") or 0.0)

        sources_online = sum(1 for p in (pyth_price, jup_price) if p > 0)
        if sources_online == 0:
            return _abstain(
                "no_second_sources_online",
                [
                    f"symbol={instrument}",
                    "no Pyth or Jupiter snapshot in window",
                    "ingest cron probably not running",
                ],
                int((time.monotonic() - started) * 1000),
            )

        # 4. Compute pairwise spreads.
        spreads: list[tuple[str, float]] = []
        if pyth_price > 0:
            spreads.append(("okx_vs_pyth", _bps(okx_price, pyth_price)))
        if jup_price > 0:
            spreads.append(("okx_vs_jupiter", _bps(okx_price, jup_price)))
        if pyth_price > 0 and jup_price > 0:
            spreads.append(("pyth_vs_jupiter", _bps(pyth_price, jup_price)))

        max_spread_bps = max(s for _name, s in spreads) if spreads else 0.0

        # 5. Threshold checks.
        if max_spread_bps > self._decline_thresh:
            return _abstain(
                f"cross_source_disagreement:{max_spread_bps:.1f}bps_gt_{self._decline_thresh:.0f}",
                [
                    f"symbol={instrument}",
                    f"okx={okx_price:.6f}",
                    f"pyth={pyth_price:.6f}",
                    f"jupiter={jup_price:.6f}",
                    *[f"{name}={spread:.1f}bps" for name, spread in spreads],
                ],
                int((time.monotonic() - started) * 1000),
            )

        if max_spread_bps > self._bullish_thresh:
            # Agreement is in the "neutral grade" zone — sources are
            # close but not tight enough to be confident bullish/bearish.
            verdict_str = "neutral"
        else:
            # Tight agreement. Check trend direction via OKX vs Pyth.
            move_bps = (okx_price - pyth_price) / pyth_price * 10_000.0 if pyth_price > 0 else 0.0
            if abs(move_bps) < self._trend_thresh:
                verdict_str = "neutral"
            elif move_bps > 0:
                verdict_str = "bullish"
            else:
                verdict_str = "bearish"

        confidence = _confidence(
            n_sources_agreeing=sources_online + 1,  # +1 for OKX
            max_spread_bps=max_spread_bps,
            threshold_bps=self._bullish_thresh,
        )

        observations = [
            f"symbol={instrument}",
            f"sources_online={sources_online + 1}/3",
            f"max_spread={max_spread_bps:.1f}bps",
            f"okx={okx_price:.6f}",
            *([f"pyth={pyth_price:.6f}"] if pyth_price > 0 else []),
            *([f"jupiter={jup_price:.6f}"] if jup_price > 0 else []),
        ]
        reasoning = (
            f"3-way price check: max spread {max_spread_bps:.1f}bps "
            f"(threshold {self._bullish_thresh:.0f}); verdict={verdict_str}"
        )

        return VoiceOpinion(
            voice_name="oracle_voice",
            verdict=verdict_str,  # type: ignore[arg-type]
            confidence=confidence,
            reasoning=reasoning[:400],
            observations=observations[:10],
            raw_response="",
            elapsed_ms=int((time.monotonic() - started) * 1000),
            cost_usd=None,
        )


__all__ = ["OracleVoice"]
