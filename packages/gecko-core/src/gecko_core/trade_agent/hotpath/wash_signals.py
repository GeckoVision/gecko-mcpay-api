"""Pure deterministic wash / bot-manipulation scorers for the Launch Firewall.

Step 1 of the Launch Firewall build order (see
``private/strategy/2026-06-18-launch-firewall-architecture-synthesis.md`` and the
Notion "Launch Firewall — Technical Architecture" page). This module is the
**flow layer** that sits on top of the existing static ``SafetyBlock`` /
``InformationMEVBlock`` read: the static layer catches fake-mcap + float-control
from a single snapshot; this layer catches *flow* manipulation — the
38-buys/0-sells loop, multi-pool price bait, wash rings, common-funder sybils.

Design constraints (hotpath isolation, per CLAUDE.md):

* **Pure.** Every function takes a snapshot and returns a verdict. No network,
  no clock-dependent globals, no I/O. Falsifiable in isolation with
  ``model_construct``-style synthetic snapshots — that is the whole point of
  doing the scorer first (Pattern B: a free local simulation before any wire).
* **Hotpath-clean.** Imports ``pydantic`` only. It MUST NOT import
  ``gecko_core.db`` / ``rag`` / ``orchestration`` (that would drag db-adjacent
  code into the latency island). The ``WashRiskBlock`` deliberately *mirrors*
  ``orchestration.trade_panel.models.InformationMEVBlock`` rather than importing
  it, keeping the dependency surface tiny. The serve layer maps one to the other.
* **Fail-OPEN.** :func:`assess_wash_risk` returns ``None`` when there is nothing
  to assess (no flow window, no pools, no wallets) — never a fabricated
  ``"clean"``. When inputs exist but are benign, a real ``clean`` block is
  emitted (a positive read is information too). ``unknown`` is never "safe".

The four signals built here (the highest signal-per-effort set; F0 already ships
as the static layer):

* **F1 — thin-pool buy-loop** (the BrCA 38-buys/0-sells headline): one-sided
  flow on tiny uniform notional while price climbs.
* **F5 — multi-pool price-discrepancy bait**: a token quoted far above its
  liquidity-weighted index price in thin, dead satellite pools.
* **F2 — wash / self-trade**: a wallet trading both sides in balance with no net
  fresh capital entering — recirculation, not price discovery.
* **F4 — common-funder sybil cluster**: the "many buyers" were all funded by a
  few fresh wallets shortly before launch.

False-positive guards are applied inline (a real hour-1 fair launch is thin,
concentrated, and one-sided by nature; without guards the firewall flags every
genuine launch). The escalation rule keeps the demo honest: a real fair launch
reads ``clean`` / ``elevated``; a manufactured one reads ``manipulated``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Output block (mirrors InformationMEVBlock — see module docstring)            #
# --------------------------------------------------------------------------- #

WashRiskLabel = str  # one of: "clean" | "elevated" | "manipulated"
_LABELS: tuple[str, str, str] = ("clean", "elevated", "manipulated")


class WashRiskBlock(BaseModel):
    """Named flow-manipulation read — severity of bot/wash activity in a token's
    *trade flow* (as opposed to the static ``InformationMEVBlock`` snapshot read).

    Fail-OPEN: the whole block is ``None`` when there were no flow inputs to
    assess. When inputs exist but benign, a real ``clean`` block is emitted.
    """

    model_config = ConfigDict(extra="forbid")

    score: float = Field(
        ..., ge=0.0, le=1.0, description="Flow-manipulation severity in [0,1]; 0 = clean."
    )
    label: WashRiskLabel = Field(
        ..., description="One-glance band: clean / elevated / manipulated."
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Human-readable signals behind the score; carries the 'clean' note when benign.",
    )
    fired_signals: list[str] = Field(
        default_factory=list,
        description="Machine codes of the signals that fired (e.g. 'thin_pool_buy_loop').",
    )


# --------------------------------------------------------------------------- #
# Pure input snapshot (a thin, I/O-free contract; token_state.py populates it) #
# --------------------------------------------------------------------------- #


class PoolSnapshot(BaseModel):
    """One DEX pool's current state (a single-pool slice of TokenState.pools)."""

    model_config = ConfigDict(extra="forbid")

    pool_addr: str
    spot_price_usd: float | None = Field(default=None, ge=0.0)
    tvl_usd: float | None = Field(default=None, ge=0.0)
    vol_5m_usd: float = Field(default=0.0, ge=0.0)
    swap_count_5m: int = Field(default=0, ge=0)
    is_clmm: bool = Field(
        default=False,
        description="Concentrated-liquidity pool; nominal TVL may sit out of range (FP guard).",
    )


