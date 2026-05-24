"""Market-structure primitives — pure, strictly causal (Gecko trade lab, Phase 1).

WHAT THIS IS
  Deterministic structure features computed STRICTLY on candles[:i+1]: a k-bar
  fractal swing-pivot detector, a clustered support/resistance level table, an
  HH/HL vs LH/LL market-structure classification, range boundaries, and the
  distance-to-next-level ("room to run") measure. No I/O, no network, no
  live-bot state — the same pure-function discipline as contest_bot/indicators.py.

CAUSALITY (the whole point)
  A k-bar fractal pivot centered at bar j is only CONFIRMABLE once k bars have
  printed AFTER it (j + k <= i). So every primitive here reads pivots at indices
  <= i - k and candle data at indices <= i, NEVER at i+1 or later. The Phase V
  Feature protocol's lookahead trap (feature_validation.lookahead_clean)
  enforces this: a value computed on the full series must equal the value
  computed on the truncated prefix candles[:i+1].

CANDLE SHAPE
  Functions take parallel ascending (oldest-first) lists: highs, lows, closes.
  The Phase V Feature conformers (structure_features.py) adapt the enriched
  dict-of-lists view the protocol passes.

HOW THE FEATURES ARE FRAMED (per the prior Phase-1 de-risk finding)
  The prior structure run found that "structure CONFIRMS the breakout direction"
  (require a confirmed HH/HL uptrend) is anti-predictive — it repeats the
  momentum pathology. The useful structural signal is SUBTRACTIVE: veto entries
  into overhead resistance / mid-range chop, and a room-to-run gate that demands
  enough headroom to clear fees. These primitives expose exactly the quantities
  those veto/gate features need; the framing lives in structure_features.py.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default fractal half-width. k=2 -> a 5-bar fractal (center is the extreme of
# the [j-2, j+2] window). Small enough to leave usable pivots on short windows,
# large enough to be a real swing rather than single-bar noise.
DEFAULT_PIVOT_K = 2

# S/R level clustering tolerance: pivots whose prices are within this % of each
# other are merged into one level (a support/resistance band, not a point).
DEFAULT_CLUSTER_PCT = 0.5


# ── Swing-pivot detection (fractal highs / lows) ────────────────────
def confirmed_pivots(
    highs: list[float], lows: list[float], i: int, k: int = DEFAULT_PIVOT_K
) -> tuple[list[int], list[int]]:
    """Return (pivot_high_indices, pivot_low_indices) CONFIRMED as of bar i.

    A k-bar fractal pivot-high at center j requires high[j] to be the maximum of
    the window [j-k, j+k] AND strictly greater than at least one neighbor on EACH
    side (rejecting flat plateaus / ties). It is confirmed only once k bars have
    printed after it (j + k <= i), so candidate centers are scanned in
    [k, i-k]. Pivot-lows are the mirror (strict local minimum).

    Strictly causal: the furthest-right read is high[j+k] with j+k <= i, so no
    bar after i is ever touched.
    """
    pivot_hi: list[int] = []
    pivot_lo: list[int] = []
    last = i - k  # furthest center whose right wing (j+k) still lands at <= i
    for j in range(k, last + 1):
        wh = highs[j - k : j + k + 1]
        wl = lows[j - k : j + k + 1]
        cj_h, cj_l = highs[j], lows[j]
        left_h, right_h = wh[:k], wh[k + 1 :]
        if cj_h >= max(wh) and any(cj_h > x for x in left_h) and any(cj_h > x for x in right_h):
            pivot_hi.append(j)
        left_l, right_l = wl[:k], wl[k + 1 :]
        if cj_l <= min(wl) and any(cj_l < x for x in left_l) and any(cj_l < x for x in right_l):
            pivot_lo.append(j)
    return pivot_hi, pivot_lo


# ── Support / resistance level table (clustered pivots) ─────────────
@dataclass
class Level:
    """A clustered support/resistance level (band of nearby pivot prices)."""

    price: float  # volume-unweighted mean price of the clustered pivots
    kind: str  # "resistance" (from pivot highs) | "support" (from pivot lows)
    touches: int  # how many pivots merged into this level (cluster strength)
    last_idx: int  # most recent pivot index in the cluster (recency)


def cluster_levels(
    prices_with_idx: list[tuple[float, int]], kind: str, cluster_pct: float = DEFAULT_CLUSTER_PCT
) -> list[Level]:
    """Greedy single-pass clustering of pivot prices into S/R levels.

    Pivots are sorted by price; a new cluster starts whenever the next price is
    more than `cluster_pct`% above the current cluster's running mean. Each level
    records its mean price, touch count (cluster size), and the most recent pivot
    index (recency). Order-independent given the price sort. Returns levels sorted
    ascending by price.
    """
    if not prices_with_idx:
        return []
    ordered = sorted(prices_with_idx, key=lambda t: t[0])
    levels: list[Level] = []
    cur_prices: list[float] = [ordered[0][0]]
    cur_idxs: list[int] = [ordered[0][1]]

    def _flush() -> None:
        mean_px = sum(cur_prices) / len(cur_prices)
        levels.append(
            Level(price=mean_px, kind=kind, touches=len(cur_prices), last_idx=max(cur_idxs))
        )

    for px, idx in ordered[1:]:
        mean_px = sum(cur_prices) / len(cur_prices)
        if mean_px > 0 and (px - mean_px) / mean_px * 100.0 <= cluster_pct:
            cur_prices.append(px)
            cur_idxs.append(idx)
        else:
            _flush()
            cur_prices, cur_idxs = [px], [idx]
    _flush()
    return levels


def sr_levels(
    highs: list[float],
    lows: list[float],
    i: int,
    k: int = DEFAULT_PIVOT_K,
    cluster_pct: float = DEFAULT_CLUSTER_PCT,
) -> tuple[list[Level], list[Level]]:
    """(resistance_levels, support_levels) as of bar i, from CONFIRMED pivots.

    Resistance levels come from clustered pivot-highs, support from pivot-lows.
    Each is sorted ascending by price. Strictly causal (uses confirmed_pivots).
    """
    pivot_hi, pivot_lo = confirmed_pivots(highs, lows, i, k)
    res = cluster_levels([(highs[j], j) for j in pivot_hi], "resistance", cluster_pct)
    sup = cluster_levels([(lows[j], j) for j in pivot_lo], "support", cluster_pct)
    return res, sup


# ── Distance-to-next-level ("room to run") ──────────────────────────
def distance_to_next_resistance(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    i: int,
    k: int = DEFAULT_PIVOT_K,
    cluster_pct: float = DEFAULT_CLUSTER_PCT,
) -> float | None:
    """% distance UP from the entry close to the NEAREST clustered resistance
    level strictly ABOVE it (the headroom a long must clear before stalling).

    None means OPEN SKY: no confirmed resistance sits above the close (a fresh
    high above all prior swings) -> unbounded room overhead. Callers treat None
    as the MOST room. Strictly causal.
    """
    px = closes[i]
    if px <= 0:
        return None
    res, _sup = sr_levels(highs, lows, i, k, cluster_pct)
    above = [lvl.price for lvl in res if lvl.price > px]
    if not above:
        return None
    return (min(above) - px) / px * 100.0


def distance_to_next_support(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    i: int,
    k: int = DEFAULT_PIVOT_K,
    cluster_pct: float = DEFAULT_CLUSTER_PCT,
) -> float | None:
    """% distance DOWN from the entry close to the NEAREST clustered support
    level strictly BELOW it (the cushion under the entry). None if no confirmed
    support sits below the close. Strictly causal."""
    px = closes[i]
    if px <= 0:
        return None
    _res, sup = sr_levels(highs, lows, i, k, cluster_pct)
    below = [lvl.price for lvl in sup if lvl.price < px]
    if not below:
        return None
    return (px - max(below)) / px * 100.0


# ── Market-structure classification (HH/HL / LH/LL / RANGE) ─────────
def market_structure(
    highs: list[float], lows: list[float], i: int, k: int = DEFAULT_PIVOT_K
) -> str:
    """Classify swing structure as of bar i from the last two CONFIRMED pivots:

      UP    : higher-high AND higher-low (HH + HL),
      DOWN  : lower-high AND lower-low (LH + LL),
      RANGE : mixed / insufficient pivots.

    Strictly causal (confirmed pivots only). NOTE (per the prior de-risk
    finding): requiring UP to CONFIRM a breakout is anti-predictive; the useful
    structural signal is vetoing DOWN. This function exposes the raw label; the
    veto framing lives in structure_features.py.
    """
    pivot_hi, pivot_lo = confirmed_pivots(highs, lows, i, k)
    if len(pivot_hi) < 2 or len(pivot_lo) < 2:
        return "RANGE"
    h2 = [highs[j] for j in pivot_hi[-2:]]
    l2 = [lows[j] for j in pivot_lo[-2:]]
    hh, hl = h2[-1] > h2[-2], l2[-1] > l2[-2]
    lh, ll = h2[-1] < h2[-2], l2[-1] < l2[-2]
    if hh and hl:
        return "UP"
    if lh and ll:
        return "DOWN"
    return "RANGE"


# ── Range boundaries + position within range ────────────────────────
def range_boundaries(
    highs: list[float], lows: list[float], i: int, k: int = DEFAULT_PIVOT_K
) -> tuple[float | None, float | None]:
    """(range_high, range_low) as of bar i: the highest confirmed pivot-high and
    the lowest confirmed pivot-low. Either may be None if no pivot of that kind
    has been confirmed. These bound the structural range the price is moving in.
    Strictly causal."""
    pivot_hi, pivot_lo = confirmed_pivots(highs, lows, i, k)
    rng_hi = max((highs[j] for j in pivot_hi), default=None)
    rng_lo = min((lows[j] for j in pivot_lo), default=None)
    return rng_hi, rng_lo


def range_position(
    highs: list[float], lows: list[float], closes: list[float], i: int, k: int = DEFAULT_PIVOT_K
) -> float | None:
    """Position of the entry close WITHIN the structural range, in [0, 1]:
      0.0 = at the range low (support), 1.0 = at the range high (resistance),
      0.5 = mid-range.
    None if the range is undefined (missing a boundary) or degenerate (high<=low).
    The mid-range zone (~0.4-0.6) is the chop dead-zone the veto features target.
    Strictly causal."""
    rng_hi, rng_lo = range_boundaries(highs, lows, i, k)
    if rng_hi is None or rng_lo is None or rng_hi <= rng_lo:
        return None
    px = closes[i]
    return (px - rng_lo) / (rng_hi - rng_lo)


__all__ = [
    "DEFAULT_CLUSTER_PCT",
    "DEFAULT_PIVOT_K",
    "Level",
    "cluster_levels",
    "confirmed_pivots",
    "distance_to_next_resistance",
    "distance_to_next_support",
    "market_structure",
    "range_boundaries",
    "range_position",
    "sr_levels",
]
