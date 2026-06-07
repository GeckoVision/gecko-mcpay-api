"""S58 — min_hold_until stamping on paper Multiply opens (completes the lock loop).

Opening a lot with a configured round-trip cost stamps its break-even hold; the
apply_actions lock then defers optimization exits until that time. Default (no
cost) = no stamp = inert lock (backward-compatible).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import kamino.vault_orchestrator as vo  # noqa: E402
from kamino.monitor import ROTATE  # noqa: E402
from kamino.multiply import LeverageStrategy  # noqa: E402

NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=UTC)
LST = LeverageStrategy(
    "JitoSOL/SOL 4x", 0.07, 0.06, 4.0, 0.90, 0.93, True, "lst_staking"
)  # net 0.10


def test_default_no_cost_leaves_lot_unstamped():
    o = vo.VaultOrchestrator(profile="aggressive")  # round_trip_cost_pct defaults to 0.0
    o._add_to_lot(LST, 1000.0, now=NOW)
    assert o.lots[0].min_hold_until == "" and o.lots[0].entry_ts == ""


def test_cost_stamps_break_even_hold():
    o = vo.VaultOrchestrator(profile="aggressive", round_trip_cost_pct=0.0027)
    o._add_to_lot(LST, 1000.0, now=NOW)
    lot = o.lots[0]
    assert lot.entry_ts == NOW.isoformat()
    until = datetime.fromisoformat(lot.min_hold_until)
    assert until > NOW  # break-even is in the future (~10 days at net 10% / 0.27% cost)


def test_topup_keeps_original_entry_ts():
    o = vo.VaultOrchestrator(profile="aggressive", round_trip_cost_pct=0.0027)
    o._add_to_lot(LST, 1000.0, now=NOW)
    first_entry = o.lots[0].entry_ts
    o._add_to_lot(LST, 500.0, now=NOW + timedelta(days=3))  # top-up later
    assert len(o.lots) == 1
    assert o.lots[0].entry_ts == first_entry  # not reset
    assert o.lots[0].principal_usd == 1500.0


def test_stamp_drives_the_lock_end_to_end():
    o = vo.VaultOrchestrator(profile="aggressive", round_trip_cost_pct=0.0027)
    o._add_to_lot(LST, 1000.0, now=NOW)
    rotate = {
        "source": "lst_staking",
        "action": ROTATE,
        "reason": "better yield",
        "suggested_leverage": 5.0,
        "safety": False,
    }
    # before break-even: optimization ROTATE is deferred (lot unchanged)
    o.apply_actions([rotate], now=NOW)
    assert o.lots[0].strategy.leverage == 4.0
    # after break-even: the same ROTATE applies
    later = datetime.fromisoformat(o.lots[0].min_hold_until) + timedelta(days=1)
    o.apply_actions([rotate], now=later)
    assert o.lots[0].strategy.leverage == 5.0


def test_no_lock_when_yield_nonpositive():
    o = vo.VaultOrchestrator(profile="aggressive", round_trip_cost_pct=0.0027)
    bleeder = LeverageStrategy("bleeder", 0.04, 0.06, 4.0, 0.90, 0.93, True, "lst_staking")  # net<0
    o._add_to_lot(bleeder, 1000.0, now=NOW)
    assert o.lots[0].min_hold_until == ""  # never clears cost → no lock