class FlowWindow(BaseModel):
    """Rolling buy/sell aggregates over one time window (e.g. last 5 minutes)."""

    model_config = ConfigDict(extra="forbid")

    buy_count: int = Field(default=0, ge=0)
    sell_count: int = Field(default=0, ge=0)
    buy_vol_usd: float = Field(default=0.0, ge=0.0)
    sell_vol_usd: float = Field(default=0.0, ge=0.0)
    unique_buyers: int = Field(default=0, ge=0)
    unique_sellers: int = Field(default=0, ge=0)
    notional_p50: float | None = Field(
        default=None, ge=0.0, description="Median trade size in USD over the window."
    )
    notional_p95: float | None = Field(
        default=None, ge=0.0, description="95th-percentile trade size in USD (size spread)."
    )
    price_open: float | None = Field(default=None, ge=0.0)
    price_close: float | None = Field(default=None, ge=0.0)


class WalletSnapshot(BaseModel):
    """Per-wallet aggregates over the launch window (capped to top-N by volume)."""

    model_config = ConfigDict(extra="forbid")

    address: str
    buy_vol_usd: float = Field(default=0.0, ge=0.0)
    sell_vol_usd: float = Field(default=0.0, ge=0.0)
    round_trips: int = Field(default=0, ge=0)
    funder: str | None = Field(
        default=None, description="One-hop funding wallet (batch-filled); None if unknown."
    )
    funded_ts: int | None = Field(
        default=None, description="Unix ts the wallet was first funded; None if unknown."
    )
    funded_amount: float | None = Field(default=None, ge=0.0)


class FirewallSnapshot(BaseModel):
    """The complete pure input to :func:`assess_wash_risk`.

    Everything the four scorers need, with no I/O. ``token_state.py`` (step 2)
    will build this from the rolling per-mint state; the sandbox feeds it
    directly from recorded fixtures.
    """

    model_config = ConfigDict(extra="forbid")

    mint: str
    age_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description="Seconds since pool creation; None if unknown. Drives launch FP guards.",
    )
    window: FlowWindow | None = Field(
        default=None, description="The recent (e.g. 5m) flow window; None if no swaps seen."
    )
    pools: list[PoolSnapshot] = Field(default_factory=list)
    wallets: list[WalletSnapshot] = Field(default_factory=list)
    index_price_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Liquidity-weighted price across pools — the single source of truth (never max-pool).",
    )
    net_fresh_inflow_usd: float | None = Field(
        default=None,
        description="External capital that actually entered the token this window; ~0 with high volume = recirculation.",
    )
    pool_created_ts: int | None = Field(
        default=None, description="Unix ts of pool creation; for F4 'funded pre-launch' test."
    )
    cex_funders: frozenset[str] = Field(
        default_factory=frozenset,
        description="Allowlist of known CEX hot-wallet funders — a shared CEX funder is NOT a sybil cluster.",
    )


# --------------------------------------------------------------------------- #
# Tunables (kept here as the single canonical place — Pattern A)               #
# --------------------------------------------------------------------------- #

# F1 — thin-pool buy-loop
F1_ONE_SIDED_RATIO = 0.9  # buys / (buys + sells)
F1_MAX_SELLS = 2
F1_MAX_MEDIAN_NOTIONAL_USD = 50.0
F1_MIN_PRICE_GAIN = 0.15  # +15% over the window
F1_DIVERSITY_BUYERS = 5  # below this, "few wallets" — bot-loop-like
F1_UNIFORMITY_P95_P50 = 1.5  # below this, trade sizes are suspiciously uniform
F1_WEIGHT = 0.45

