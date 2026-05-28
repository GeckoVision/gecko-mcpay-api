"""gecko-copy-trade-grader — smoke tests.

Light-weight tests covering: grade_trades on a winner, grade_trades on a
gambler, grade_okx_trader_from_payload on the bundled sample, and the
cross-period stability helper.

Per project conventions (CLAUDE.md): light fakes, no over-mocking, targeted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `grader` importable from anywhere
SKILL_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_DIR))

from grader import (
    grade_trades,
    grade_okx_trader_from_payload,
    cross_period_stability,
)


def test_grade_trades_one_big_win_n_small_losses_is_C_or_D():
    """Heavy-tail winner — 1 big win + 5 small losses. Tail-heavy, downgraded for small N."""
    trades = [
        {"entry_ts_ms": 1, "exit_ts_ms": 2, "symbol": "SUI", "side": "long",
         "entry_px": 1.0, "exit_px": 1.24, "size_usd": 1000, "realized_pnl_usd": 237, "realized_pnl_pct": 23.7},
        *[{"entry_ts_ms": 3 + i, "exit_ts_ms": 4 + i, "symbol": "X", "side": "long",
           "entry_px": 1.0, "exit_px": 0.99, "size_usd": 1000, "realized_pnl_usd": -10, "realized_pnl_pct": -1.0}
          for i in range(5)]
    ]
    sc = grade_trades(trades, trader_label="tail_winner", n_peers=200)
    assert sc.n_trades == 6
    assert sc.grade in ("C", "D")  # small-N + low Sharpe even though profit factor > 1
    assert sc.win_loss_ratio > 5  # huge asymmetry


def test_grade_trades_steady_consistent_winner_is_B_at_min():
    """40 trades, 80% win-rate +1.5%/-0.3% — should clear B."""
    trades = []
    for i in range(40):
        # Pattern: 4 wins, 1 loss repeating (80% win-rate)
        is_win = (i % 5) != 0
        pct = 1.5 if is_win else -0.3
        trades.append({
            "entry_ts_ms": i * 86400_000,
            "exit_ts_ms": (i + 1) * 86400_000,
            "symbol": "X", "side": "long",
            "entry_px": 1.0, "exit_px": 1.0 + pct / 100,
            "size_usd": 1000, "realized_pnl_usd": pct * 10, "realized_pnl_pct": pct,
        })
    sc = grade_trades(trades, trader_label="steady", n_peers=50)
    assert sc.n_trades == 40
    assert sc.grade in ("A", "B"), f"Expected A/B, got {sc.grade} with Sharpe {sc.sharpe_per_trade}"
    assert sc.win_rate_pct >= 75


def test_grade_trades_gambling_profile_is_D():
    """30 trades with -5% catastrophic losses 40% of the time → D."""
    trades = []
    for i in range(30):
        if i % 5 < 2:
            pct = -5.0  # catastrophic 40% of the time
        else:
            pct = 0.5
        trades.append({
            "entry_ts_ms": i * 86400_000,
            "exit_ts_ms": (i + 1) * 86400_000,
            "symbol": "X", "side": "long",
            "entry_px": 1.0, "exit_px": 1.0 + pct / 100,
            "size_usd": 1000, "realized_pnl_usd": pct * 10, "realized_pnl_pct": pct,
        })
    sc = grade_trades(trades, trader_label="gambler", n_peers=50)
    assert sc.grade == "D"
    assert sc.catastrophic_rate_pct >= 25


def test_grade_okx_trader_from_payload_sample():
    """Bundled OKX sample should grade cleanly."""
    sample = json.loads((SKILL_DIR / "examples" / "okx_top5_snapshot.json").read_text())
    traders = sample["data"]
    grades = [grade_okx_trader_from_payload(t) for t in traders]
    assert len(grades) == 5
    assert all("grade" in g for g in grades)
    # 天王盖地虎M should grade A (Sharpe 11+ per our 2026-05-28 analysis)
    tianwang = next((g for g in grades if "天王" in g.get("nickname", "")), None)
    assert tianwang is not None
    assert tianwang["grade"] in ("A", "B")
    # 三年好日子 should grade D (cat-rate 65% per our 2026-05-28 analysis)
    bad = next((g for g in grades if "三年好日子" in g.get("nickname", "")), None)
    assert bad is not None
    assert bad["grade"] == "D"


def test_cross_period_stability_runs_on_2_periods():
    """Smoke: 2 periods, 3 traders each (1 stable, 1 flip, 1 in one period only)."""
    p30 = [
        {"authorId": "A", "nickname": "stable", "grade": "A"},
        {"authorId": "B", "nickname": "flipper", "grade": "A"},
        {"authorId": "C", "nickname": "only_30d", "grade": "B"},
    ]
    p90 = [
        {"authorId": "A", "nickname": "stable", "grade": "A"},
        {"authorId": "B", "nickname": "flipper", "grade": "D"},
        {"authorId": "D", "nickname": "only_90d", "grade": "C"},
    ]
    summary = cross_period_stability({"30d": p30, "90d": p90})
    assert "stable A/B" in summary
    assert "FLIP" in summary
    assert "stable" in summary.lower()
