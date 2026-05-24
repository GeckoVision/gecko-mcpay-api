"""ICT / order-flow primitives — pure, strictly causal (Gecko trade lab, Phase B).

WHAT THIS IS
  Deterministic ICT/order-flow features computed STRICTLY on candles[:i+1]:
  Order Blocks (OB), Fair Value Gaps (FVG) with causal mitigation tracking,
  Market Structure Shifts (MSS), liquidity sweeps (sweep-and-reclaim), and the
  OTE / Fibonacci discount-zone test built on the structure.py swing pivots.
  No I/O, no network, no live-bot state — the same pure-function discipline as
  contest_bot/indicators.py and contest_bot/features/structure.py.

CAUSALITY (the whole point)
  Every ICT pattern here is multi-candle and therefore LOOKAHEAD-PRONE if written
  carelessly. The discipline is identical to structure.py: a value computed at bar
  i reads bar i and every bar before it, and NOTHING at i+1 or later. The Phase V
  Feature protocol's lookahead trap (feature_validation.lookahead_clean) enforces
  this: a value computed on the full series must equal the value computed on the
  truncated prefix candles[:i+1]. Two traps in particular:
    * FVG mitigation — a gap is "unmitigated" only with respect to bars <= i.
      Mitigation by a FUTURE bar must NOT retroactively change the value at i.
    * MSS / OB confirmation — the swing extreme broken / the displacement candle
      must be fully printed at or before i.

FOUNDER'S DEFINITIONS (implemented exactly)
  BIAS (4H):
    * Order Block: a high-volume displacement candle. V_t > mean_V_20 + 2*std_V_20
      AND |close-open| > rolling mean of |close-open|.
    * Fair Value Gap (bullish): 3-candle window with Low_t > High_{t-2}. The
      interval [High_{t-2}, Low_t] is unmitigated until price trades back into it.
    * Market Structure Shift (bullish): C_t > max(H_{t-1..t-5}) AND V_t > mean_V_20.
  ENTRY (15m):
    * Liquidity sweep: L_sweep = min(L_{t-1..t-N}); a bar whose low spikes below
      L_sweep but whose close reclaims back above it (sweep-and-reclaim in-bar).
    * OTE / Fib: dealing range from swing low to swing high (structure.py pivots);
      discount zone = retrace < 50%; OTE entry level = H - 0.618*(H - L).

SCORE CONVENTION
  "higher = more bullish / more take-able", consistent with feature_validation's
  tercile edge estimator. Each gate also exposes a boolean `passes` predicate so
  the acceptance-gate harness can build the SELECTED ("act") subset.

CANDLE SHAPE
  The Phase V Feature protocol passes the enriched dict-of-lists (candles["open"],
  ["high"], ["low"], ["close"], ["volume"] aligned ascending). Low-level helpers
  take parallel ascending lists; the Feature conformers slice the dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Lookback for the rolling volume / body statistics that define a displacement
# candle (OB) and the MSS volume floor. 20 bars is the founder's mean_V_20.
DEFAULT_VOL_LOOKBACK = 20

# MSS / structure-break lookback: C_t must exceed the max high of the prior 5 bars.
DEFAULT_MSS_LOOKBACK = 5

# Liquidity-sweep lookback N: the prior-low window whose minimum is the swept level.
DEFAULT_SWEEP_LOOKBACK = 10

# OTE fib retracement levels. Discount zone is below the 50% level; the 0.618 is
# the canonical OTE entry inside the discount zone.
OTE_LEVEL = 0.618
DISCOUNT_MAX = 0.5  # entry only when retrace is in the discount half (<50%)

# Pivot half-width for the OTE dealing-range swings (reuse structure.py's default).
DEFAULT_PIVOT_K = 2
DEFAULT_PIVOT_LOOKBACK = 120


# ── Rolling stats helpers (strictly backward windows) ───────────────
def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float], mean: float | None = None) -> float:
    """Population std of a backward window. 0.0 on degenerate (<2) windows."""
    if len(xs) < 2:
        return 0.0
    m = _mean(xs) if mean is None else mean
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


# ── Bias #1: Order Block (high-volume displacement candle) ──────────
@dataclass
class OrderBlock:
    """A confirmed order-block candle: its index and price range [low, high]."""

    idx: int
    low: float
    high: float
    open: float
    close: float


def is_order_block(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    i: int,
    vol_lookback: int = DEFAULT_VOL_LOOKBACK,
) -> bool:
    """True iff bar i is an Order Block per the founder's definition:

        V_i > mean(V_{i-L..i-1}) + 2*std(V_{i-L..i-1})   (volume displacement)
        AND |close_i - open_i| > mean(|close-open|_{i-L..i-1})   (large body)

    The volume / body baselines are taken over the PRIOR L bars (strictly before
    i), so the test reads only candles[:i+1]. Returns False during warmup.
    """
    if i < vol_lookback:
        return False
    vw = volumes[i - vol_lookback : i]
    vm = _mean(vw)
    vs = _std(vw, vm)
    if volumes[i] <= vm + 2.0 * vs:
        return False
    bodies = [abs(closes[j] - opens[j]) for j in range(i - vol_lookback, i)]
    body_mean = _mean(bodies)
    return abs(closes[i] - opens[i]) > body_mean


def recent_order_blocks(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    i: int,
    vol_lookback: int = DEFAULT_VOL_LOOKBACK,
    scan: int = DEFAULT_PIVOT_LOOKBACK,
) -> list[OrderBlock]:
    """Order blocks confirmed within the last `scan` bars up to and including i.
    Each carries its candle range (used as the SL anchor downstream). Strictly
    causal: every candidate bar j <= i and its stats window is strictly before j.
    """
    out: list[OrderBlock] = []
    first = max(vol_lookback, i - scan)
    for j in range(first, i + 1):
        if is_order_block(opens, highs, lows, closes, volumes, j, vol_lookback):
            out.append(
                OrderBlock(idx=j, low=lows[j], high=highs[j], open=opens[j], close=closes[j])
            )
    return out


# ── Bias #2: Fair Value Gap (bullish) with causal mitigation ────────
@dataclass
class FVG:
    """A bullish Fair Value Gap: the 3-candle window centered such that the gap is
    [bottom, top] = [High_{t-2}, Low_t]. `created_idx` is t (the right candle of
    the triple). Mitigation is computed causally w.r.t. a query bar i."""

    created_idx: int  # = t, the index of the right candle of the 3-bar window
    bottom: float  # High_{t-2}
    top: float  # Low_t


def bullish_fvgs(
    highs: list[float],
    lows: list[float],
    i: int,
    scan: int = DEFAULT_PIVOT_LOOKBACK,
) -> list[FVG]:
    """All bullish FVGs CREATED at bars in (i-scan, i]: a 3-bar window ending at t
    (t <= i) with Low_t > High_{t-2}. The gap interval is [High_{t-2}, Low_t].

    Strictly causal: a window ending at t reads highs/lows at t, t-1, t-2 only —
    all <= i. Returns gaps oldest-first.
    """
    out: list[FVG] = []
    first = max(2, i - scan)
    for t in range(first, i + 1):
        bottom = highs[t - 2]
        top = lows[t]
        if top > bottom:
            out.append(FVG(created_idx=t, bottom=bottom, top=top))
    return out


def fvg_mitigated(fvg: FVG, lows: list[float], i: int) -> bool:
    """True iff the FVG has been MITIGATED by any bar AFTER its creation up to and
    including i — i.e. price traded back DOWN into the gap (some bar's low <= top
    of the gap). Mitigation is evaluated ONLY over bars in (created_idx, i].

    Causality note: this is parameterised by the query bar i. A future bar that
    mitigates the gap does NOT change the answer for an earlier i — the caller
    passes the i it is asking about, and we never read past it.
    """
    # price traded back into the gap from above on any bar after creation
    return any(lows[j] <= fvg.top for j in range(fvg.created_idx + 1, i + 1))


def unmitigated_bullish_fvgs_below(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    i: int,
    scan: int = DEFAULT_PIVOT_LOOKBACK,
) -> list[FVG]:
    """Unmitigated bullish FVGs whose gap sits BELOW the current close (the
    classic 'unfilled demand below price' that ICT bias requires). Strictly causal:
    creation, mitigation, and the below-price test all read only bars <= i.
    """
    px = closes[i]
    out: list[FVG] = []
    for g in bullish_fvgs(highs, lows, i, scan):
        if g.created_idx >= i:  # need at least one bar after creation to mitigate-test
            # a gap created exactly at i is unmitigated by construction; keep if below
            if g.top < px:
                out.append(g)
            continue
        if g.top < px and not fvg_mitigated(g, lows, i):
            out.append(g)
    return out


# ── Bias #3: Market Structure Shift (bullish) ───────────────────────
def is_mss_bullish(
    highs: list[float],
    closes: list[float],
    volumes: list[float],
    i: int,
    mss_lookback: int = DEFAULT_MSS_LOOKBACK,
    vol_lookback: int = DEFAULT_VOL_LOOKBACK,
) -> bool:
    """True iff bar i is a bullish Market Structure Shift per the founder's def:

        C_i > max(H_{i-1 .. i-mss_lookback})    (break of recent structure high)
        AND V_i > mean(V_{i-vol_lookback .. i-1})   (on participation)

    Both windows are strictly before i (highs i-1..i-5, volume i-20..i-1). The
    only bar-i reads are close_i and volume_i. Strictly causal.
    """
    if i < max(mss_lookback, vol_lookback):
        return False
    prior_high = max(highs[i - mss_lookback : i])
    if closes[i] <= prior_high:
        return False
    vm = _mean(volumes[i - vol_lookback : i])
    return volumes[i] > vm


def mss_bullish_active(
    highs: list[float],
    closes: list[float],
    volumes: list[float],
    i: int,
    mss_lookback: int = DEFAULT_MSS_LOOKBACK,
    vol_lookback: int = DEFAULT_VOL_LOOKBACK,
    persist: int = DEFAULT_MSS_LOOKBACK,
) -> bool:
    """True iff a bullish MSS FIRED within the last `persist` bars (inclusive of i).
    A structural-shift bias does not evaporate the next bar; it persists for a
    short window. Strictly causal (scans bars <= i only)."""
    first = max(0, i - persist + 1)
    for j in range(first, i + 1):
        if is_mss_bullish(highs, closes, volumes, j, mss_lookback, vol_lookback):
            return True
    return False


# ── Entry #1: Liquidity sweep (sweep-and-reclaim) ───────────────────
def is_liquidity_sweep(
    lows: list[float],
    closes: list[float],
    i: int,
    sweep_lookback: int = DEFAULT_SWEEP_LOOKBACK,
) -> bool:
    """True iff bar i is a bullish liquidity sweep-and-reclaim:

        L_sweep = min(L_{i-1 .. i-N})
        AND low_i < L_sweep            (wick spikes below prior liquidity)
        AND close_i > L_sweep          (but closes back above — reclaim)

    The swept level is the min of the PRIOR N lows (strictly before i); only low_i
    and close_i are read at i. Strictly causal.
    """
    if i < sweep_lookback:
        return False
    l_sweep = min(lows[i - sweep_lookback : i])
    return lows[i] < l_sweep and closes[i] > l_sweep


# ── Entry #2: OTE / Fib discount zone ───────────────────────────────
@dataclass
class DealingRange:
    """The swing dealing range used for the OTE/Fib retracement.
    low_idx/high_idx are the confirmed swing pivots; ote_level is the 0.618 entry."""

    swing_low: float
    swing_high: float
    low_idx: int
    high_idx: int
    ote_level: float = field(init=False)

    def __post_init__(self) -> None:
        self.ote_level = self.swing_high - OTE_LEVEL * (self.swing_high - self.swing_low)

    def retrace(self, price: float) -> float | None:
        """Where `price` sits in the range as a retracement from the high:
        0.0 = at the swing high, 1.0 = at the swing low. None if degenerate."""
        span = self.swing_high - self.swing_low
        if span <= 0:
            return None
        return (self.swing_high - price) / span


def latest_dealing_range(
    highs: list[float],
    lows: list[float],
    i: int,
    k: int = DEFAULT_PIVOT_K,
    lookback: int = DEFAULT_PIVOT_LOOKBACK,
) -> DealingRange | None:
    """The most-recent bullish dealing range as of bar i: the latest CONFIRMED
    swing low followed by a later CONFIRMED swing high (low precedes high → an up
    leg to retrace). Returns None if no such ordered pair exists. Uses
    structure.confirmed_pivots, which only confirms a pivot once k bars have
    printed after it (j + k <= i) — so this is strictly causal.
    """
    import structure as _st  # local import: structure.py sits beside this module

    pivot_hi, pivot_lo = _st.confirmed_pivots(highs, lows, i, k, lookback)
    if not pivot_hi or not pivot_lo:
        return None
    high_idx = pivot_hi[-1]
    # the most recent confirmed swing low STRICTLY BEFORE that high (the leg up)
    lows_before = [j for j in pivot_lo if j < high_idx]
    if not lows_before:
        return None
    low_idx = lows_before[-1]
    return DealingRange(
        swing_low=lows[low_idx], swing_high=highs[high_idx], low_idx=low_idx, high_idx=high_idx
    )


def in_discount_zone(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    i: int,
    k: int = DEFAULT_PIVOT_K,
    lookback: int = DEFAULT_PIVOT_LOOKBACK,
) -> bool:
    """True iff the close at i sits in the DISCOUNT half of the latest dealing
    range (retrace >= 50% down from the swing high, i.e. price below the
    equilibrium). Entries are only taken in discount. Strictly causal."""
    dr = latest_dealing_range(highs, lows, i, k, lookback)
    if dr is None:
        return False
    rt = dr.retrace(closes[i])
    return rt is not None and rt >= DISCOUNT_MAX


# ════════════════════════════════════════════════════════════════════
# Phase V Feature conformers (compute(candles, i) -> float, strictly causal)
# ════════════════════════════════════════════════════════════════════
def _ohlcv(candles: dict):
    return (
        candles["open"],
        candles["high"],
        candles["low"],
        candles["close"],
        candles["volume"],
    )


@dataclass
class OrderBlockFeature:
    """Score 1.0 iff bar i is (or recently was) a bullish order block — a
    high-volume displacement candle. `passes` mirrors the score. Strictly causal."""

    vol_lookback: int = DEFAULT_VOL_LOOKBACK
    persist: int = DEFAULT_MSS_LOOKBACK
    name: str = "order_block"

    def passes(self, candles: dict, i: int) -> bool:
        o, h, low, cl, v = _ohlcv(candles)
        first = max(self.vol_lookback, i - self.persist + 1)
        for j in range(first, i + 1):
            # an OB is bullish-displacement only if the candle also closed up
            if is_order_block(o, h, low, cl, v, j, self.vol_lookback) and cl[j] > o[j]:
                return True
        return False

    def compute(self, candles: dict, i: int) -> float:
        return 1.0 if self.passes(candles, i) else 0.0


@dataclass
class FVGFeature:
    """Score 1.0 iff there is an UNMITIGATED bullish FVG below the current close
    (unfilled demand under price). Strictly causal."""

    scan: int = DEFAULT_PIVOT_LOOKBACK
    name: str = "fvg_unmitigated_below"

    def passes(self, candles: dict, i: int) -> bool:
        _o, h, low, cl, _v = _ohlcv(candles)
        return len(unmitigated_bullish_fvgs_below(h, low, cl, i, self.scan)) > 0

    def compute(self, candles: dict, i: int) -> float:
        return 1.0 if self.passes(candles, i) else 0.0


@dataclass
class MSSFeature:
    """Score 1.0 iff a bullish Market Structure Shift fired within the persist
    window ending at i. Strictly causal."""

    mss_lookback: int = DEFAULT_MSS_LOOKBACK
    vol_lookback: int = DEFAULT_VOL_LOOKBACK
    persist: int = DEFAULT_MSS_LOOKBACK
    name: str = "mss_bullish"

    def passes(self, candles: dict, i: int) -> bool:
        _o, h, _low, cl, v = _ohlcv(candles)
        return mss_bullish_active(h, cl, v, i, self.mss_lookback, self.vol_lookback, self.persist)

    def compute(self, candles: dict, i: int) -> float:
        return 1.0 if self.passes(candles, i) else 0.0


@dataclass
class LiquiditySweepFeature:
    """Score 1.0 iff bar i is a bullish liquidity sweep-and-reclaim. Strictly
    causal."""

    sweep_lookback: int = DEFAULT_SWEEP_LOOKBACK
    name: str = "liquidity_sweep"

    def passes(self, candles: dict, i: int) -> bool:
        _o, _h, low, cl, _v = _ohlcv(candles)
        return is_liquidity_sweep(low, cl, i, self.sweep_lookback)

    def compute(self, candles: dict, i: int) -> float:
        return 1.0 if self.passes(candles, i) else 0.0


@dataclass
class OTEFeature:
    """Score 1.0 iff the close sits in the discount/OTE zone of the latest dealing
    range (retrace >= 50%). Strictly causal."""

    k: int = DEFAULT_PIVOT_K
    lookback: int = DEFAULT_PIVOT_LOOKBACK
    name: str = "ote_discount_zone"

    def passes(self, candles: dict, i: int) -> bool:
        _o, h, low, cl, _v = _ohlcv(candles)
        return in_discount_zone(h, low, cl, i, self.k, self.lookback)

    def compute(self, candles: dict, i: int) -> float:
        return 1.0 if self.passes(candles, i) else 0.0


@dataclass
class ICTCombinedEntry:
    """The full Step-2 gate: bullish bias (MSS active AND an unmitigated FVG below
    price) AND a liquidity sweep AND price in the discount/OTE zone. compute is
    1.0 iff ALL conditions hold at i. This is the candidate 'act' set for the
    combined-system gross-edge question. Strictly causal."""

    mss_lookback: int = DEFAULT_MSS_LOOKBACK
    vol_lookback: int = DEFAULT_VOL_LOOKBACK
    mss_persist: int = DEFAULT_MSS_LOOKBACK
    sweep_lookback: int = DEFAULT_SWEEP_LOOKBACK
    fvg_scan: int = DEFAULT_PIVOT_LOOKBACK
    k: int = DEFAULT_PIVOT_K
    pivot_lookback: int = DEFAULT_PIVOT_LOOKBACK
    name: str = "ict_combined_entry"

    def passes(self, candles: dict, i: int) -> bool:
        _o, h, low, cl, v = _ohlcv(candles)
        bias = mss_bullish_active(
            h, cl, v, i, self.mss_lookback, self.vol_lookback, self.mss_persist
        ) and bool(unmitigated_bullish_fvgs_below(h, low, cl, i, self.fvg_scan))
        if not bias:
            return False
        if not is_liquidity_sweep(low, cl, i, self.sweep_lookback):
            return False
        return in_discount_zone(h, low, cl, i, self.k, self.pivot_lookback)

    def compute(self, candles: dict, i: int) -> float:
        return 1.0 if self.passes(candles, i) else 0.0


__all__ = [
    "DISCOUNT_MAX",
    "FVG",
    "OTE_LEVEL",
    "DealingRange",
    "FVGFeature",
    "ICTCombinedEntry",
    "LiquiditySweepFeature",
    "MSSFeature",
    "OTEFeature",
    "OrderBlock",
    "OrderBlockFeature",
    "bullish_fvgs",
    "fvg_mitigated",
    "in_discount_zone",
    "is_liquidity_sweep",
    "is_mss_bullish",
    "is_order_block",
    "latest_dealing_range",
    "mss_bullish_active",
    "recent_order_blocks",
    "unmitigated_bullish_fvgs_below",
]
