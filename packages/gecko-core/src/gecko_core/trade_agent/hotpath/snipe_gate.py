"""Snipe gate (B1) — the multi-signal launch-integrity classifier.

The novel core of the wedge. Jito sees one bundle at submit-time; contract
scanners see one snapshot; NOBODY fuses behavioral signals across wallets, slots,
and pools to decide whether a launch's demand is real. This module is that fusion.

It composes the tells the firewall already has primitives for into ONE scored
``launch_integrity`` verdict:

* **same-slot co-buy** — N distinct wallets buying one thin pool in a single ~400ms
  slot (no organic crowd produces that).
* **Jito-bundle buys** — buys that paid a tip account (``hotpath.jito.is_jito_bundle_tx``)
  — categorically automated.
* **fresh-wallet swarm** — buyers whose accounts were created <48h before launch.
* **fee/tip outlier** — top buy tip at/above the live p95 tip floor
  (``hotpath.jito_tips.TipFloor``).
* **uniform sizing** — bot loops use tight, identical sizes (fat-tailed = organic).
* **LP drain** — the inflate-then-dump tail (large buys → reserve drop → same
  wallets exit).

Pure + deterministic (``pydantic``/stdlib only): takes a :class:`SnipeSnapshot`
of already-extracted features + an optional live tip floor, returns a
:class:`SnipeBlock`. The feature extraction (per-wallet, per-slot, account-age)
rides the parsed-transaction ingest path (deferred); this scorer is the brain and
is falsifiable today against synthetic snapshots (Pattern B). Mirrors the
``wash_signals`` discipline: FP guards inline, fail-OPEN, honest labels.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from gecko_core.trade_agent.hotpath.jito_tips import TipFloor

SnipeLabel = str  # "clean" | "suspicious" | "likely_sniped" | "confirmed_wash"

# --- tunables (single canonical place — Pattern A) -------------------------- #
FRESH_WALLET_MAX_AGE_S = 48 * 3600  # a buyer wallet younger than this is "fresh"
CO_BUY_MIN = 3  # ≥ this many distinct buyers in one slot = a co-buy cluster
CO_BUY_SATURATION = 6  # co-buy contribution maxes out here
FEE_OUTLIER_PCTILE = "p95"  # a top buy tip at/above this floor = urgency
FRESH_RATIO_FLAG = 0.5  # ≥ half the buyers are fresh = swarm

# Per-signal weights (Jito-map I1). Jito-bundle presence is the highest-precision
# tell; co-buy alone is the weakest (organic hype also clusters).
W_JITO_BUNDLE = 0.40
W_FRESH_SWARM = 0.25
W_FEE_OUTLIER = 0.20
W_CO_BUY = 0.15
W_LP_DRAIN = 0.45  # the inflate-then-dump tail — strong on its own

LABEL_SUSPICIOUS = 0.30
LABEL_LIKELY_SNIPED = 0.65

# Launch FP guard: a genuine hyped fair launch is also buy-clustered + thin in
# the first hour. Below this age, a LONE co-buy signal never escalates — it needs
# corroboration from an automation tell (jito / fresh-swarm / fee-outlier).
LAUNCH_AGE_S = 3600.0


class SnipeSnapshot(BaseModel):
    """Already-extracted per-launch features (the parsed-tx path fills these)."""

    model_config = ConfigDict(extra="forbid")

    mint: str
    age_seconds: float | None = Field(default=None, ge=0.0)
    buyer_count: int = Field(default=0, ge=0, description="distinct buyers observed.")
    max_slot_unique_buyers: int = Field(
        default=0, ge=0, description="most distinct buyers in any single slot (co-buy)."
    )
    jito_bundle_buys: int = Field(
        default=0, ge=0, description="buys that paid a Jito tip account (is_jito_bundle_tx)."
    )
    fresh_wallet_buyers: int = Field(
        default=0, ge=0, description="buyers whose wallet age < FRESH_WALLET_MAX_AGE_S."
    )
    max_buy_tip_sol: float | None = Field(
        default=None, ge=0.0, description="top tip/priority among launch buys (SOL)."
    )
    notional_p50: float | None = Field(default=None, ge=0.0)
    notional_p95: float | None = Field(default=None, ge=0.0)
    lp_drained: bool = Field(
        default=False, description="large buys → reserve drop → same wallets exit."
    )


class SnipeBlock(BaseModel):
    """Fused launch-integrity verdict."""

    model_config = ConfigDict(extra="forbid")

    score: float = Field(..., ge=0.0, le=1.0)
    label: SnipeLabel = Field(
        ..., description="clean / suspicious / likely_sniped / confirmed_wash."
    )
    reasons: list[str] = Field(default_factory=list)
    fired_signals: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class _Sig:
    fired: bool
    code: str
    weight: float
    reason: str | None


def _has_inputs(s: SnipeSnapshot) -> bool:
    return bool(
        s.buyer_count
        or s.max_slot_unique_buyers
        or s.jito_bundle_buys
        or s.fresh_wallet_buyers
        or s.lp_drained
        or s.max_buy_tip_sol
    )


def _co_buy(s: SnipeSnapshot) -> _Sig:
    code = "same_slot_co_buy"
    if s.max_slot_unique_buyers < CO_BUY_MIN:
        return _Sig(False, code, W_CO_BUY, None)
    # scale 0..1 between CO_BUY_MIN and CO_BUY_SATURATION
    span = max(1, CO_BUY_SATURATION - CO_BUY_MIN)
    frac = min(1.0, (s.max_slot_unique_buyers - CO_BUY_MIN) / span + 1.0 / span)
    return _Sig(
        True,
        code,
        W_CO_BUY * frac,
        f"{s.max_slot_unique_buyers} distinct buyers in one slot",
    )


def _jito_bundle(s: SnipeSnapshot) -> _Sig:
    code = "jito_bundle_snipe"
    if s.jito_bundle_buys <= 0:
        return _Sig(False, code, W_JITO_BUNDLE, None)
    return _Sig(
        True,
        code,
        W_JITO_BUNDLE,
        f"{s.jito_bundle_buys} buy(s) submitted via a Jito bundle (tip account paid) — automated",
    )


def _fresh_swarm(s: SnipeSnapshot) -> _Sig:
    code = "fresh_wallet_swarm"
    if s.buyer_count <= 0 or s.fresh_wallet_buyers <= 0:
        return _Sig(False, code, W_FRESH_SWARM, None)
    ratio = s.fresh_wallet_buyers / s.buyer_count
    if ratio < FRESH_RATIO_FLAG:
        return _Sig(False, code, W_FRESH_SWARM, None)
    return _Sig(
        True,
        code,
        W_FRESH_SWARM * min(1.0, ratio),
        f"{s.fresh_wallet_buyers}/{s.buyer_count} buyers on wallets <48h old",
    )


def _fee_outlier(s: SnipeSnapshot, tip_floor: TipFloor | None) -> _Sig:
    code = "fee_tip_outlier"
    if tip_floor is None or s.max_buy_tip_sol is None:
        return _Sig(False, code, W_FEE_OUTLIER, None)
    if not tip_floor.is_outlier(s.max_buy_tip_sol, at=FEE_OUTLIER_PCTILE):
        return _Sig(False, code, W_FEE_OUTLIER, None)
    return _Sig(
        True,
        code,
        W_FEE_OUTLIER,
        f"top buy tip {s.max_buy_tip_sol:.6g} SOL at/above the live {FEE_OUTLIER_PCTILE} tip floor",
    )


def _lp_drain(s: SnipeSnapshot) -> _Sig:
    code = "lp_drain"
    if not s.lp_drained:
        return _Sig(False, code, W_LP_DRAIN, None)
    return _Sig(
        True, code, W_LP_DRAIN, "inflate-then-drain: reserves dropped + early buyers exited"
    )


def _label_for(score: float, *, lp_drained: bool) -> str:
    if lp_drained and score >= LABEL_LIKELY_SNIPED:
        return "confirmed_wash"
    if score >= LABEL_LIKELY_SNIPED:
        return "likely_sniped"
    if score >= LABEL_SUSPICIOUS:
        return "suspicious"
    return "clean"


def assess_snipe(snap: SnipeSnapshot, tip_floor: TipFloor | None = None) -> SnipeBlock | None:
    """Fuse the snipe signals into one launch-integrity verdict.

    Returns ``None`` (fail-OPEN) when there's nothing to assess. Launch FP guard:
    for a token younger than :data:`LAUNCH_AGE_S`, a lone co-buy signal (organic
    hype also clusters early) does not escalate — it needs corroboration from an
    automation tell (jito / fresh-swarm / fee-outlier / lp-drain).
    """
    if not _has_inputs(snap):
        return None

    sigs = [
        _jito_bundle(snap),
        _fresh_swarm(snap),
        _fee_outlier(snap, tip_floor),
        _co_buy(snap),
        _lp_drain(snap),
    ]
    fired = [s for s in sigs if s.fired]
    if not fired:
        return SnipeBlock(
            score=0.0,
            label="clean",
            reasons=["no snipe/bot launch signals fired"],
            fired_signals=[],
        )

    # Launch guard: drop a lone co-buy on a fresh token (organic-hype false positive).
    at_launch = snap.age_seconds is not None and snap.age_seconds < LAUNCH_AGE_S
    if at_launch and {s.code for s in fired} == {"same_slot_co_buy"}:
        return SnipeBlock(
            score=0.0,
            label="clean",
            reasons=["co-buy at launch without automation corroboration — likely organic hype"],
            fired_signals=[],
        )

    score = min(1.0, sum(s.weight for s in fired))
    return SnipeBlock(
        score=round(score, 4),
        label=_label_for(score, lp_drained=snap.lp_drained),
        reasons=[s.reason for s in fired if s.reason],
        fired_signals=[s.code for s in fired],
    )


__all__ = ["SnipeBlock", "SnipeLabel", "SnipeSnapshot", "assess_snipe"]
