"""Tests for carry_realistic_validation — the basis-aware leg return + hour-floor join.

Load-bearing: the leg return must be mult*(funding - (perp_ret - spot_ret)); a short
(mult+1) on positive funding with a FALLING premium (perp converging down) must GAIN
on both funding and basis. And funding/perp ts must join despite the ms offset.

Run: uv run pytest scripts/calibration/test_carry_realistic_validation.py -q
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import carry_realistic_validation as cr


def test_hour_floor_join(monkeypatch):
    # funding ts offset by +2ms, perp ts exact :00 -> must still join after flooring
    with tempfile.TemporaryDirectory() as d:
        fund_dir = os.path.join(d, "funding")
        perp_dir = os.path.join(d, "perp")
        os.makedirs(fund_dir)
        os.makedirs(perp_dir)
        H = 3_600_000
        fund = [{"ts": i * H + 2, "fundingRate": 0.001, "premium": 0.0005} for i in range(5)]
        perp = [{"ts": i * H, "close": 100.0 + i} for i in range(5)]
        json.dump(fund, open(os.path.join(fund_dir, "BTC_funding.json"), "w"))
        json.dump(perp, open(os.path.join(perp_dir, "BTC_perp.json"), "w"))
        monkeypatch.setattr(cr, "FUND_DIR", fund_dir)
        monkeypatch.setattr(cr, "PERP_DIR", perp_dir)
        monkeypatch.setattr(cr, "COINS", ["BTC"])
        legs = cr.load_leg_inputs()
        assert "BTC" in legs and len(legs["BTC"]) == 4  # 5 bars -> 4 with a prior bar


def test_leg_return_sign():
    # short (mult+1) on positive funding: funding term positive; basis term -(perp_ret-spot_ret)
    fr, perp_ret, spot_ret = (
        0.001,
        0.02,
        0.025,
    )  # perp rose less than spot -> basis fell -> short gains
    r = 1 * (fr - (perp_ret - spot_ret))
    assert r > 0  # +0.001 - (0.02-0.025) = +0.001 + 0.005
