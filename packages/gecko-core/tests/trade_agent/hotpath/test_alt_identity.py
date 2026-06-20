"""Tests for ALT-as-operator-identity (the shared-execution-rig signal)."""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.alt_identity import shared_alt_buyers

ALT_A = "ALT_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
ALT_B = "ALT_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
JUP = "JUP_publicrouter_alt_111111111111111111111111"


def test_no_sharing_is_zero():
    # each buyer on its own ALT — no shared rig
    assert shared_alt_buyers({"W1": {ALT_A}, "W2": {ALT_B}}) == 0


def test_two_buyers_sharing_alt_cluster():
    assert shared_alt_buyers({"W1": {ALT_A}, "W2": {ALT_A}}) == 2


def test_three_way_cluster():
    n = shared_alt_buyers({"W1": {ALT_A}, "W2": {ALT_A}, "W3": {ALT_A}, "W4": {ALT_B}})
    assert n == 3  # W1/W2/W3 share ALT_A; W4 alone


def test_public_alt_is_excluded():
    # a shared PUBLIC/aggregator ALT (Jupiter) is not a coordination signal
    assert shared_alt_buyers({"W1": {JUP}, "W2": {JUP}}, public_alts=frozenset({JUP})) == 0
    # but a custom ALT shared alongside it still clusters
    assert (
        shared_alt_buyers({"W1": {JUP, ALT_A}, "W2": {JUP, ALT_A}}, public_alts=frozenset({JUP}))
        == 2
    )


def test_empty_is_zero():
    assert shared_alt_buyers({}) == 0
    assert shared_alt_buyers({"W1": set()}) == 0
