"""Tests for the attack catalog — registry integrity + signal→pattern lookup."""

from __future__ import annotations

from gecko_core.trade_agent.attack_catalog import (
    CATALOG,
    get_pattern,
    patterns_by_coverage,
    patterns_for_signals,
)

_VALID_COVERAGE = {"live", "partial", "planned", "out_of_scope"}
_VALID_LATENCY = {"realtime", "batch", "static", "external"}


def test_catalog_ids_unique_and_nonempty():
    ids = [p.id for p in CATALOG]
    assert len(ids) == len(set(ids))  # unique
    assert all(p.id and p.name and p.description for p in CATALOG)


def test_enums_in_range():
    for p in CATALOG:
        assert p.coverage in _VALID_COVERAGE
        assert p.latency_tier in _VALID_LATENCY


def test_live_patterns_have_signals():
    # If we claim a pattern is detected live/partial, it must name ≥1 signal code.
    for p in CATALOG:
        if p.coverage in ("live", "partial"):
            assert p.signals, f"{p.id} claims coverage={p.coverage} but lists no signals"


def test_planned_patterns_are_honest():
    # 'planned'/'out_of_scope' patterns must NOT claim live signal detection.
    for p in CATALOG:
        if p.coverage in ("planned", "out_of_scope"):
            assert not p.signals, f"{p.id} is {p.coverage} but claims signals {p.signals}"


def test_get_pattern():
    assert get_pattern("thin_pool_buy_loop") is not None
    assert get_pattern("nope") is None


def test_patterns_for_signals_maps_firewall_codes():
    # The exact codes wash_signals emits → their named attacks.
    hits = {p.id for p in patterns_for_signals(["thin_pool_buy_loop", "multi_pool_price_bait"])}
    assert {
        "thin_pool_buy_loop",
        "multi_pool_price_bait",
    } <= hits  # oracle_manip also shares the loop code


def test_patterns_for_signals_fake_mcap_alias():
    # fake_market_cap pattern lists both rug_flag codes.
    hits = {p.id for p in patterns_for_signals(["thin_liquidity_vs_mcap"])}
    assert "fake_market_cap" in hits


def test_patterns_for_signals_empty():
    assert patterns_for_signals([]) == []
    assert patterns_for_signals(["unknown_code"]) == []


def test_coverage_roadmap_nonempty():
    # The 'planned' set is our build roadmap — wash/sybil/snipe should be there.
    planned = {p.id for p in patterns_by_coverage("planned")}
    assert (
        "rug_pull_lp_remove" in planned
    )  # no detector yet (snipe_gate consumes lp_drained as input)
    partial = {p.id for p in patterns_by_coverage("partial")}
    assert {
        "same_slot_co_buy",
        "jito_bundle_snipe",
        "fresh_wallet_swarm",
    } <= partial  # snipe_gate fires


def test_sandwich_has_jito_dontfront_mitigation():
    p = get_pattern("sandwich_mev")
    assert p is not None
    assert any("jitodontfront" in m for m in p.mitigations_agent)


def test_concentrated_capture_pattern_registered():
    p = get_pattern("concentrated_capture")
    assert p is not None
    assert p.category == "market_data"
    assert p.coverage == "partial"
    assert p.signals == ["concentrated_capture"]
    # the honest framing: the residual that survives every automation tell off
    assert p.on_chain_signature  # non-empty footprint description
    assert p.mitigations_agent  # the agent has a documented response


def test_concentrated_capture_signal_maps_to_pattern():
    hits = {p.id for p in patterns_for_signals(["concentrated_capture"])}
    assert "concentrated_capture" in hits
