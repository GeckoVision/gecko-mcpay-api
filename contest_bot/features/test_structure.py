"""Tests for the structure primitives — leakage-safety + correctness.

The load-bearing assertions: a fractal pivot at bar j is INVISIBLE until exactly
bar j+k (no look-ahead), and the room/structure/range measures are computed
correctly from confirmed pivots. Synthetic, deterministic, no I/O.

Run: uv run pytest contest_bot/features/test_structure.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import structure as s


def _approx(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol


# ── Pivot detection ─────────────────────────────────────────────────
def test_pivot_highs_detected_at_clear_peaks():
    H = [1.0, 2, 3, 4, 10, 4, 3, 5, 12, 6, 5, 4, 3]
    L = [1.0, 1, 0, 2, 3, 2, 0, 3, 5, 4, 2, 1, 0]
    ph, _pl = s.confirmed_pivots(H, L, i=12, k=2)
    assert ph == [4, 8]


def test_pivot_lows_detected_at_clear_troughs():
    H = [1.0, 2, 3, 4, 10, 4, 3, 5, 12, 6, 5, 4, 3]
    L = [1.0, 1, 0, 2, 3, 2, 0, 3, 5, 4, 2, 1, 0]
    _ph, pl = s.confirmed_pivots(H, L, i=12, k=2)
    assert 2 in pl and 6 in pl and 12 not in pl


def test_flat_plateau_is_not_a_pivot():
    # A center tied with the right edge of its window (no STRICTLY lower neighbor
    # on the right) must NOT register — guards against flat ties as pivots.
    # window for center j=2 (k=2) is highs[0:5]=[1,2,5,5,5]; right=[5,5] has no
    # value strictly below 5 -> not a pivot.
    H = [1.0, 2, 5, 5, 5, 6, 7]
    L = [0.0, 1, 4, 4, 4, 5, 6]
    ph, _pl = s.confirmed_pivots(H, L, i=6, k=2)
    assert 2 not in ph  # the tied-right plateau center fails the strict-neighbor rule


# ── Leakage: a pivot at j is invisible before j+k ───────────────────
def test_pivot_not_visible_before_confirmation_bar():
    H = [1.0, 2, 3, 4, 10, 4, 3, 5, 12, 6, 5, 4, 3]
    L = [1.0, 1, 0, 2, 3, 2, 0, 3, 5, 4, 2, 1, 0]
    ph_before, _ = s.confirmed_pivots(H, L, i=4 + 2 - 1, k=2)  # i=5
    ph_at, _ = s.confirmed_pivots(H, L, i=4 + 2, k=2)  # i=6
    assert 4 not in ph_before  # peak@4 not yet confirmable at i=5
    assert 4 in ph_at  # confirmed exactly at i=j+k=6


# ── S/R clustering ──────────────────────────────────────────────────
def test_cluster_merges_nearby_pivots_and_separates_far_ones():
    # three pivots near 100 (within 0.5%) -> one level; one far at 110 -> another.
    pts = [(100.0, 1), (100.3, 5), (99.8, 9), (110.0, 13)]
    levels = s.cluster_levels(pts, "resistance", cluster_pct=0.5)
    assert len(levels) == 2
    near, far = levels[0], levels[1]
    assert near.touches == 3 and far.touches == 1
    assert near.last_idx == 9  # most recent in the near cluster
    assert _approx(far.price, 110.0)


def test_cluster_empty_input():
    assert s.cluster_levels([], "support") == []


# ── Distance-to-next-level (room to run) ────────────────────────────
def test_room_to_resistance_above_and_open_sky():
    # entry close below a known resistance -> finite room; above all -> open sky.
    H = [5.0, 6, 9, 6, 5, 7, 7, 7]  # swing-high (9) at index 2
    L = [4.0, 4, 7, 4, 3, 5, 5, 5]  # swing-low (3) at index 4
    C = [4.5, 5.5, 8.5, 5.5, 4.0, 6.0, 6.0, 6.0]  # entry@6 close=6.0
    room = s.distance_to_next_resistance(H, L, C, 6, k=2)
    assert _approx(room, (9 - 6) / 6 * 100)  # 50%
    sup = s.distance_to_next_support(H, L, C, 6, k=2)
    assert _approx(sup, (6 - 3) / 6 * 100)  # 50%


def test_open_sky_returns_none():
    H = [5.0, 9, 5, 4, 5, 20, 20, 20]  # only confirmed swing-high is 9@idx1
    L = [4.0, 7, 3, 2, 3, 18, 18, 18]
    C = [4.5, 8.5, 4.0, 3.0, 4.0, 19, 19, 19]  # entry@6 close=19 > 9
    assert s.distance_to_next_resistance(H, L, C, 6, k=2) is None


# ── Market structure ────────────────────────────────────────────────
def _zigzag(pivots: list[tuple[str, int, float]]) -> tuple[list[float], list[float], list[float]]:
    xs = [p[1] for p in pivots]
    ys = [p[2] for p in pivots]
    n = xs[-1] + 1
    mid = [0.0] * n
    for seg in range(len(xs) - 1):
        x0, x1, y0, y1 = xs[seg], xs[seg + 1], ys[seg], ys[seg + 1]
        for x in range(x0, x1 + 1):
            mid[x] = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    hi = [m + 0.3 for m in mid]
    lo = [m - 0.3 for m in mid]
    for kind, idx, _lvl in pivots:
        if kind == "H":
            hi[idx] = mid[idx] + 0.6
        else:
            lo[idx] = mid[idx] - 0.6
    return hi, lo, mid


def test_market_structure_up_down_range():
    up_h, up_l, _ = _zigzag(
        [
            ("L", 0, 3),
            ("H", 4, 7),
            ("L", 8, 4),
            ("H", 12, 10),
            ("L", 16, 5),
            ("H", 20, 13),
            ("L", 24, 6),
        ]
    )
    assert s.market_structure(up_h, up_l, 24, k=2) == "UP"
    dn_h, dn_l, _ = _zigzag(
        [
            ("L", 0, 16),
            ("H", 4, 13),
            ("L", 8, 8),
            ("H", 12, 10),
            ("L", 16, 5),
            ("H", 20, 7),
            ("L", 24, 2),
        ]
    )
    assert s.market_structure(dn_h, dn_l, 24, k=2) == "DOWN"
    rg_h, rg_l, _ = _zigzag(
        [
            ("L", 0, 5),
            ("H", 4, 7),
            ("L", 8, 2),
            ("H", 12, 10),
            ("L", 16, 1),
            ("H", 20, 13),
            ("L", 24, 0),
        ]
    )
    assert s.market_structure(rg_h, rg_l, 24, k=2) == "RANGE"


def test_market_structure_insufficient_pivots_is_range():
    H = [1.0, 2, 5, 2, 1]
    L = [0.0, 1, 4, 1, 0]
    assert s.market_structure(H, L, 4, k=2) == "RANGE"


# ── Range boundaries + position ─────────────────────────────────────
def test_range_position_low_mid_high():
    H = [5.0, 6, 10, 6, 5, 7, 7, 7]  # range high pivot = 10@idx2
    L = [4.0, 4, 8, 4, 2, 5, 5, 5]  # range low pivot = 2@idx4
    # entry close at the low boundary
    C_lo = [4.5, 5, 9, 5, 3, 2.0, 2.0, 2.0]
    pos_lo = s.range_position(H, L, C_lo, 6, k=2)
    assert pos_lo is not None and pos_lo < 0.1
    # entry close at the high boundary
    C_hi = [4.5, 5, 9, 5, 3, 10.0, 10.0, 10.0]
    pos_hi = s.range_position(H, L, C_hi, 6, k=2)
    assert pos_hi is not None and pos_hi > 0.9
    # mid-range
    C_mid = [4.5, 5, 9, 5, 3, 6.0, 6.0, 6.0]
    pos_mid = s.range_position(H, L, C_mid, 6, k=2)
    assert pos_mid is not None and 0.4 < pos_mid < 0.6


def test_range_position_none_when_boundary_missing():
    # no confirmed pivot-low below -> range undefined.
    H = [1.0, 2, 5, 2, 1, 3, 3]
    L = [0.9, 1.5, 4, 1.5, 0.9, 2, 2]
    pos = s.range_position(H, L, [1.0] * 7, 2, k=2)
    assert pos is None
