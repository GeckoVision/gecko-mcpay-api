"""Regime labeling over the historical tape (s46).

REUSES the EXISTING deterministic classifier — chart_floor_calibration.regime_at
(ADX(14): >=25 trend / <=18 chop / between transitional) and its enrich() — so the
tape's regime labels are identical to what the calibration scripts already use.
We do NOT invent a new classifier.

We slide a fixed-length window across each (symbol, tf) tape and label each window
by the MAJORITY per-bar regime within it. For TREND windows we additionally split
trend-up vs trend-down by the sign of the net price change across the window
(close[end] vs close[start]) — the Phase-V harness needs both trend directions as
distinct weather, and the base classifier is direction-agnostic.

Output: a window index — a flat list of labeled windows with (symbol, tf,
start_idx, end_idx, ts_start, ts_end, label, sub_label) — plus a distribution
summary (the key deliverable: do we finally have multi-regime coverage?).
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_CAL = os.path.dirname(_HERE)  # scripts/calibration
sys.path.insert(0, _CAL)

import chart_floor_calibration as base  # noqa: E402  the EXISTING regime classifier

# Window length per timeframe — chosen so each window ~ a coherent regime episode.
# 5m: 36 bars=3h, 15m: 24 bars=6h, 1H: 24 bars=1d, 4H: 18 bars=3d.
WINDOW_BARS: dict[str, int] = {"5m": 36, "15m": 24, "1H": 24, "4H": 18}
WINDOW_STRIDE_DIV = 2  # stride = window // 2 (50% overlap)
DEFAULT_WINDOW = 24


def window_len(tf: str) -> int:
    return WINDOW_BARS.get(tf, DEFAULT_WINDOW)


def label_window(c: dict[str, Any], start: int, end: int) -> tuple[str, str]:
    """Return (label, sub_label) for bars [start, end).

    label    : majority per-bar regime in {trend, transitional, chop} (regime_at).
    sub_label: for trend -> trend_up / trend_down by net close change; else same
               as label.
    """
    votes = Counter(base.regime_at(c, i) for i in range(start, end))
    label = votes.most_common(1)[0][0]
    if label == "trend":
        net = c["close"][end - 1] - c["close"][start]
        return label, "trend_up" if net >= 0 else "trend_down"
    return label, label


def label_tape(symbol: str, tf: str, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Slide labeled windows across one enriched (symbol, tf) tape."""
    c = base.enrich(candles)
    n = len(c["close"])
    w = window_len(tf)
    stride = max(1, w // WINDOW_STRIDE_DIV)
    out: list[dict[str, Any]] = []
    # start after WARMUP so ADX(14)/EMA(50) are trustworthy
    start = base.WARMUP
    while start + w <= n:
        end = start + w
        label, sub = label_window(c, start, end)
        out.append(
            {
                "symbol": symbol,
                "tf": tf,
                "start_idx": start,
                "end_idx": end,
                "ts_start": c["ts"][start],
                "ts_end": c["ts"][end - 1],
                "label": label,
                "sub_label": sub,
            }
        )
        start += stride
    return out


def distribution(windows: list[dict[str, Any]]) -> dict[str, int]:
    """Count windows per sub_label (trend_up / trend_down / transitional / chop)."""
    counts: Counter[str] = Counter(w["sub_label"] for w in windows)
    return dict(counts)


def distribution_by_tf(windows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = {}
    for w in windows:
        out.setdefault(w["tf"], Counter())[w["sub_label"]] += 1
    return {tf: dict(c) for tf, c in out.items()}


def has_multiregime_coverage(windows: list[dict[str, Any]], min_per_regime: int = 5) -> bool:
    """The whole point: do we have >= min_per_regime windows in EACH of the four
    regime buckets (trend_up, trend_down, transitional, chop)?"""
    dist = distribution(windows)
    return all(dist.get(r, 0) >= min_per_regime for r in REGIME_BUCKETS)


REGIME_BUCKETS = ("trend_up", "trend_down", "transitional", "chop")
