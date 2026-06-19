"""Tests for the live-ingest runner (step 6) — gating + end-to-end reachability.

Drives the runner with a fake websocket client and recorded vault notifications
(no network), proving a draining buy-loop on the live path reaches the scorer and
flips the cache. Pattern E for the live wire.
"""

from __future__ import annotations

import pytest
from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from gecko_core.trade_agent.hotpath.launch_runner import (
    LaunchRunner,
    build_runner,
    is_firewall_enabled,
)


class _FakeWS:
    """Records subscribe_account calls; hands back the callbacks so the test can
    drive notifications directly."""

    def __init__(self) -> None:
        self.callbacks: dict[str, object] = {}
        self._n = 0

    async def subscribe_account(self, pubkey, callback):
        self._n += 1
        self.callbacks[pubkey] = callback
        return self._n


def _acct(mint: str, ui: float, slot: int = 1) -> dict:
    return {
        "subscription": 1,
        "result": {
            "context": {"slot": slot},
            "value": {
                "data": {
                    "parsed": {
                        "info": {
                            "mint": mint,
                            "tokenAmount": {
                                "amount": str(int(ui * 1e6)),
                                "decimals": 6,
                                "uiAmount": ui,
                            },
                        },
                        "type": "account",
                    },
                    "program": "spl-token",
                },
            },
        },
    }


# --------------------------------------------------------------------------- #
# Gating                                                                       #
# --------------------------------------------------------------------------- #


def test_gating_default_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GECKO_FIREWALL_ENABLED", raising=False)
    assert is_firewall_enabled() is False


def test_gating_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GECKO_FIREWALL_ENABLED", "true")
    assert is_firewall_enabled() is True


def test_build_runner_none_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GECKO_FIREWALL_ENABLED", raising=False)
    assert build_runner(LaunchMonitor(HotpathCache())) is None


def test_build_runner_none_when_enabled_but_no_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GECKO_FIREWALL_ENABLED", "1")
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    assert build_runner(LaunchMonitor(HotpathCache())) is None


# --------------------------------------------------------------------------- #
# End-to-end: live notifications → scorer → cache                             #
# --------------------------------------------------------------------------- #


async def test_draining_buy_loop_reaches_cache():
    store = HotpathCache()
    mon = LaunchMonitor(store)
    ws = _FakeWS()
    clock = {"t": 100_000.0}
    runner = LaunchRunner(mon, ws, now=lambda: clock["t"])

    created = int(clock["t"] - 120)
    await runner.track_pool(
        mint="VICTIM",
        pool_addr="PoolXYZ",
        base_vault="baseV",
        quote_vault="quoteV",
        quote_usd_per_unit=1.0,
        pool_created_ts=created,
    )
    assert runner.tracked_pools == 1
    assert set(ws.callbacks) == {"baseV", "quoteV"}

    base_cb = ws.callbacks["baseV"]
    quote_cb = ws.callbacks["quoteV"]

    # Seed reserves: 1000 base, 1000 quote (price ~1.0).
    await quote_cb(_acct("USDC", 1000.0))
    await base_cb(_acct("BASE", 1000.0))

    # A tight, one-sided buy loop: base drained in small uniform steps, quote
    # rising → price climbs. (Uniform sizes = the F1 size-uniformity guard.)
    base = 1000.0
    quote = 1000.0
    for _i in range(40):
        clock["t"] += 1
        base -= 2.0
        quote += 2.0 * (quote / base)  # constant-product-ish quote in
        await quote_cb(_acct("USDC", quote))
        await base_cb(_acct("BASE", base))

    await runner.recompute_all()
    pc = await store.get("VICTIM")
    assert pc is not None
    assert pc.wash is not None
    # The live path powers F1 (flow shape). It must at least flag elevated.
    assert pc.wash.label in {"elevated", "manipulated"}
    assert "thin_pool_buy_loop" in pc.wash.fired_signals
