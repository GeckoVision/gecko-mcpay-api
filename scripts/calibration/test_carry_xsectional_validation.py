"""Tests for carry_xsectional_validation.build — the cross-sectional weekly book.

Load-bearing: top-K coins must be SHORTED (mult +1, harvest +funding) and bottom-K
LONGED (mult -1, harvest -funding); both harvest positive on persistent funding;
ranking must use strictly-prior data (no look-ahead).

Run: uv run pytest scripts/calibration/test_carry_xsectional_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import carry_xsectional_validation as cx


def test_book_sides_and_harvest_positive():
    # 4 coins, constant funding: HI/HI2 positive (should be shorted, +1), LO/LO2 negative (longed, -1).
    W = cx.W
    n = W * 3
    fund = {
        "HI": {i * 3_600_000: 0.001 for i in range(n)},
        "HI2": {i * 3_600_000: 0.0009 for i in range(n)},
        "LO": {i * 3_600_000: -0.001 for i in range(n)},
        "LO2": {i * 3_600_000: -0.0009 for i in range(n)},
    }
    port, per_coin = cx.build(fund, k=2, flip_cost=0.0)
    assert len(port) > 0
    # every selected leg harvests positively (short positive funding / long negative funding)
    # after the first rebalance hour (no flip cost here anyway)
    assert all(v > 0 for _, v in per_coin["HI"])
    assert all(v > 0 for _, v in per_coin["LO"])
    # portfolio mean is positive (pure harvest, no cost)
    assert sum(port) / len(port) > 0


def test_flip_cost_charged_at_rebalance():
    W = cx.W
    n = W * 3
    fund = {
        "HI": {i * 3_600_000: 0.001 for i in range(n)},
        "LO": {i * 3_600_000: -0.001 for i in range(n)},
    }
    no_cost, _ = cx.build(fund, k=1, flip_cost=0.0)
    with_cost, _ = cx.build(fund, k=1, flip_cost=0.002)
    # charging a flip cost lowers total return (legs enter at first rebalance)
    assert sum(with_cost) < sum(no_cost)
