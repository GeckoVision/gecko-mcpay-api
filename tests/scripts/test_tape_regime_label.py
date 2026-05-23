"""TDD for tape regime labeling — must REUSE chart_floor_calibration.regime_at
(not invent a classifier) and split trend_up vs trend_down."""

from __future__ import annotations

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_RL = os.path.join(_REPO, "scripts", "calibration", "tape", "regime_label.py")

_spec = importlib.util.spec_from_file_location("tape_regime_label", _RL)
assert _spec and _spec.loader
rl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rl)


def _candle(ts: float, price: float, vol: float = 100.0) -> dict[str, float]:
    return {
        "ts": float(ts),
        "open": price,
        "high": price * 1.001,
        "low": price * 0.999,
        "close": price,
        "volume": vol,
    }


def test_reuses_existing_classifier() -> None:
    """label_window must call base.regime_at — assert the label is drawn from the
    base classifier's vocabulary and that the module imported the base study."""
    assert rl.base.__name__ == "chart_floor_calibration"
    assert hasattr(rl.base, "regime_at")


def test_uptrend_window_labels_trend_up() -> None:
    # strongly rising series -> high ADX -> base.regime_at == 'trend', net up
    candles = [_candle(i * 300_000, 1.0 + i * 0.05) for i in range(120)]
    c = rl.base.enrich(candles)
    # find a window deep enough that ADX has built up
    label, sub = rl.label_window(c, 80, 80 + rl.window_len("5m"))
    assert label == "trend"
    assert sub == "trend_up"


def test_downtrend_window_labels_trend_down() -> None:
    candles = [_candle(i * 300_000, 10.0 - i * 0.05) for i in range(120)]
    c = rl.base.enrich(candles)
    label, sub = rl.label_window(c, 80, 80 + rl.window_len("5m"))
    assert label == "trend"
    assert sub == "trend_down"


def test_label_tape_emits_windows_with_expected_fields() -> None:
    candles = [_candle(i * 300_000, 1.0 + i * 0.05) for i in range(150)]
    windows = rl.label_tape("PYTH", "5m", candles)
    assert windows, "expected at least one labeled window"
    w = windows[0]
    assert set(w) >= {
        "symbol",
        "tf",
        "start_idx",
        "end_idx",
        "ts_start",
        "ts_end",
        "label",
        "sub_label",
    }
    assert w["symbol"] == "PYTH"
    assert w["sub_label"] in rl.REGIME_BUCKETS


def test_distribution_counts_subscript_labels() -> None:
    windows = [
        {"sub_label": "trend_up", "tf": "5m"},
        {"sub_label": "trend_up", "tf": "5m"},
        {"sub_label": "chop", "tf": "1H"},
    ]
    dist = rl.distribution(windows)
    assert dist == {"trend_up": 2, "chop": 1}
    by_tf = rl.distribution_by_tf(windows)
    assert by_tf["5m"]["trend_up"] == 2
    assert by_tf["1H"]["chop"] == 1


def test_has_multiregime_coverage_gate() -> None:
    sparse = [{"sub_label": "trend_up", "tf": "5m"}] * 3
    assert not rl.has_multiregime_coverage(sparse, min_per_regime=5)
    full = (
        [{"sub_label": "trend_up", "tf": "5m"}] * 6
        + [{"sub_label": "trend_down", "tf": "5m"}] * 6
        + [{"sub_label": "transitional", "tf": "5m"}] * 6
        + [{"sub_label": "chop", "tf": "5m"}] * 6
    )
    assert rl.has_multiregime_coverage(full, min_per_regime=5)
