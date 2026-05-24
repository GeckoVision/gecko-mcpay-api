"""TDD for ICT / order-flow primitives — hand-constructed fixtures (Phase B).

Each primitive is tested against a deliberately-built candle window with a KNOWN
pattern (a known FVG, a known sweep, a known OB, a known MSS) so the math is
checked, not eyeballed. The lookahead trap is also exercised directly: a value
computed on the full series must equal the value computed on the truncated prefix
candles[:i+1] — the structural leakage check the Phase V harness enforces.

Run: uv run pytest contest_bot/features/test_orderflow.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import orderflow as of


def _candles(rows: list[tuple[float, float, float, float, float]]) -> dict:
    """rows = list of (open, high, low, close, volume) -> enriched dict-of-lists."""
    return {
        "ts": [t * 1000 for t in range(len(rows))],
        "open": [r[0] for r in rows],
        "high": [r[1] for r in rows],
        "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
        "volume": [r[4] for r in rows],
    }


# ── Order Block ─────────────────────────────────────────────────────
def test_order_block_fires_on_volume_and_body_displacement():
    # 20 quiet bars (vol ~10, tiny body), then a displacement bar:
    # huge volume (>mean+2std) and a large body.
    rows = [(100.0, 100.5, 99.5, 100.0, 10.0) for _ in range(20)]
    # displacement bar at i=20: big body 100->105, volume 100
    rows.append((100.0, 105.5, 99.9, 105.0, 100.0))
    c = _candles(rows)
    o, h, low, cl, v = c["open"], c["high"], c["low"], c["close"], c["volume"]
    assert of.is_order_block(o, h, low, cl, v, 20) is True


def test_order_block_quiet_bar_is_not_ob():
    rows = [(100.0, 100.5, 99.5, 100.0, 10.0) for _ in range(25)]
    c = _candles(rows)
    o, h, low, cl, v = c["open"], c["high"], c["low"], c["close"], c["volume"]
    assert of.is_order_block(o, h, low, cl, v, 24) is False


def test_order_block_high_volume_but_tiny_body_is_not_ob():
    # volume spikes but body is tiny (doji) -> not a displacement OB.
    # Baseline bars carry a realistic ~0.3 body so the body-mean is nonzero;
    # the doji's 0.01 body must NOT exceed it.
    rows = [(100.0, 100.5, 99.5, 100.3, 10.0) for _ in range(20)]
    rows.append((100.0, 100.6, 99.4, 100.01, 100.0))  # huge vol, ~0.01 body
    c = _candles(rows)
    o, h, low, cl, v = c["open"], c["high"], c["low"], c["close"], c["volume"]
    assert of.is_order_block(o, h, low, cl, v, 20) is False


# ── Fair Value Gap ──────────────────────────────────────────────────
def test_bullish_fvg_detected_at_known_gap():
    # 3-bar window: bar t-2 high=101, bar t low=103 -> gap [101, 103].
    rows = [
        (100.0, 101.0, 99.0, 100.5, 10.0),  # t-2: high=101
        (101.0, 102.0, 100.5, 101.5, 10.0),  # t-1: middle candle (ignored by def)
        (103.5, 104.0, 103.0, 103.8, 10.0),  # t: low=103 > 101 -> bullish FVG
    ]
    c = _candles(rows)
    gaps = of.bullish_fvgs(c["high"], c["low"], 2)
    assert len(gaps) == 1
    g = gaps[0]
    assert g.created_idx == 2
    assert abs(g.bottom - 101.0) < 1e-9
    assert abs(g.top - 103.0) < 1e-9


def test_no_fvg_when_no_gap():
    rows = [
        (100.0, 101.0, 99.0, 100.5, 10.0),
        (101.0, 102.0, 100.0, 101.5, 10.0),
        (101.5, 102.5, 100.8, 102.0, 10.0),  # low=100.8 < high_{t-2}=101 -> no gap
    ]
    c = _candles(rows)
    assert of.bullish_fvgs(c["high"], c["low"], 2) == []


def test_fvg_mitigation_is_causal():
    # gap [101,103] created at idx 2; a LATER bar (idx 4) dips into it (low=102.5).
    rows = [
        (100.0, 101.0, 99.0, 100.5, 10.0),  # 0  t-2 high=101
        (101.0, 102.0, 100.5, 101.5, 10.0),  # 1  middle
        (103.5, 104.0, 103.0, 103.8, 10.0),  # 2  t low=103 -> FVG [101,103]
        (103.8, 104.5, 103.5, 104.0, 10.0),  # 3  stays above gap (low 103.5 > 103)
        (104.0, 104.2, 102.5, 102.8, 10.0),  # 4  dips to 102.5 <= 103 -> mitigates
    ]
    c = _candles(rows)
    gaps = of.bullish_fvgs(c["high"], c["low"], 4)
    g = next(x for x in gaps if x.created_idx == 2)
    # At i=3 the gap is UNMITIGATED (the mitigating bar 4 hasn't happened yet).
    assert of.fvg_mitigated(g, c["low"], 3) is False
    # At i=4 the gap IS mitigated.
    assert of.fvg_mitigated(g, c["low"], 4) is True


# ── Market Structure Shift ──────────────────────────────────────────
def test_mss_bullish_fires_on_break_with_volume():
    # 20 quiet bars topping out ~101, then a bar that closes above the prior-5 high
    # on above-average volume.
    rows = [(100.0, 101.0, 99.0, 100.0, 10.0) for _ in range(20)]
    rows.append((100.5, 103.0, 100.2, 102.5, 20.0))  # close 102.5 > max(prev5 high=101), vol 20>10
    c = _candles(rows)
    assert of.is_mss_bullish(c["high"], c["close"], c["volume"], 20) is True


def test_mss_no_fire_without_volume():
    rows = [(100.0, 101.0, 99.0, 100.0, 10.0) for _ in range(20)]
    rows.append((100.5, 103.0, 100.2, 102.5, 5.0))  # breaks high but vol 5 < mean 10
    c = _candles(rows)
    assert of.is_mss_bullish(c["high"], c["close"], c["volume"], 20) is False


def test_mss_no_fire_without_break():
    rows = [(100.0, 101.0, 99.0, 100.0, 10.0) for _ in range(20)]
    rows.append((100.5, 100.9, 100.2, 100.8, 20.0))  # high vol but close 100.8 < 101
    c = _candles(rows)
    assert of.is_mss_bullish(c["high"], c["close"], c["volume"], 20) is False


# ── Liquidity sweep ─────────────────────────────────────────────────
def test_liquidity_sweep_and_reclaim():
    # prior 10 lows min ~99; a bar wicks to 98 (below) then closes 100.5 (above).
    rows = [(100.0, 101.0, 99.0, 100.0, 10.0) for _ in range(10)]
    rows.append((100.0, 101.0, 98.0, 100.5, 10.0))  # low 98 < 99, close 100.5 > 99
    c = _candles(rows)
    assert of.is_liquidity_sweep(c["low"], c["close"], 10) is True


def test_no_sweep_when_close_below_swept_level():
    rows = [(100.0, 101.0, 99.0, 100.0, 10.0) for _ in range(10)]
    rows.append((100.0, 100.5, 98.0, 98.5, 10.0))  # low 98 < 99 but close 98.5 < 99 -> no reclaim
    c = _candles(rows)
    assert of.is_liquidity_sweep(c["low"], c["close"], 10) is False


def test_no_sweep_when_low_does_not_breach():
    rows = [(100.0, 101.0, 99.0, 100.0, 10.0) for _ in range(10)]
    rows.append((100.0, 101.0, 99.5, 100.5, 10.0))  # low 99.5 > 99 -> never swept
    c = _candles(rows)
    assert of.is_liquidity_sweep(c["low"], c["close"], 10) is False


# ── OTE / discount zone ─────────────────────────────────────────────
def test_dealing_range_and_discount_zone():
    # Build an up-leg: a confirmed swing low early, then a confirmed swing high,
    # then a retrace into the discount half. Pivot k=2 needs 2 bars each side.
    rows = []
    # swing low at idx 4 (low 90, surrounded by higher lows)
    rows += [(100, 101, 99, 100, 10) for _ in range(2)]  # 0,1
    rows += [(98, 99, 95, 96, 10)]  # 2
    rows += [(95, 96, 92, 93, 10)]  # 3
    rows += [(93, 94, 90, 91, 10)]  # 4  <- swing low (90)
    rows += [(91, 95, 91, 94, 10)]  # 5
    rows += [(94, 99, 94, 98, 10)]  # 6
    # swing high at idx 8 (high 120)
    rows += [(98, 110, 98, 108, 10)]  # 7
    rows += [(108, 120, 107, 118, 10)]  # 8  <- swing high (120)
    rows += [(118, 119, 112, 113, 10)]  # 9
    rows += [(113, 114, 108, 109, 10)]  # 10
    # now retrace down into the discount half (equilibrium = (120+90)/2 = 105)
    rows += [(109, 110, 100, 101, 10)]  # 11  close 101 < 105 -> discount
    c = _candles([tuple(map(float, r)) for r in rows])
    dr = of.latest_dealing_range(c["high"], c["low"], 11, k=2)
    assert dr is not None
    assert abs(dr.swing_low - 90.0) < 1e-9
    assert abs(dr.swing_high - 120.0) < 1e-9
    # OTE = 120 - 0.618*(30) = 101.46
    assert abs(dr.ote_level - (120.0 - 0.618 * 30.0)) < 1e-6
    # close 101 is in the discount half (retrace = (120-101)/30 = 0.633 >= 0.5)
    assert of.in_discount_zone(c["high"], c["low"], c["close"], 11, k=2) is True


def test_premium_zone_is_not_discount():
    rows = []
    rows += [(100, 101, 99, 100, 10) for _ in range(2)]
    rows += [(98, 99, 95, 96, 10)]
    rows += [(95, 96, 92, 93, 10)]
    rows += [(93, 94, 90, 91, 10)]  # swing low 90
    rows += [(91, 95, 91, 94, 10)]
    rows += [(94, 99, 94, 98, 10)]
    rows += [(98, 110, 98, 108, 10)]
    rows += [(108, 120, 107, 118, 10)]  # swing high 120
    rows += [(118, 119, 112, 113, 10)]
    rows += [(113, 114, 110, 112, 10)]
    rows += [(112, 117, 112, 116, 10)]  # close 116 > equilibrium 105 -> premium
    c = _candles([tuple(map(float, r)) for r in rows])
    assert of.in_discount_zone(c["high"], c["low"], c["close"], 11, k=2) is False


# ── Lookahead trap (the structural causality check) ─────────────────
def _lookahead_clean(feat, candles: dict, indices: list[int]) -> bool:
    for i in indices:
        full = feat.compute(candles, i)
        prefix_c = {k: v[: i + 1] for k, v in candles.items()}
        prefix = feat.compute(prefix_c, i)
        if abs(full - prefix) > 1e-9:
            return False
    return True


def _mixed_window(n: int = 80, seed: int = 7) -> dict:
    import random

    rng = random.Random(seed)
    rows = []
    px = 100.0
    for _ in range(n):
        drift = rng.gauss(0, 0.01)
        nxt = px * (1 + drift)
        hi = max(px, nxt) * (1 + abs(rng.gauss(0, 0.005)))
        lo = min(px, nxt) * (1 - abs(rng.gauss(0, 0.005)))
        vol = abs(rng.gauss(20, 8))
        rows.append((px, hi, lo, nxt, vol))
        px = nxt
    return _candles([tuple(map(float, r)) for r in rows])


def test_all_features_are_lookahead_clean():
    c = _mixed_window(90)
    indices = list(range(30, 85))  # leave warmup + room
    for feat in (
        of.OrderBlockFeature(),
        of.FVGFeature(),
        of.MSSFeature(),
        of.LiquiditySweepFeature(),
        of.OTEFeature(),
        of.ICTCombinedEntry(),
    ):
        assert _lookahead_clean(feat, c, indices), f"{feat.name} leaks the future"


def test_fvg_feature_lookahead_clean_around_mitigation():
    # Explicit construction: a gap that gets mitigated late. The FVGFeature value
    # at an early i must NOT change when later (mitigating) bars are revealed.
    rows = [
        (100.0, 101.0, 99.0, 100.5, 10.0),
        (101.0, 102.0, 100.5, 101.5, 10.0),
        (103.5, 104.0, 103.0, 103.8, 10.0),  # FVG [101,103] created
        (103.8, 104.5, 103.5, 104.0, 10.0),  # i=3 unmitigated, close above gap
        (104.0, 104.2, 102.5, 102.8, 10.0),  # i=4 mitigates
    ]
    c = _candles(rows)
    feat = of.FVGFeature()
    # full-series value at i=3 must equal prefix value at i=3 (future bar 4 hidden)
    full3 = feat.compute(c, 3)
    pref3 = feat.compute({k: v[:4] for k, v in c.items()}, 3)
    assert abs(full3 - pref3) < 1e-9
