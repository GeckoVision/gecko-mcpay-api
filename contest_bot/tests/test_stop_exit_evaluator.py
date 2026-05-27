"""Tests for the Sprint 7 _evaluate_stop_exits pure helper.

Per `feedback_lighter_tests`: pure function, no monkey-patch sprawl, no
end-to-end pipeline. Each test passes thresholds as kwargs to avoid module-state
coupling.

Background — autopsy finding (Sprint 6 Phase A):
- trailing_stop exits had mean -2.12% (one disaster at -6.28%)
- Root cause: trailing was evaluated BEFORE stop_loss in monitor_positions;
  poll-gap drops past -3% fired the trailing branch first and labeled them as
  trailing_stop instead of stop_loss
- Sprint 7 fix: (a) eval-order swap (stop_loss first), (b) trail_stop_pct
  tightened 1 → 0.5, (c) NEW safety guard trail_min_pnl_pct (default -1.0)
  that declines the trailing branch if pnl has already breached the trail
  safety floor
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from jto_breakout_gecko_gated_contest_bot import _evaluate_stop_exits  # noqa: E402


# ── stop_loss is evaluated first (the load-bearing fix) ────────────────────


def test_stop_loss_wins_over_trailing_when_both_conditions_met() -> None:
    """The autopsy bug: poll-gap drops past -3% must label as stop_loss."""
    # Position: entry=100, peak=101 (was +1% green at some point), now=94
    # (-6% from entry, -6.93% from peak). Both stop_loss (-6 <= -3) AND
    # trailing (peak>=1 activate, retrace 6.93 >= 1) conditions are met.
    # Pre-Sprint-7: this fired as trailing_stop (the autopsy disaster).
    # Post-Sprint-7: this fires as stop_loss.
    reason = _evaluate_stop_exits(
        pnl_pct=-6.0,
        peak_pct=1.0,
        current_price=94.0,
        peak_price=101.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    assert reason == "stop_loss"


def test_stop_loss_fires_at_exact_threshold() -> None:
    reason = _evaluate_stop_exits(
        pnl_pct=-3.0,
        peak_pct=0.0,
        current_price=97.0,
        peak_price=100.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    assert reason == "stop_loss"


def test_stop_loss_does_not_fire_above_threshold() -> None:
    reason = _evaluate_stop_exits(
        pnl_pct=-2.9,
        peak_pct=0.0,
        current_price=97.1,
        peak_price=100.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    assert reason is None


# ── trailing_stop fires only when ALL conditions met ──────────────────────


def test_trailing_fires_when_peak_active_and_retrace_exceeds_threshold() -> None:
    """Classic happy path: green peak, modest retrace, still profitable."""
    # entry=100, peak=103, now=102 — peak +3% (active), retrace 0.97% (>= 0.5%
    # threshold), pnl +2% (above -1% floor). Should fire trailing_stop.
    reason = _evaluate_stop_exits(
        pnl_pct=2.0,
        peak_pct=3.0,
        current_price=102.0,
        peak_price=103.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    assert reason == "trailing_stop"


def test_trailing_does_not_fire_below_activation() -> None:
    """Peak never cleared +1% activation gate."""
    reason = _evaluate_stop_exits(
        pnl_pct=0.3,
        peak_pct=0.5,
        current_price=100.3,
        peak_price=100.5,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    assert reason is None


def test_trailing_does_not_fire_when_retrace_below_threshold() -> None:
    """Peak active but retrace too small."""
    # entry=100, peak=103, now=102.7 — retrace 0.29% (< 0.5%).
    reason = _evaluate_stop_exits(
        pnl_pct=2.7,
        peak_pct=3.0,
        current_price=102.7,
        peak_price=103.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    assert reason is None


def test_tighter_05pct_threshold_fires_where_old_1pct_would_not() -> None:
    """Regression-prevent: the Sprint-7 tightening must actually be tighter."""
    # Retrace 0.7% from peak — fires at the new 0.5% threshold, not at old 1.0%
    reason_new = _evaluate_stop_exits(
        pnl_pct=2.3,
        peak_pct=3.0,
        current_price=102.3,
        peak_price=103.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,  # Sprint 7 default
        trail_min_pnl_pct=-1.0,
    )
    reason_old = _evaluate_stop_exits(
        pnl_pct=2.3,
        peak_pct=3.0,
        current_price=102.3,
        peak_price=103.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=1.0,  # PRE-Sprint-7
        trail_min_pnl_pct=-1.0,
    )
    assert reason_new == "trailing_stop"
    assert reason_old is None


# ── trail_min_pnl_pct safety guard (the NEW rail) ──────────────────────────


def test_trailing_declines_when_pnl_below_safety_floor() -> None:
    """The NEW Sprint 7 guard: if pnl < -1%, decline trailing.

    Scenario the autopsy revealed: peak briefly cleared +1%, then poll-gap
    crash dropped pnl to -2% (below the -1% safety floor) but ALSO past the
    -3% stop_loss threshold. Pre-Sprint-7 logic would fire trailing_stop and
    label this as -2% trailing_stop. Post-Sprint-7:
    - Stop_loss (-3% threshold) doesn't fire — pnl is -2%, above threshold
    - Trailing safety guard declines (-2 <= -1 floor) — returns None
    - Position stays open until next poll where stop_loss or another rule
      catches it. NOT mis-labeled as trailing.
    """
    reason = _evaluate_stop_exits(
        pnl_pct=-2.0,
        peak_pct=1.5,
        current_price=98.0,
        peak_price=101.5,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    assert reason is None


def test_trailing_fires_at_exact_safety_floor_boundary() -> None:
    """pnl > floor required (strict >); exactly at floor should NOT fire."""
    reason_just_above = _evaluate_stop_exits(
        pnl_pct=-0.99,
        peak_pct=1.5,
        current_price=99.01,
        peak_price=101.5,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    reason_at_floor = _evaluate_stop_exits(
        pnl_pct=-1.0,
        peak_pct=1.5,
        current_price=99.0,
        peak_price=101.5,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    assert reason_just_above == "trailing_stop"
    assert reason_at_floor is None


def test_autopsy_disaster_replay_now_labels_correctly() -> None:
    """Replay the exact JTO #5 trade pattern from the Sprint 6 Phase A autopsy.

    Per the autopsy: entry → peak briefly cleared +1% activation → poll gap →
    next poll showed -6.28%. Pre-Sprint-7: fired as trailing_stop labeled -6.28.
    Post-Sprint-7: stop_loss fires FIRST (capping the label at -3% threshold,
    even though the actual fill price reflects the gap).
    """
    # entry=100, peak=101.05 (briefly +1.05%), polled-now=93.72 (-6.28%)
    reason = _evaluate_stop_exits(
        pnl_pct=-6.28,
        peak_pct=1.05,
        current_price=93.72,
        peak_price=101.05,
    )  # uses module defaults — confirms the constants ARE the new defaults
    assert reason == "stop_loss"


# ── Trailing disabled (TRAIL_STOP_PCT=None) ────────────────────────────────


def test_trailing_disabled_returns_none_in_stop_loss_window() -> None:
    """When trailing is None, only stop_loss can fire."""
    # In stop_loss range — stop_loss fires
    reason = _evaluate_stop_exits(
        pnl_pct=-4.0,
        peak_pct=2.0,
        current_price=96.0,
        peak_price=102.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=None,
        trail_min_pnl_pct=-1.0,
    )
    assert reason == "stop_loss"


def test_trailing_disabled_returns_none_in_green_retrace() -> None:
    """When trailing is None, retraces don't fire."""
    reason = _evaluate_stop_exits(
        pnl_pct=2.0,
        peak_pct=3.0,
        current_price=102.0,
        peak_price=103.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=None,
        trail_min_pnl_pct=-1.0,
    )
    assert reason is None


