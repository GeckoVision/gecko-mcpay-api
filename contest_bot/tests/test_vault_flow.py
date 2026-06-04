"""S44/S45/S47 — vault gate + orchestrator + Oracle-downside bridge. Pure, no network."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from kamino import monitor as mon  # noqa: E402
from kamino import vault_gate as vg  # noqa: E402
from kamino import vault_orchestrator as vo  # noqa: E402
from kamino.multiply import LeverageStrategy  # noqa: E402


def _pol(**kw):
    base = {"max_allocation_usd": 10_000.0}
    base.update(kw)
    return vg.VaultPolicy(**base)


def _lst(lev):
    return LeverageStrategy("lst", 0.07, 0.06, lev, 0.90, 0.93, True, "lst_staking")


# ── gate ──────────────────────────────────────────────────────────────────
def test_gate_denies_when_disabled():
    v = vg.vault_check(vg.DEPOSIT, 100.0, vg.VaultPolicy(max_allocation_usd=0.0))
    assert not v.allow and any("disabled" in r for r in v.reasons)


def test_gate_denies_over_allocation_cap():
    v = vg.vault_check(vg.DEPOSIT, 600.0, _pol(max_allocation_usd=1000.0), current_allocation_usd=500.0)
    assert not v.allow and any("allocation cap" in r for r in v.reasons)


def test_gate_denies_kill_switch():
    v = vg.vault_check(vg.DEPOSIT, 100.0, _pol(kill_switch=True))
    assert not v.allow and any("kill_switch" in r for r in v.reasons)


def test_gate_refuses_deposit_into_exit_position():
    # inverted-spread strategy → monitor EXIT → gate blocks the deposit
    bad = LeverageStrategy("x", 0.0632, 0.0808, 4.0, 0.85, 0.90, True, "stable_spread")
    v = vg.vault_check(vg.DEPOSIT, 100.0, _pol(), strategy=bad)
    assert not v.allow and v.monitor_action == mon.EXIT


def test_gate_allows_clean_deposit():
    v = vg.vault_check(vg.DEPOSIT, 100.0, _pol(hurdle=mon.CRYPTO_ONLY), strategy=_lst(4.0))
    assert v.allow and not v.reasons


def test_gate_denies_leverage_over_cap():
    v = vg.vault_check(vg.DEPOSIT, 100.0, _pol(max_leverage=5.0), strategy=_lst(8.0))
    assert not v.allow and any("leverage" in r for r in v.reasons)


# ── orchestrator ────────────────────────────────────────────────────────────
def test_allocate_conservative_single_lot():
    orch = vo.VaultOrchestrator(profile="conservative", policy=_pol(), hurdle=mon.CRYPTO_ONLY)
    rep = orch.allocate_profit(1000.0)
    assert len(orch.lots) == 1 and orch.lots[0].source == "stable_spread"
    assert abs(orch.allocation_usd - 1000.0) < 1e-6
    assert rep["deposited"] and not rep["denied"]


def test_allocate_aggressive_three_lots_weighted():
    orch = vo.VaultOrchestrator(profile="aggressive", policy=_pol(max_leverage=10.0), hurdle=mon.CRYPTO_ONLY)
    orch.allocate_profit(1000.0)
    sources = {lot.source for lot in orch.lots}
    assert sources == {"lst_staking", "jlp_fees", "stable_spread"}
    # 50/30/20 split
    by = {lot.source: lot.principal_usd for lot in orch.lots}
    assert abs(by["lst_staking"] - 500.0) < 1e-6 and abs(by["jlp_fees"] - 300.0) < 1e-6


def test_allocate_respects_allocation_cap():
    orch = vo.VaultOrchestrator(profile="conservative", policy=_pol(max_allocation_usd=400.0), hurdle=mon.CRYPTO_ONLY)
    rep = orch.allocate_profit(1000.0)
    assert rep["denied"] and not orch.lots  # 1000 > 400 cap → denied, nothing deposited


def test_monitor_tick_and_exit_action():
    orch = vo.VaultOrchestrator(profile="aggressive", policy=_pol(max_leverage=10.0), hurdle=mon.CRYPTO_ONLY)
    orch.allocate_profit(1000.0)
    # big predicted downside → the volatile JLP lot should EXIT
    verdicts = orch.monitor_tick(predicted_drawdown_pct=0.30)
    jlp = next(v for v in verdicts if v["source"] == "jlp_fees")
    assert jlp["action"] in (mon.EXIT, mon.DELEVERAGE)
    before = len(orch.lots)
    orch.apply_actions(verdicts)
    assert len(orch.lots) <= before  # exited lots removed


def test_apply_actions_deleverages():
    orch = vo.VaultOrchestrator(profile="moderate", policy=_pol(), hurdle=mon.CRYPTO_ONLY)
    orch.lots = [vo.VaultLot("jlp_fees", 100.0, LeverageStrategy("j", 0.12, 0.06, 5.0, 0.90, 0.93, False, "jlp_fees"))]
    verdicts = orch.monitor_tick(predicted_drawdown_pct=0.10)  # within buffer → DELEVERAGE
    orch.apply_actions(verdicts)
    assert orch.lots[0].strategy.leverage < 5.0


def test_snapshot_shape():
    orch = vo.VaultOrchestrator(profile="conservative", policy=_pol(), hurdle=mon.CRYPTO_ONLY)
    orch.allocate_profit(500.0)
    snap = orch.snapshot()
    assert snap["profile"] == "conservative" and snap["lots"] and "liquidation_drop_pct" in snap["lots"][0]


def test_allocate_never_raises_on_bad_profile():
    orch = vo.VaultOrchestrator(profile="nonexistent", policy=_pol(), hurdle=mon.CRYPTO_ONLY)
    rep = orch.allocate_profit(100.0)  # falls back to conservative, doesn't raise
    assert "deposited" in rep


# ── Oracle bridge (S47) ───────────────────────────────────────────────────
def test_predicted_drawdown_risk_off():
    assert vo.predicted_drawdown_from_market_temp({"temp": -0.57, "label": "risk_off"}) == 0.15


def test_predicted_drawdown_cool():
    assert vo.predicted_drawdown_from_market_temp({"temp": -0.10, "label": "cool"}) == 0.08


def test_predicted_drawdown_neutral_is_none():
    assert vo.predicted_drawdown_from_market_temp({"temp": 0.0, "label": "neutral"}) is None


def test_predicted_drawdown_stale_is_none():
    assert vo.predicted_drawdown_from_market_temp({"temp": -0.57, "stale": True}) is None
    assert vo.predicted_drawdown_from_market_temp(None) is None
