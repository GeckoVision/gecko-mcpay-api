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
* **concentrated capture** — the residual fingerprint that survives every
  automation tell being OFF (slot-spread + no tip + no shared ALT + multi-hop
  funding + randomized sizing): a few wallets capturing a disproportionate share
  of one-sided early buy volume. You can hide the *mechanism*; you cannot
  simultaneously *capture the float* AND *look like a diverse organic crowd*. The
  diversity-deficit (few wallets buying many times, not many wallets buying once)
  is the discriminator vs a genuinely hyped fair launch.

Pure + deterministic (``pydantic``/stdlib only): takes a :class:`SnipeSnapshot`
of already-extracted features + an optional live tip floor, returns a
:class:`SnipeBlock`. The feature extraction (per-wallet, per-slot, account-age)
is built by :func:`snipe_features.build_snipe_snapshot` from parsed swaps; the
only deferred piece is the live Helius adapter that produces those parsed swaps.
This scorer is the brain and is falsifiable today against synthetic snapshots
(Pattern B). Mirrors the ``wash_signals`` discipline: FP guards inline,
fail-OPEN, honest labels.
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
W_UNKNOWN_PROGRAM = (
    0.20  # buy routed through a first-seen custom program (I2) — sniper-program tell
)
W_SHARED_ALT = 0.25  # distinct buyers sharing an execution rig (ALT) — survives funder laundering
W_CO_BUY = 0.15
W_LP_DRAIN = 0.45  # the inflate-then-dump tail — strong on its own

# Concentrated-capture (the residual that survives every automation tell off). W
# is tuned so the signal reaches `suspicious` ALONE (raises the floor from clean —
# the honest win) and escalates to `block` WITH any corroborating tell (see
# _concentration_corroborated). High enough to be decisive when fused; never a
# block on its own except in the EXTREME tier below.
W_CONCENTRATION = 0.30
CONC_T = 0.60  # top-5 buyers hold ≥60% of buy notional = float-capture concentration
ONESIDE_T = 0.90  # buy_notional/(buy+sell) ≥0.90 = pure accumulation, no discovery
DIV_T = 1.5  # buy_count/buyer_count ≥1.5 = diversity-deficit (few wallets, many buys)
MIN_CONC_BUYERS = 5  # never fire on a trivial 1-4 buyer pool (noise)
# EXTREME tier: a near-single-wallet, near-zero-sell capture. No fair launch looks
# like this; it blocks ALONE (even at launch), like lp_drain's escalation.
EXTREME_CONC_T = 0.85
EXTREME_ONESIDE_T = 0.97

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
    unknown_program_buys: int = Field(
        default=0,
        ge=0,
        description="buys routed through a first-seen/unknown custom program (I2 attribution).",
    )
    shared_alt_buyers: int = Field(
        default=0,
        ge=0,
        description="distinct buyers sharing a non-public ALT (same execution rig).",
    )
    buy_count: int = Field(
        default=0,
        ge=0,
        description="number of buy swaps (vs buyer_count = distinct buyers); ratio = diversity-deficit.",
    )
    top_buyer_share: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="top-5 buyers' share of total BUY notional (float-capture concentration).",
    )
    one_sided_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="buy_notional / (buy_notional + sell_notional); →1.0 = pure accumulation.",
    )
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
        or s.unknown_program_buys
        or s.shared_alt_buyers
        or s.lp_drained
        or s.max_buy_tip_sol
        or s.top_buyer_share
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


def _unknown_program(s: SnipeSnapshot) -> _Sig:
    code = "unknown_program_route"
    if s.unknown_program_buys <= 0:
        return _Sig(False, code, W_UNKNOWN_PROGRAM, None)
    return _Sig(
        True,
        code,
        W_UNKNOWN_PROGRAM,
        f"{s.unknown_program_buys} buy(s) routed through a first-seen/unknown custom program",
    )


def _shared_alt(s: SnipeSnapshot) -> _Sig:
    code = "shared_alt_rig"
    if s.shared_alt_buyers < 2:
        return _Sig(False, code, W_SHARED_ALT, None)
    return _Sig(
        True,
        code,
        W_SHARED_ALT,
        f"{s.shared_alt_buyers} buyers share a custom address-lookup-table (same execution rig)",
    )


def _lp_drain(s: SnipeSnapshot) -> _Sig:
    code = "lp_drain"
    if not s.lp_drained:
        return _Sig(False, code, W_LP_DRAIN, None)
    return _Sig(
        True, code, W_LP_DRAIN, "inflate-then-drain: reserves dropped + early buyers exited"
    )


