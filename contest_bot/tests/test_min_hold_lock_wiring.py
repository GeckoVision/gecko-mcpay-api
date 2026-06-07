import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import kamino.vault_orchestrator as vo  # noqa: E402
from kamino.monitor import EXIT, ROTATE  # noqa: E402
from kamino.multiply import LeverageStrategy  # noqa: E402

NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=UTC)
FUTURE = (NOW + timedelta(days=10)).isoformat()
PAST = (NOW - timedelta(days=1)).isoformat()


def _orch_with_locked_lot(min_hold_until: str) -> vo.VaultOrchestrator:
    o = vo.VaultOrchestrator(profile="Balanced")
    o.lots.append(
        vo.VaultLot(
            source="lst_staking",
            principal_usd=600.0,
            strategy=LeverageStrategy(
                "JitoSOL/SOL 4x", 0.07, 0.06, 4.0, 0.90, 0.93, True, "lst_staking"
            ),
            min_hold_until=min_hold_until,
        )
    )
    return o


def test_optimization_rotate_deferred_while_locked():
    o = _orch_with_locked_lot(FUTURE)
    changed = o.apply_actions(
        [
            {
                "source": "lst_staking",
                "action": ROTATE,
                "reason": "better yield",
                "suggested_leverage": 5.0,
                "safety": False,
            }
        ],
        now=NOW,
    )
    assert changed and changed[0]["did"].startswith("deferred")
    assert o.lots[0].strategy.leverage == 4.0  # unchanged — lock held


def test_safety_exit_fires_while_locked():
    o = _orch_with_locked_lot(FUTURE)
    changed = o.apply_actions(
        [{"source": "lst_staking", "action": EXIT, "reason": "pegana depeg", "safety": True}],
        now=NOW,
    )
    assert changed[0]["did"] == "exited"
    assert o.lots == []  # safety override beats the lock


def test_rotate_executes_when_not_locked():
    o = _orch_with_locked_lot(PAST)  # min-hold already elapsed
    o.apply_actions(
        [
            {
                "source": "lst_staking",
                "action": ROTATE,
                "reason": "x",
                "suggested_leverage": 5.0,
                "safety": False,
            }
        ],
        now=NOW,
    )
    assert o.lots[0].strategy.leverage == 5.0


def test_monitor_tick_tags_safety_on_spread_inversion():
    o = vo.VaultOrchestrator(profile="aggressive")
    o.lots.append(
        vo.VaultLot(
            source="lst_staking",
            principal_usd=600.0,
            strategy=LeverageStrategy("inverted", 0.04, 0.06, 4.0, 0.90, 0.93, True, "lst_staking"),
        )
    )
    verdicts = o.monitor_tick()
    assert verdicts[0]["action"] == EXIT and verdicts[0]["safety"] is True
