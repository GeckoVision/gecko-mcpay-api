"""Tests for I2 program reputation (bundle→originating-program attribution)."""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.program_reputation import (
    ESTABLISHED_PROGRAMS,
    classify_program,
    has_unknown_program,
)

RAYDIUM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
CUSTOM_SNIPER = "Sn1perPr0gram1111111111111111111111111111111"


def test_known_dex_is_established():
    assert classify_program(RAYDIUM) == "established"
    assert classify_program(PUMPFUN) == "established"


def test_unknown_program_is_unknown():
    assert classify_program(CUSTOM_SNIPER) == "unknown"
    assert classify_program("") == "unknown"


def test_has_unknown_program_detects_custom():
    # an ordinary route: pump.fun + token program -> all established
    assert has_unknown_program([PUMPFUN, "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"]) is False
    # a sniper route: a custom program in the mix -> flagged
    assert has_unknown_program([RAYDIUM, CUSTOM_SNIPER]) is True


def test_empty_set_has_no_unknown():
    assert has_unknown_program([]) is False


def test_registry_nonempty_and_frozen():
    assert len(ESTABLISHED_PROGRAMS) >= 8
    assert isinstance(ESTABLISHED_PROGRAMS, frozenset)
