"""Tests for the structure Feature conformers.

Load-bearing assertions:
  * each conformer satisfies the Phase V Feature protocol (has .name + .compute);
  * each is LOOKAHEAD-CLEAN on real tape data (the value on the full series equals
    the value on the truncated prefix candles[:i+1]) — the leakage trap;
  * the gate/veto predicates behave (room gate passes open sky + high room, vetoes
    low room; not-down veto blocks DOWN structure; not-mid-range vetoes mid-range).

Run: uv run pytest contest_bot/features/test_structure_features.py -q
"""

from __future__ import annotations

import os
import sys

# structure_features + structure
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# the Phase V spine (feature_validation) lives under scripts/calibration
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "scripts", "calibration"))

import feature_validation as fv  # noqa: E402
import structure_features as sf  # noqa: E402

ALL_FEATURES = [
    sf.OverheadRoomFeature(),
    sf.RoomToRunGate(),
    sf.NotIntoResistanceVeto(),
    sf.NotMidRangeVeto(),
    sf.StructureNotDownVeto(),
    sf.StructureStackGate(),
]


def _synthetic_window(n: int = 200) -> dict:
    # a walk with real swings so pivots/levels/structure are all defined.
    import math
    import random

    rng = random.Random(7)
    close = [100.0]
    for t in range(1, n):
        wave = 3.0 * math.sin(t / 9.0)
        close.append(max(1.0, close[-1] + wave * 0.1 + rng.gauss(0, 0.4)))
    return {
        "ts": [t * 300_000 for t in range(n)],
        "open": close[:],
        "high": [c * 1.004 for c in close],
        "low": [c * 0.996 for c in close],
        "close": close,
        "volume": [1.0] * n,
    }


# ── Protocol conformance ────────────────────────────────────────────
def test_all_features_satisfy_protocol():
    for feat in ALL_FEATURES:
        assert isinstance(feat, fv.Feature), f"{feat.name} is not a Feature"
        assert isinstance(feat.name, str) and feat.name


def test_compute_returns_float():
    c = _synthetic_window()
    for feat in ALL_FEATURES:
        v = feat.compute(c, 120)
        assert isinstance(v, float)


# ── Leakage: lookahead trap on the synthetic window ─────────────────
def test_all_features_are_lookahead_clean():
    c = _synthetic_window()
    indices = list(range(20, len(c["close"]) - 2))
    for feat in ALL_FEATURES:
        assert fv.lookahead_clean(feat, c, indices), f"{feat.name} leaks the future"


# ── Room-to-run gate behavior ───────────────────────────────────────
def test_room_gate_passes_open_sky():
    # entry above all confirmed resistance -> open sky -> gate passes.
    H = [5.0, 9, 5, 4, 5, 20, 20, 20]
    L = [4.0, 7, 3, 2, 3, 18, 18, 18]
    C = [4.5, 8.5, 4.0, 3.0, 4.0, 19, 19, 19]
    c = {
        "high": H,
        "low": L,
        "close": C,
        "open": C,
        "volume": [1] * 8,
        "ts": [i * 3e5 for i in range(8)],
    }
    gate = sf.RoomToRunGate()
    assert gate.passes(c, 6) is True
    assert gate.compute(c, 6) == 1.0


def test_room_gate_vetoes_low_room():
    # entry just under a resistance (tiny room < 2x0.75=1.5%) -> gate vetoes.
    # resistance pivot high = 100@idx2; entry close 99.9 -> room ~0.1%.
    H = [98.0, 99, 100.0, 99, 98, 99.9, 99.9, 99.9]
    L = [97.0, 97, 99.0, 97, 96, 98.0, 98.0, 98.0]
    C = [97.5, 98, 99.5, 98, 97, 99.9, 99.9, 99.9]
    c = {
        "high": H,
        "low": L,
        "close": C,
        "open": C,
        "volume": [1] * 8,
        "ts": [i * 3e5 for i in range(8)],
    }
    gate = sf.RoomToRunGate(fee_rt=0.75, room_multiple=2.0)  # threshold 1.5%
    assert gate.passes(c, 6) is False
    assert gate.compute(c, 6) == 0.0


def test_room_gate_threshold_scales_with_fee():
    assert sf.RoomToRunGate(fee_rt=0.5, room_multiple=2.0).threshold_pct == 1.0
    assert sf.RoomToRunGate(fee_rt=0.75, room_multiple=2.0).threshold_pct == 1.5


# ── Structure-not-down veto ─────────────────────────────────────────
def test_not_down_veto_blocks_down_structure():
    # build a clean LH/LL down zig-zag.
    from test_structure import _zigzag  # reuse the helper

    dn_h, dn_l, mid = _zigzag(
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
    c = {
        "high": dn_h,
        "low": dn_l,
        "close": mid,
        "open": mid,
        "volume": [1] * len(mid),
        "ts": [i * 3e5 for i in range(len(mid))],
    }
    veto = sf.StructureNotDownVeto()
    assert veto.passes(c, 24) is False
    assert veto.compute(c, 24) == 0.0


def test_not_down_veto_allows_up_structure():
    from test_structure import _zigzag

    up_h, up_l, mid = _zigzag(
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
    c = {
        "high": up_h,
        "low": up_l,
        "close": mid,
        "open": mid,
        "volume": [1] * len(mid),
        "ts": [i * 3e5 for i in range(len(mid))],
    }
    veto = sf.StructureNotDownVeto()
    assert veto.passes(c, 24) is True
    assert veto.compute(c, 24) == 1.0


# ── Not-mid-range veto ──────────────────────────────────────────────
def test_mid_range_is_vetoed_edges_pass():
    H = [5.0, 6, 10, 6, 5, 7, 7, 7]  # range high 10@2
    L = [4.0, 4, 8, 4, 2, 5, 5, 5]  # range low 2@4
    base = {"high": H, "low": L, "open": H, "volume": [1] * 8, "ts": [i * 3e5 for i in range(8)]}
    veto = sf.NotMidRangeVeto(half_width=0.15)
    # mid-range close (~6 -> pos 0.5) -> vetoed
    c_mid = {**base, "close": [4.5, 5, 9, 5, 3, 6.0, 6.0, 6.0]}
    assert veto.passes(c_mid, 6) is False
    # near the high boundary -> passes
    c_hi = {**base, "close": [4.5, 5, 9, 5, 3, 9.8, 9.8, 9.8]}
    assert veto.passes(c_hi, 6) is True
