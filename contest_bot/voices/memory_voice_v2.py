"""memory_voice v2 — pure-Python feature-rule evaluator (Sprint 6 Phase C + Phase D).

Replaces v1's LLM-based memory-grading with a deterministic, zero-cost,
interpretable voice that reads:

1. **Symbol cohort** (from Phase B's 730d Binance backtest by-symbol
   stratification, PR #54). Half the universe was +EV; half was -EV. The
   cohort lists are baked in below. Trades on chronic -EV symbols get a
   bearish vote (capped soft so it doesn't dominate); trades on chronic
   +EV symbols get a mild bullish vote.

2. **Indicator exhaustion**: extreme RSI + MFI combinations that the
   autopsy (Sprint 6 Phase A) flagged as scratch/loss-class entries —
   e.g. RSI > 80 AND MFI > 95 = exhausted top, late entry.

3. **Realized outcomes** (preserved from v1) — recent close history on
   THIS instrument. If 3+ recent closes are net-positive, mild bullish.
   If net-negative, mild bearish. Recency-weighted.

Combination logic:
- Feature rules can OVERRIDE the realized-outcome signal (a "chronic
  -EV symbol" bearish vote wins over a mild "this instrument has been
  winning lately" bullish vote).
- Confidence is bounded ≤ 0.7 so the voice can never dominate the
  4-voice panel single-handedly.
- ABSTAIN if no rule fires AND insufficient outcomes — preserves v1's
  cold-start protocol.

NO LLM CALL. Pure Python. ~10ms latency vs v1's ~1500ms+ LLM RTT.

Per `private/strategy/2026-05-27-sprint-6-phase-b-counterfactual-findings.md`
for the cohort derivation. Per `private/strategy/2026-05-26-sprint-6-phase-a-trade-autopsy.md`
for the indicator-exhaustion finding (entry_dist_from_pre_high_pct > 2% wins
came clustered at extreme RSI/MFI values).
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
from dataclasses import dataclass
from typing import Any

from voices.base import MemoryReader, VoiceOpinion, VoiceVerdict

logger = logging.getLogger(__name__)

# ── Phase B by-symbol cohorts (PR #54) — BINANCE PERP UNIVERSE ───────────
# Top 10 +EV across 730d/50-coin Binance backtest, mean +EV.
PLUS_EV_COHORT: frozenset[str] = frozenset(
    {"RENDER", "ZEC", "ARB", "TAO", "ENA", "WLD", "ETH", "ICP", "INJ", "ONDO"}
)
# Bottom 10 -EV — chronic losers across the same backtest.
MINUS_EV_COHORT: frozenset[str] = frozenset(
    {"BCH", "EIGEN", "UNI", "SOL", "LINK", "BNB", "WLFI", "MMT", "TIA", "BTC"}
)

# ── Phase D #1 cohorts (PR #5x) — SOLANA DEX UNIVERSE ────────────────────
# Derived from 40 Solana-ecosystem tokens × 365d daily-momentum backtest
# (scripts/calibration/derive_solana_cohort.py). Train/test OOS validation
# (early-half train → late-half test) showed +195.9% lift from declining
# the chronic-loser cohort. 7/10 stable across train/test boundary.
#
# TIMESCALE CAVEAT (load-bearing — DO NOT IGNORE):
# This cohort is derived from a DAILY strategy (5d breakout lookback, 15d
# max hold). The live bot runs 30s polls. **Two of the live bot's autopsy
# WINNERS (WIF + PYTH) are in this MINUS_EV list.** The daily-strategy edge
# on these tokens doesn't necessarily transfer to the bot's intra-day
# strategy. To respect the empirical bot-evidence vs the daily-backtest
# signal, we use SOFT_SOLANA_* CONFIDENCE constants below — half the
# Binance cohort confidence. The vote contributes to the panel but does
# NOT dominate; other voices can override.
# Default cohorts (from Phase D #1, 2026-05-27, 365d derivation).
# Used IFF the rolling cohort JSON (Phase D #2) is missing or unreadable.
# Rolling re-derivation overwrites these via load_solana_cohorts_from_json().
_DEFAULT_SOLANA_PLUS_EV: frozenset[str] = frozenset(
    {"MUON", "GOOGLX", "CHZ", "KMNO", "ZEC", "CAKE", "DRIFT", "HIMSON", "GRASS", "PRIME"}
)
_DEFAULT_SOLANA_MINUS_EV: frozenset[str] = frozenset(
    {"WIF", "IO", "ATH", "VIRTUAL", "ORDI", "FIDA", "BIO", "PYTH", "FARTCOIN", "BONK"}
)


def _try_load_cohort_json(path: pathlib.Path) -> tuple[frozenset[str], frozenset[str]] | None:
    """Read a cohort result JSON; return (plus_ev, minus_ev) or None.

    JSON shape (matches scripts/calibration/derive_solana_cohort.py output):
        {"plus_ev_cohort": ["MUON", ...], "minus_ev_cohort": ["WIF", ...], ...}
    """
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        plus = data.get("plus_ev_cohort")
        minus = data.get("minus_ev_cohort")
        if not isinstance(plus, list) or not isinstance(minus, list):
            return None
        if not plus or not minus:
            return None
        return frozenset(str(s).upper() for s in plus), frozenset(str(s).upper() for s in minus)
    except (json.JSONDecodeError, OSError):
        return None


# Phase D #2: Solana cohort JSON path. Auto-loads at module import; falls
# back to _DEFAULT_* constants if missing. Rolling re-derivation (cron
# scheduled scripts/calibration/derive_rolling_solana_cohort.py) overwrites
# this file; next bot restart picks up the fresh cohort.
SOLANA_COHORT_JSON_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "scripts" / "calibration" / "data" / "solana" / "_cohort_result.json"
)
_loaded = _try_load_cohort_json(SOLANA_COHORT_JSON_PATH)
if _loaded is not None:
    SOLANA_PLUS_EV_COHORT, SOLANA_MINUS_EV_COHORT = _loaded
else:
    SOLANA_PLUS_EV_COHORT = _DEFAULT_SOLANA_PLUS_EV
    SOLANA_MINUS_EV_COHORT = _DEFAULT_SOLANA_MINUS_EV

# ── Indicator exhaustion thresholds ──────────────────────────────────────
# Per Phase A autopsy data:
#   PYTH #14 (RSI=76.0, MFI=99.3) → scratch    ← the canary case
#   WIF  #12 (RSI=82.4, MFI=63.0) → WIN       ← high RSI alone is fine
#   WIF  #4  (RSI=70.3, MFI=83.2) → win        ← moderate combo is fine
#   WIF  #11 (RSI=70.0, MFI=66.2) → win        ← neither extreme = fine
# Rule: BOTH must be elevated AND MFI must be extreme. Thresholds chosen
# to fire on PYTH #14 but NOT on the WIF wins:
#   RSI >= 75 (captures PYTH 76 + WIF 70-72 boundary)
#   MFI >= 90 (captures PYTH 99.3 but not WIF 83.2)
# Combined: "buyers are clearly exhausted on both momentum + flow."
RSI_EXHAUSTION_THRESHOLD = 75.0
MFI_EXHAUSTION_THRESHOLD = 90.0

# ── Realized-outcome thresholds (v1 carry-over) ──────────────────────────
COLD_START_MIN_OUTCOMES = 3
MEMORY_WINDOW = 20
REALIZED_MIN_PNL_PCT = 0.5  # matches bot's MIN_REALIZED_WIN_PCT (Fix 2)

# ── Confidence caps ──────────────────────────────────────────────────────
COHORT_BEARISH_CONFIDENCE = 0.65  # chronic -EV symbol → bearish (Binance cohort)
COHORT_BULLISH_CONFIDENCE = 0.55  # chronic +EV symbol → mild bullish (Binance cohort)
# Solana cohort: SOFTER per timescale-mismatch caveat above. Vote influences
# the panel but doesn't auto-decline; other voices can override.
SOLANA_COHORT_BEARISH_CONFIDENCE = 0.40
SOLANA_COHORT_BULLISH_CONFIDENCE = 0.40
EXHAUSTION_BEARISH_CONFIDENCE = 0.70  # max — never dominates 4-voice panel
REALIZED_CONFIDENCE = 0.55


@dataclass
class _RuleResult:
    verdict: VoiceVerdict
    confidence: float
    rule: str
    observation: str

    def __bool__(self) -> bool:
        return self.verdict != "abstain"


class MemoryVoiceV2:
    """Pure-Python feature-rule memory voice — Phase C (Sprint 6).

    The voice is intentionally narrow: it does NOT analyze market structure
    (that's chart_analyst) and does NOT compute risk gates (that's
    risk_voice). It reads two memory layers — historical-cohort statistics
    + this-instrument realized history — and votes accordingly.
    """

    voice_name: str = "memory_voice"  # keep the same wire-name as v1

    def __init__(
        self,
        *,
        plus_ev_cohort: frozenset[str] = PLUS_EV_COHORT,
        minus_ev_cohort: frozenset[str] = MINUS_EV_COHORT,
        solana_plus_ev_cohort: frozenset[str] = SOLANA_PLUS_EV_COHORT,
        solana_minus_ev_cohort: frozenset[str] = SOLANA_MINUS_EV_COHORT,
        rsi_exhaustion_threshold: float = RSI_EXHAUSTION_THRESHOLD,
        mfi_exhaustion_threshold: float = MFI_EXHAUSTION_THRESHOLD,
        cold_start_min_outcomes: int = COLD_START_MIN_OUTCOMES,
        memory_window: int = MEMORY_WINDOW,
    ) -> None:
        self._plus_ev = plus_ev_cohort
        self._minus_ev = minus_ev_cohort
        self._solana_plus_ev = solana_plus_ev_cohort
        self._solana_minus_ev = solana_minus_ev_cohort
        self._rsi_threshold = rsi_exhaustion_threshold
        self._mfi_threshold = mfi_exhaustion_threshold
        self._cold_start = cold_start_min_outcomes
        self._window = memory_window

    async def grade(
        self,
        market_state: dict[str, Any],
        memory: MemoryReader,
    ) -> VoiceOpinion:
        started = time.monotonic()
        symbol = _normalize_symbol(market_state)
        indicators = market_state.get("indicators") or {}
        observations: list[str] = []

        # Run all rules; collect ALL results. Then combine.
        rules: list[_RuleResult] = []

        # Rule 1: chronic -EV cohort (HIGHEST priority — override realized signal)
        if symbol in self._minus_ev:
            rules.append(
                _RuleResult(
                    verdict="bearish",
                    confidence=COHORT_BEARISH_CONFIDENCE,
                    rule="chronic_minus_ev_cohort",
                    observation=f"{symbol} in chronic -EV cohort (Phase B 730d backtest, Binance)",
                )
            )

        # Rule 1b: Solana-DEX chronic -EV cohort (SOFTER — see timescale caveat
        # at module top). For the live bot which trades JTO/JUP/WIF/PYTH/RAY,
        # this is the cohort rule that ACTUALLY FIRES.
        if symbol in self._solana_minus_ev:
            rules.append(
                _RuleResult(
                    verdict="bearish",
                    confidence=SOLANA_COHORT_BEARISH_CONFIDENCE,
                    rule="chronic_solana_minus_ev_cohort",
                    observation=f"{symbol} in chronic -EV Solana cohort (Phase D 365d daily-momentum sim)",
                )
            )

        # Rule 2: indicator exhaustion (override realized signal)
        rsi = _safe_float(indicators.get("rsi"))
        mfi = _safe_float(indicators.get("mfi"))
        if (
            rsi is not None
            and mfi is not None
            and rsi >= self._rsi_threshold
            and mfi >= self._mfi_threshold
        ):
            rules.append(
                _RuleResult(
                    verdict="bearish",
                    confidence=EXHAUSTION_BEARISH_CONFIDENCE,
                    rule="indicator_exhaustion",
                    observation=f"RSI={rsi:.1f} MFI={mfi:.1f} both extreme — exhausted top",
                )
            )

        # Rule 3: chronic +EV cohort (mild bullish)
        if symbol in self._plus_ev:
            rules.append(
                _RuleResult(
                    verdict="bullish",
                    confidence=COHORT_BULLISH_CONFIDENCE,
                    rule="chronic_plus_ev_cohort",
                    observation=f"{symbol} in chronic +EV cohort (Phase B 730d backtest, Binance)",
                )
            )

        # Rule 3b: Solana-DEX chronic +EV cohort (SOFTER — same timescale caveat)
        if symbol in self._solana_plus_ev:
            rules.append(
                _RuleResult(
                    verdict="bullish",
                    confidence=SOLANA_COHORT_BULLISH_CONFIDENCE,
                    rule="chronic_solana_plus_ev_cohort",
                    observation=f"{symbol} in chronic +EV Solana cohort (Phase D 365d daily-momentum sim)",
                )
            )

        # Rule 4: realized-outcome history (carry-over from v1)
        realized_rule = self._evaluate_realized_outcomes(symbol, memory)
        if realized_rule is not None:
            rules.append(realized_rule)
            observations.append(realized_rule.observation)

        # ── Combine rules ────────────────────────────────────────────────
        # Bearish rules WIN over bullish (defensive bias — preserve capital).
        # Highest-confidence rule of the winning side carries the vote.
        bearish = [r for r in rules if r.verdict == "bearish"]
        bullish = [r for r in rules if r.verdict == "bullish"]

        if bearish:
            chosen = max(bearish, key=lambda r: r.confidence)
            reasoning = f"v2:{chosen.rule}"
            observations.insert(0, chosen.observation)
            return self._build_opinion(
                verdict="bearish",
                confidence=chosen.confidence,
                reasoning=reasoning,
                observations=observations,
                elapsed_ms=_elapsed_ms(started),
            )

        if bullish:
            chosen = max(bullish, key=lambda r: r.confidence)
            reasoning = f"v2:{chosen.rule}"
            observations.insert(0, chosen.observation)
            return self._build_opinion(
                verdict="bullish",
                confidence=chosen.confidence,
                reasoning=reasoning,
                observations=observations,
                elapsed_ms=_elapsed_ms(started),
            )

        # No rule fired → abstain (cold start / no signal)
        return self._build_opinion(
            verdict="abstain",
            confidence=0.0,
            reasoning="v2:no_rule_fired",
            observations=observations,
            elapsed_ms=_elapsed_ms(started),
        )

    def _evaluate_realized_outcomes(
        self, symbol: str, memory: MemoryReader
    ) -> _RuleResult | None:
        """Read recent position_close rows for this instrument; vote on outcome distribution.

        Mirrors v1's read pattern but without the LLM. Recency-weighted mean
        of pnl_pct over the last MEMORY_WINDOW closes on THIS symbol.
        """
        try:
            rows = memory.recent(event_filter=("position_close",), limit=self._window)
        except Exception as exc:
            logger.warning("memory_voice_v2: memory.recent raised %s", type(exc).__name__)
            return None

        # Filter to this symbol only
        symbol_rows: list[tuple[float, float]] = []  # (pnl_pct, recency_weight)
        for i, row in enumerate(rows):
            payload = row.get("payload") or {}
            row_sym = _normalize_symbol_from_payload(payload)
            if row_sym != symbol:
                continue
            pnl = _safe_float(payload.get("pnl_pct"))
            if pnl is None:
                continue
            # Recency weight: newest=1.0, decay 0.9 per position back
            weight = 0.9 ** i
            symbol_rows.append((pnl, weight))

        if len(symbol_rows) < self._cold_start:
            return None

        # Weighted mean PnL on this symbol's recent closes
        total_weight = sum(w for _, w in symbol_rows)
        if total_weight <= 0:
            return None
        weighted_mean = sum(pnl * w for pnl, w in symbol_rows) / total_weight

        if weighted_mean >= REALIZED_MIN_PNL_PCT:
            return _RuleResult(
                verdict="bullish",
                confidence=REALIZED_CONFIDENCE,
                rule="realized_outcomes_positive",
                observation=(
                    f"recent {len(symbol_rows)} closes on {symbol}: weighted mean "
                    f"{weighted_mean:+.2f}% (>= {REALIZED_MIN_PNL_PCT}%)"
                ),
            )
        if weighted_mean <= -REALIZED_MIN_PNL_PCT:
            return _RuleResult(
                verdict="bearish",
                confidence=REALIZED_CONFIDENCE,
                rule="realized_outcomes_negative",
                observation=(
                    f"recent {len(symbol_rows)} closes on {symbol}: weighted mean "
                    f"{weighted_mean:+.2f}% (<= -{REALIZED_MIN_PNL_PCT}%)"
                ),
            )
        return None

    def _build_opinion(
        self,
        *,
        verdict: VoiceVerdict,
        confidence: float,
        reasoning: str,
        observations: list[str],
        elapsed_ms: int,
    ) -> VoiceOpinion:
        return VoiceOpinion(
            voice_name=self.voice_name,
            verdict=verdict,
            confidence=confidence,
            reasoning=reasoning[:200],
            observations=[o[:200] for o in observations[:5]],
            raw_response="",  # no LLM call; raw_response empty
            elapsed_ms=elapsed_ms,
            cost_usd=0.0,  # zero LLM spend
        )


# ── helpers ──────────────────────────────────────────────────────────────


def _normalize_symbol(market_state: dict[str, Any]) -> str:
    """Pull the symbol from market_state. Accept 'instrument' or 'symbol' key.

    Symbols come in shapes like 'JTO-USDC' or 'JTO'. Strip USDC suffix.
    """
    raw = (
        market_state.get("instrument")
        or market_state.get("symbol")
        or ""
    )
    return str(raw).split("-")[0].upper()


def _normalize_symbol_from_payload(payload: dict[str, Any]) -> str:
    """Same shape as _normalize_symbol but reads from a memory-row payload."""
    raw = payload.get("symbol") or payload.get("instrument") or ""
    return str(raw).split("-")[0].upper()


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def would_decline_for_backtest(
    symbol: str,
    rsi: float | None = None,
    mfi: float | None = None,
    *,
    plus_ev_cohort: frozenset[str] = PLUS_EV_COHORT,
    minus_ev_cohort: frozenset[str] = MINUS_EV_COHORT,
    rsi_threshold: float = RSI_EXHAUSTION_THRESHOLD,
    mfi_threshold: float = MFI_EXHAUSTION_THRESHOLD,
) -> bool:
    """Sync wrapper for the v2 BINANCE cohort + exhaustion rules.

    Returns True if v2 would vote bearish on this entry candidate (HARD
    confidence sufficient to drive a decline). Used by the Phase C backtest
    validation (scripts/analysis/backtest/ runner with --with-v2-rules).

    Excludes the realized-outcomes path because backtest entries have no
    live ledger history. Excludes the SOLANA cohort because at SOFT
    confidence (0.40) it doesn't drive a decline by itself; the Solana
    cohort is informational/influential, not gating, at the backtest layer.

    Decision tree mirrors MemoryVoiceV2.grade() for the HARD-confidence rules:
    - Binance chronic -EV cohort symbol → True (decline)
    - Indicator exhaustion (RSI + MFI both elevated) → True (decline)
    - Else → False (allow)
    """
    norm = str(symbol).split("-")[0].upper()
    if norm in minus_ev_cohort:
        return True
    if (
        rsi is not None
        and mfi is not None
        and rsi >= rsi_threshold
        and mfi >= mfi_threshold
    ):
        return True
    return False


__all__ = [
    "COHORT_BEARISH_CONFIDENCE",
    "COHORT_BULLISH_CONFIDENCE",
    "EXHAUSTION_BEARISH_CONFIDENCE",
    "MFI_EXHAUSTION_THRESHOLD",
    "MINUS_EV_COHORT",
    "MemoryVoiceV2",
    "PLUS_EV_COHORT",
    "RSI_EXHAUSTION_THRESHOLD",
    "SOLANA_COHORT_BEARISH_CONFIDENCE",
    "SOLANA_COHORT_BULLISH_CONFIDENCE",
    "SOLANA_MINUS_EV_COHORT",
    "SOLANA_PLUS_EV_COHORT",
    "would_decline_for_backtest",
]