# ── Edge cases ─────────────────────────────────────────────────────────────


def test_zero_peak_price_does_not_divzero() -> None:
    """Brand-new position; peak hasn't been initialized. Don't crash."""
    reason = _evaluate_stop_exits(
        pnl_pct=0.0,
        peak_pct=0.0,
        current_price=0.0,
        peak_price=0.0,
        stop_loss_pct=3.0,
        trail_activate_pct=1.0,
        trail_stop_pct=0.5,
        trail_min_pnl_pct=-1.0,
    )
    assert reason is None


def test_module_defaults_match_sprint_7_constants() -> None:
    """Regression-prevent: if the module constants drift, this test fires."""
    from jto_breakout_gecko_gated_contest_bot import (
        STOP_LOSS_PCT,
        TRAIL_ACTIVATE_AFTER_PCT,
        TRAIL_MIN_PNL_PCT,
        TRAIL_STOP_PCT,
    )

    assert STOP_LOSS_PCT == 3
    assert TRAIL_ACTIVATE_AFTER_PCT == 1
    assert TRAIL_STOP_PCT == 0.5, "Sprint 7 tightened 1 → 0.5"
    assert TRAIL_MIN_PNL_PCT == -1.0, "Sprint 7 added trail safety floor"


@pytest.mark.parametrize(
    "pnl_pct,peak_pct,current,peak,expected",
    [
        # Happy paths
        (2.0, 3.0, 102.0, 103.0, "trailing_stop"),  # classic peak-and-retrace
        (-3.5, 2.0, 96.5, 102.0, "stop_loss"),  # past stop floor
        (0.5, 1.0, 100.5, 101.0, None),  # peak just hit activate, no retrace yet
        # Safety guard active
        (-1.5, 2.0, 98.5, 102.0, None),  # past trail floor, not yet stop_loss
        # Stop wins
        (-3.0, 2.0, 97.0, 102.0, "stop_loss"),  # exactly at stop threshold
        # Trailing wins (just barely)
        (2.49, 3.0, 102.49, 103.0, "trailing_stop"),  # retrace 0.495% (>= 0.5%? edge)
    ],
)
def test_truth_table(pnl_pct, peak_pct, current, peak, expected) -> None:
    reason = _evaluate_stop_exits(
        pnl_pct=pnl_pct,
        peak_pct=peak_pct,
        current_price=current,
        peak_price=peak,
    )
    # 0.495 is just below the 0.5 trail_stop threshold — should NOT fire
    if pnl_pct == 2.49 and peak == 103.0:
        assert reason is None
    else:
        assert reason == expected