# F5 — multi-pool price-discrepancy bait
F5_DISPERSION = 1.5  # max_pool_price / index_price
F5_DEAD_POOL_TVL_USD = 1_000.0
F5_WEIGHT = 0.30

# F2 — wash / self-trade
F2_BALANCE_RATIO = 0.8  # min(buy,sell) / max(buy,sell)
F2_MIN_ROUND_TRIPS = 4
F2_NET_INFLOW_FRAC = 0.05  # net fresh inflow < 5% of wallet volume = internal recirculation
F2_WEIGHT = 0.35

# F4 — common-funder sybil cluster
F4_CLUSTER_SHARE = 0.60  # ≥60% of buyers share …
F4_MAX_FUNDERS = 3  # … ≤3 common funders
F4_PRE_LAUNCH_WINDOW_S = 24 * 3600  # funded < 24h before launch
F4_AMOUNT_TOLERANCE = 0.05  # near-identical funding amounts (±5%)
F4_MIN_BUYERS = 5  # need a meaningful buyer set before clustering means anything
F4_WEIGHT = 0.40

# Launch false-positive guard
LAUNCH_AGE_S = 3600.0  # tokens younger than this are "at launch"

# Aggregate → label thresholds
LABEL_ELEVATED = 0.30
LABEL_MANIPULATED = 0.60


@dataclass(slots=True)
class _SignalResult:
    fired: bool
    code: str
    weight: float
    reason: str | None


# --------------------------------------------------------------------------- #
# Individual signals (each pure, each returns a _SignalResult)                 #
# --------------------------------------------------------------------------- #


def _f1_thin_pool_buy_loop(snap: FirewallSnapshot) -> _SignalResult:
    """One-sided buys on tiny uniform notional while price climbs (BrCA pattern).

    FP guard: a hyped fair launch is also buy-heavy, but it has *many* unique
    buyers with *fat-tailed* trade sizes. We only fire when the flow is BOTH
    one-sided AND (few buyers OR uniform sizes).
    """
    code = "thin_pool_buy_loop"
    w = snap.window
    if w is None:
        return _SignalResult(False, code, F1_WEIGHT, None)
    total = w.buy_count + w.sell_count
    if total == 0:
        return _SignalResult(False, code, F1_WEIGHT, None)

    buy_ratio = w.buy_count / total
    one_sided = buy_ratio >= F1_ONE_SIDED_RATIO and w.sell_count <= F1_MAX_SELLS
    tiny = w.notional_p50 is not None and w.notional_p50 < F1_MAX_MEDIAN_NOTIONAL_USD
    rising = (
        w.price_open is not None
        and w.price_close is not None
        and w.price_open > 0
        and (w.price_close - w.price_open) / w.price_open >= F1_MIN_PRICE_GAIN
    )
    if not (one_sided and tiny and rising):
        return _SignalResult(False, code, F1_WEIGHT, None)

    # FP guard: organic hype has trader diversity + size spread.
    few_buyers = w.unique_buyers < F1_DIVERSITY_BUYERS
    uniform = (
        w.notional_p95 is not None
        and w.notional_p50 is not None
        and w.notional_p50 > 0
        and (w.notional_p95 / w.notional_p50) < F1_UNIFORMITY_P95_P50
    )
    if not (few_buyers or uniform):
        return _SignalResult(False, code, F1_WEIGHT, None)

    detail = (
        f"{w.buy_count} buys / {w.sell_count} sells, "
        f"median ${w.notional_p50:.0f}, {w.unique_buyers} buyers"
    )
    return _SignalResult(
        True, code, F1_WEIGHT, f"thin-pool buy-loop ({detail}) — one-sided, uniform, price climbing"
    )


