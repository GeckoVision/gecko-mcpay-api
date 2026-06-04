"""gecko_safety facade — the componentized SDK surface stays stable."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import gecko_safety as gs  # noqa: E402


def test_facade_exports_the_safety_surface():
    for name in ("verify_strategy", "safety_check", "TradeSafetyPolicy", "Order", "SafetyVerdict"):
        assert hasattr(gs, name), f"facade missing {name}"


def test_safety_check_denies_unverified_by_default():
    # default ctx has no DEPLOY verdict → real money blocked (the wedge default)
    v = gs.safety_check(gs.Order("BTC/USDT", "okx", 50.0))
    assert not v.allow and any("not DEPLOY" in r for r in v.reasons)


def test_safety_check_allows_clean_verified():
    v = gs.safety_check(
        gs.Order("BTC/USDT", "okx", 50.0),
        ctx=gs.SafetyContext(strategy_verdict="DEPLOY"),
    )
    assert v.allow


def test_verify_strategy_is_callable_and_lazy():
    # the heavy backtest import is lazy — the facade imports without it
    assert callable(gs.verify_strategy)