def _concentrated_capture(s: SnipeSnapshot) -> _Sig:
    """The residual fingerprint: float-capture concentration without diversity.

    Survives every automation tell being off (slot-spread, no tip, no shared ALT,
    multi-hop funding, randomized sizing). FIRES when a few wallets hold a
    disproportionate share of one-sided early buy volume AND the buys come from
    few wallets buying many times (the diversity-deficit) — NOT from a diverse
    crowd. The diversity-deficit gate is the key FP discriminator: a real hyped
    fair launch has many distinct buyers each buying ~once (ratio →1, below DIV_T)
    so it does NOT fire; a capture loop is few wallets buying many times (ratio
    high) so it fires.
    """
    code = "concentrated_capture"
    if (
        s.buyer_count < MIN_CONC_BUYERS
        or s.top_buyer_share is None
        or s.one_sided_ratio is None
        or s.buyer_count <= 0
    ):
        return _Sig(False, code, W_CONCENTRATION, None)
    diversity_deficit = s.buy_count / s.buyer_count
    if not (
        s.top_buyer_share >= CONC_T
        and s.one_sided_ratio >= ONESIDE_T
        and diversity_deficit >= DIV_T
    ):
        return _Sig(False, code, W_CONCENTRATION, None)
    return _Sig(
        True,
        code,
        W_CONCENTRATION,
        (
            f"top-5 buyers hold {s.top_buyer_share:.0%} of buy notional, "
            f"{s.one_sided_ratio:.0%} one-sided, {diversity_deficit:.1f} buys/buyer "
            f"(few wallets capturing the float — not an organic crowd)"
        ),
    )


def _is_extreme_concentration(s: SnipeSnapshot) -> bool:
    """A near-single-wallet, near-zero-sell capture — no fair launch looks like this.

    Mirrors the lp_drain escalation: an EXTREME structural read forces the label up
    regardless of corroboration. Requires the base signal's diversity-deficit to
    also hold (kept inside :func:`_concentrated_capture`'s fire check), so this is a
    strictly-stronger tier of the same fired signal, never a standalone over-claim.
    """
    return bool(
        s.buyer_count >= MIN_CONC_BUYERS
        and s.top_buyer_share is not None
        and s.one_sided_ratio is not None
        and s.top_buyer_share >= EXTREME_CONC_T
        and s.one_sided_ratio >= EXTREME_ONESIDE_T
    )


def _label_for(
    score: float,
    *,
    lp_drained: bool,
    concentration_corroborated: bool = False,
    extreme_concentration: bool = False,
) -> str:
    # EXTREME concentration or concentration + any corroborating tell forces the
    # verdict to at least likely_sniped (→ gate "block"), independent of the raw
    # weight sum: W_CONCENTRATION alone is a `suspicious` floor by design, and a
    # captured float corroborated by even one other tell is a block.
    if extreme_concentration or concentration_corroborated:
        if lp_drained:
            return "confirmed_wash"
        return "likely_sniped"
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
        _unknown_program(snap),
        _shared_alt(snap),
        _co_buy(snap),
        _lp_drain(snap),
        _concentrated_capture(snap),
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

    # Concentrated-capture escalation (mirrors lp_drain): a captured float
    # corroborated by ANY other fired tell is a block; an EXTREME capture
    # (near-single-wallet, near-zero-sell) blocks alone — even at launch, since no
    # fair launch shows that shape. A LONE moderate concentration stays a
    # `suspicious` floor (W_CONCENTRATION = LABEL_SUSPICIOUS), incl. at launch:
    # the launch FP guard is satisfied by NOT escalating it to block.
    fired_codes = {s.code for s in fired}
    concentration_fired = "concentrated_capture" in fired_codes
    extreme_concentration = concentration_fired and _is_extreme_concentration(snap)
    concentration_corroborated = concentration_fired and bool(
        fired_codes - {"concentrated_capture"}
    )

    score = min(1.0, sum(s.weight for s in fired))
    return SnipeBlock(
        score=round(score, 4),
        label=_label_for(
            score,
            lp_drained=snap.lp_drained,
            concentration_corroborated=concentration_corroborated,
            extreme_concentration=extreme_concentration,
        ),
        reasons=[s.reason for s in fired if s.reason],
        fired_signals=[s.code for s in fired],
    )


__all__ = ["SnipeBlock", "SnipeLabel", "SnipeSnapshot", "TipFloor", "assess_snipe"]