def _f5_multi_pool_price_bait(snap: FirewallSnapshot) -> _SignalResult:
    """A token quoted far above its index price in thin, dead satellite pools.

    Uses the liquidity-weighted index price as truth. FP guard: CLMM pools can
    legitimately sit out of range, so we never treat a CLMM pool as a dead-bait
    pool (we lack in-range liquidity in this snapshot — exclude conservatively).
    """
    code = "multi_pool_price_bait"
    idx = snap.index_price_usd
    if idx is None or idx <= 0 or not snap.pools:
        return _SignalResult(False, code, F5_WEIGHT, None)

    worst: PoolSnapshot | None = None
    worst_disp = 0.0
    for p in snap.pools:
        if p.is_clmm or p.spot_price_usd is None or p.spot_price_usd <= 0:
            continue
        disp = p.spot_price_usd / idx
        dead = (p.tvl_usd is not None and p.tvl_usd < F5_DEAD_POOL_TVL_USD) and p.swap_count_5m == 0
        if disp >= F5_DISPERSION and dead and disp > worst_disp:
            worst, worst_disp = p, disp

    if worst is None:
        return _SignalResult(False, code, F5_WEIGHT, None)

    return _SignalResult(
        True,
        code,
        F5_WEIGHT,
        (
            f"price-bait pool {worst.pool_addr[:8]}… quotes ${worst.spot_price_usd:.4f} "
            f"({worst_disp:.1f}x the ${idx:.4f} index) on ~${worst.tvl_usd or 0:.0f} dead liquidity"
        ),
    )


def _f2_wash_self_trade(snap: FirewallSnapshot) -> _SignalResult:
    """A wallet trading both sides in balance with ≥4 round-trips and no net
    fresh capital entering — recirculation, not price discovery.

    FP guard (MM vs wash): a real market maker moves price toward the index and
    brings *fresh* capital; wash recirculates internally. We require the token's
    net fresh inflow to be ~0 relative to the wash wallet's volume.
    """
    code = "wash_self_trade"
    if not snap.wallets:
        return _SignalResult(False, code, F2_WEIGHT, None)

    for wal in snap.wallets:
        hi = max(wal.buy_vol_usd, wal.sell_vol_usd)
        lo = min(wal.buy_vol_usd, wal.sell_vol_usd)
        if hi <= 0:
            continue
        balanced = (lo / hi) >= F2_BALANCE_RATIO
        churning = wal.round_trips >= F2_MIN_ROUND_TRIPS
        if not (balanced and churning):
            continue
        # MM guard: require recirculation (little/no net external inflow).
        if snap.net_fresh_inflow_usd is not None:
            wallet_vol = wal.buy_vol_usd + wal.sell_vol_usd
            if wallet_vol > 0 and snap.net_fresh_inflow_usd > F2_NET_INFLOW_FRAC * wallet_vol:
                continue  # real fresh capital — looks like MM, not wash
        return _SignalResult(
            True,
            code,
            F2_WEIGHT,
            (
                f"wallet {wal.address[:8]}… {wal.round_trips} round-trips, "
                f"buy/sell balanced ({lo / hi:.2f}) with no net inflow — wash"
            ),
        )
    return _SignalResult(False, code, F2_WEIGHT, None)


