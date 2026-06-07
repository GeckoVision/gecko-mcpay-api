import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from kamino.monitor import DELEVERAGE, EXIT, HOLD, ROTATE, apply_min_hold_lock  # noqa: E402


def test_optimization_exit_suppressed_before_min_hold():
    out = apply_min_hold_lock(ROTATE, reason="better_yield_elsewhere", locked=True, safety=False)
    assert out["action"] == HOLD and out["locked"] is True
    assert out["deferred_reason"] == "better_yield_elsewhere"


def test_deleverage_for_yield_suppressed_before_min_hold():
    out = apply_min_hold_lock(DELEVERAGE, reason="spread_compression", locked=True, safety=False)
    assert out["action"] == HOLD


def test_safety_exit_overrides_lock():
    out = apply_min_hold_lock(EXIT, reason="pegana_depeg", locked=True, safety=True)
    assert out["action"] == EXIT and out["override"] == "pegana_depeg"


def test_safety_deleverage_overrides_lock():
    out = apply_min_hold_lock(DELEVERAGE, reason="liquidation_distance", locked=True, safety=True)
    assert out["action"] == DELEVERAGE and out["override"] == "liquidation_distance"


def test_no_suppression_after_min_hold():
    out = apply_min_hold_lock(ROTATE, reason="better_yield_elsewhere", locked=False, safety=False)
    assert out["action"] == ROTATE
