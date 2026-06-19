"""Tests for the shared safety-gate kernel + PrecomputedSafety (step 2).

The gate is duck-typed, so we exercise it with lightweight namespace stand-ins
for a ``SafetyBlock`` (no orchestration import needed — that is the point of the
hotpath-clean kernel).
"""

from __future__ import annotations

from types import SimpleNamespace

from gecko_core.trade_agent.hotpath.precomputed import (
    PrecomputedSafety,
    SafetyStore,
    safety_gate,
)
from gecko_core.trade_agent.hotpath.wash_signals import WashRiskBlock


def _block(*, checked=True, honeypot=False, rug_flags=None, imev_label=None):
    imev = SimpleNamespace(label=imev_label) if imev_label is not None else None
    return SimpleNamespace(
        checked=checked,
        honeypot=honeypot,
        rug_flags=rug_flags or [],
        information_mev=imev,
    )


# --------------------------------------------------------------------------- #
# safety_gate — static read                                                    #
# --------------------------------------------------------------------------- #


def test_unchecked_is_unknown():
    assert safety_gate(_block(checked=False)) == "unknown"


def test_honeypot_blocks():
    assert safety_gate(_block(honeypot=True)) == "block"


def test_fake_market_cap_blocks():
    assert safety_gate(_block(rug_flags=["fake_market_cap"])) == "block"


def test_depeg_blocks():
    assert safety_gate(_block(rug_flags=["depeg_risk"])) == "block"


def test_imev_manipulated_blocks():
    assert safety_gate(_block(imev_label="manipulated")) == "block"


def test_caution_flags_caution():
    assert safety_gate(_block(rug_flags=["thin_liquidity_vs_mcap"])) == "caution"
    assert safety_gate(_block(rug_flags=["high_holder_concentration"])) == "caution"
    assert safety_gate(_block(rug_flags=["mint_not_renounced"])) == "caution"


def test_imev_elevated_caution():
    assert safety_gate(_block(imev_label="elevated")) == "caution"


def test_clean_is_ok():
    assert safety_gate(_block()) == "ok"


# --------------------------------------------------------------------------- #
# safety_gate — folding in the wash read                                       #
# --------------------------------------------------------------------------- #


def test_wash_manipulated_blocks_even_on_clean_static():
    wash = WashRiskBlock(score=0.75, label="manipulated", reasons=["x"], fired_signals=["f1"])
    assert safety_gate(_block(), wash=wash) == "block"


def test_wash_manipulated_blocks_even_when_static_unchecked():
    wash = WashRiskBlock(score=0.75, label="manipulated", reasons=["x"], fired_signals=["f1"])
    assert safety_gate(_block(checked=False), wash=wash) == "block"


def test_wash_elevated_raises_clean_to_caution():
    wash = WashRiskBlock(score=0.45, label="elevated", reasons=["x"], fired_signals=["f1"])
    assert safety_gate(_block(), wash=wash) == "caution"


def test_wash_elevated_when_static_unchecked_is_caution():
    # No static read but an elevated flow read → caution, not unknown.
    wash = WashRiskBlock(score=0.45, label="elevated", reasons=["x"], fired_signals=["f1"])
    assert safety_gate(_block(checked=False), wash=wash) == "caution"


def test_clean_wash_keeps_ok():
    wash = WashRiskBlock(score=0.0, label="clean", reasons=["benign"], fired_signals=[])
    assert safety_gate(_block(), wash=wash) == "ok"


# --------------------------------------------------------------------------- #
# PrecomputedSafety                                                            #
# --------------------------------------------------------------------------- #


def test_age_and_freshness():
    pc = PrecomputedSafety(mint="X", gate="ok", computed_at_epoch=1_000.0)
    assert pc.age_seconds(1_005.0) == 5.0
    assert pc.age_seconds(900.0) == 0.0  # clamped
    assert pc.is_fresh(1_005.0, max_age_s=10.0)
    assert not pc.is_fresh(1_020.0, max_age_s=10.0)


def test_to_response_shape():
    wash = WashRiskBlock(score=0.75, label="manipulated", reasons=["x"], fired_signals=["f1"])
    pc = PrecomputedSafety(
        mint="X",
        gate="block",
        safety={"checked": True, "honeypot": False},
        wash=wash,
        computed_at_epoch=1_000.0,
        source="monitor",
    )
    resp = pc.to_response(now_epoch=1_002.0)
    assert resp["gate"] == "block"
    assert resp["checked"] is True  # safety fields are merged at top level
    assert resp["wash_risk"]["label"] == "manipulated"
    assert resp["source"] == "monitor"
    assert resp["staleness_s"] == 2.0


def test_to_response_without_wash():
    pc = PrecomputedSafety(mint="X", gate="unknown", computed_at_epoch=1_000.0)
    resp = pc.to_response()
    assert resp["wash_risk"] is None
    assert "staleness_s" not in resp  # omitted when no now given


def test_hotpathcache_satisfies_store_protocol():
    from gecko_core.trade_agent.hotpath.cache import HotpathCache

    # HotpathCache.get/set match the SafetyStore shape (structural check).
    assert isinstance(HotpathCache(), SafetyStore)