def _f4_common_funder_sybil(snap: FirewallSnapshot) -> _SignalResult:
    """≥60% of distinct buyers funded by ≤3 fresh wallets shortly pre-launch with
    near-identical amounts — a coordinated sybil cluster, not organic demand.

    FP guard: a shared *CEX* hot-wallet funder is excluded (buyers just withdrew
    from the same exchange). Only fresh/EOA common funders count.
    """
    code = "common_funder_sybil"
    # Distinct buyers = wallets that actually bought.
    buyers = [w for w in snap.wallets if w.buy_vol_usd > 0]
    if len(buyers) < F4_MIN_BUYERS:
        return _SignalResult(False, code, F4_WEIGHT, None)

    # Tally fresh, pre-launch funders with their funding amounts.
    funder_amounts: dict[str, list[float]] = {}
    for w in buyers:
        f = w.funder
        if f is None or f in snap.cex_funders:
            continue
        if (
            snap.pool_created_ts is not None
            and w.funded_ts is not None
            and not (0 <= snap.pool_created_ts - w.funded_ts <= F4_PRE_LAUNCH_WINDOW_S)
        ):
            continue  # not funded in the pre-launch window
        funder_amounts.setdefault(f, []).append(w.funded_amount or 0.0)

    if not funder_amounts:
        return _SignalResult(False, code, F4_WEIGHT, None)

    # Take the top funders by buyer-count; do they cover ≥60% of buyers?
    ranked = sorted(funder_amounts.items(), key=lambda kv: len(kv[1]), reverse=True)
    top = ranked[:F4_MAX_FUNDERS]
    covered = sum(len(amts) for _, amts in top)
    share = covered / len(buyers)
    if share < F4_CLUSTER_SHARE:
        return _SignalResult(False, code, F4_WEIGHT, None)

    # Near-identical funding amounts within the cluster (the automation tell).
    all_amts = [a for _, amts in top for a in amts if a > 0]
    uniform_amounts = True
    if len(all_amts) >= 2:
        mean = sum(all_amts) / len(all_amts)
        if mean > 0:
            uniform_amounts = all(abs(a - mean) / mean <= F4_AMOUNT_TOLERANCE for a in all_amts)
    if not uniform_amounts:
        return _SignalResult(False, code, F4_WEIGHT, None)

    return _SignalResult(
        True,
        code,
        F4_WEIGHT,
        (
            f"{covered}/{len(buyers)} buyers ({share:.0%}) share ≤{len(top)} fresh funders, "
            "funded pre-launch with near-identical amounts — sybil cluster"
        ),
    )


_SIGNALS = (
    _f1_thin_pool_buy_loop,
    _f5_multi_pool_price_bait,
    _f2_wash_self_trade,
    _f4_common_funder_sybil,
)


# --------------------------------------------------------------------------- #
# Aggregator                                                                   #
# --------------------------------------------------------------------------- #


def _has_inputs(snap: FirewallSnapshot) -> bool:
    """True when there is at least one thing to assess (else fail-OPEN → None)."""
    window_has_flow = (
        snap.window is not None and (snap.window.buy_count + snap.window.sell_count) > 0
    )
    return window_has_flow or bool(snap.pools) or bool(snap.wallets)


def _label_for(score: float) -> str:
    if score >= LABEL_MANIPULATED:
        return "manipulated"
    if score >= LABEL_ELEVATED:
        return "elevated"
    return "clean"


def assess_wash_risk(snap: FirewallSnapshot) -> WashRiskBlock | None:
    """Run all flow signals and aggregate into a single :class:`WashRiskBlock`.

    Returns ``None`` (fail-OPEN) when there is nothing to assess. Otherwise
    returns a real block — including a benign ``clean`` block when inputs exist
    but no signal fires (a positive read is information too).

    Launch FP guard: for tokens younger than :data:`LAUNCH_AGE_S`, a single
    fired flow signal escalates only to ``elevated``; ``manipulated`` requires
    corroboration (≥2 signals or aggregate ≥ threshold). A genuine fair launch
    that trips exactly one signal therefore never reads ``manipulated``.
    """
    if not _has_inputs(snap):
        return None

    results = [sig(snap) for sig in _SIGNALS]
    fired = [r for r in results if r.fired]

    if not fired:
        return WashRiskBlock(
            score=0.0,
            label="clean",
            reasons=["no wash/bot flow signals fired on the observed flow"],
            fired_signals=[],
        )

    score = min(1.0, sum(r.weight for r in fired))
    label = _label_for(score)

    # At launch, a lone signal is suggestive but not damning — cap at elevated.
    at_launch = snap.age_seconds is not None and snap.age_seconds < LAUNCH_AGE_S
    if at_launch and len(fired) < 2 and label == "manipulated":
        label = "elevated"

    return WashRiskBlock(
        score=round(score, 4),
        label=label,
        reasons=[r.reason for r in fired if r.reason],
        fired_signals=[r.code for r in fired],
    )
