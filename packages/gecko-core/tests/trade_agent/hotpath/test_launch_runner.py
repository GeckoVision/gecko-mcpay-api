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


def test_build_runner_constructs_when_enabled_and_keyed(monkeypatch: pytest.MonkeyPatch):
    # The path the gecko-api lifespan uses: enabled + a key -> a real runner
    # (constructs the ws client; no network until start()).
    monkeypatch.setenv("GECKO_FIREWALL_ENABLED", "true")
    monkeypatch.setenv("HELIUS_API_KEY", "test-key-not-real")
    runner = build_runner(LaunchMonitor(HotpathCache()))
    assert isinstance(runner, LaunchRunner)
    assert runner.tracked_pools == 0


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


# --------------------------------------------------------------------------- #
# Free-path snipe ingest (logsSubscribe + getTransaction)                      #
# --------------------------------------------------------------------------- #

from gecko_core.trade_agent.hotpath.jito import JITO_TIP_ACCOUNTS  # noqa: E402
from gecko_core.trade_agent.hotpath.snipe_features import LAMPORTS_PER_SOL  # noqa: E402

_RAYDIUM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
_SYSTEM = "11111111111111111111111111111111"
_TIP = next(iter(JITO_TIP_ACCOUNTS))


class _FakeLogsWS:
    """Fake ws exposing subscribe_account + subscribe_logs; captures callbacks."""

    def __init__(self) -> None:
        self.acct_cbs: dict[str, object] = {}
        self.logs_cbs: list[object] = []
        self._n = 0

    async def subscribe_account(self, pubkey, callback):
        self._n += 1
        self.acct_cbs[pubkey] = callback
        return self._n

    async def subscribe_logs(self, mentions, callback):
        self._n += 1
        self.logs_cbs.append(callback)
        return self._n


def _logs_notif(sig: str) -> dict:
    return {"result": {"value": {"signature": sig, "logs": ["Program log: ray_log"], "err": None}}}


def _buy_tx(signer: str) -> dict:
    return {
        "blockTime": 1000,
        "transaction": {
            "message": {
                "accountKeys": [{"pubkey": signer, "signer": True, "writable": True}],
                "instructions": [
                    {"programId": _RAYDIUM},
                    {
                        "programId": _SYSTEM,
                        "parsed": {
                            "type": "transfer",
                            "info": {"destination": _TIP, "lamports": int(2e-4 * LAMPORTS_PER_SOL)},
                        },
                    },
                ],
            }
        },
        "meta": {
            "err": None,
            "preBalances": [int(5 * LAMPORTS_PER_SOL)],
            "postBalances": [int(4 * LAMPORTS_PER_SOL)],
            "innerInstructions": [],
        },
    }


@pytest.mark.asyncio
async def test_free_logs_path_feeds_snipe_gate():
    store = HotpathCache()
    mon = LaunchMonitor(store)
    ws = _FakeLogsWS()
    fetched: list[str] = []

    async def fake_fetch(sig: str):
        fetched.append(sig)
        return _buy_tx(f"W{len(fetched)}")  # a distinct fresh-ish buyer per sig

    runner = LaunchRunner(mon, ws, tx_fetcher=fake_fetch, tx_mode="logs", now=lambda: 1030.0)
    await runner.track_pool(
        mint="MINT", pool_addr="P", base_vault="BV", quote_vault="QV", pool_created_ts=1000
    )
    assert ws.logs_cbs, "a logsSubscribe should have been registered for the free path"

    # drive 4 swap-log notifications (4 distinct sigs) through the captured callback
    cb = ws.logs_cbs[0]
    for i in range(4):
        await cb(_logs_notif(f"sig{i}"))

    assert fetched == ["sig0", "sig1", "sig2", "sig3"]  # each unique sig fetched once
    # de-dup: a repeat sig is not fetched again
    await cb(_logs_notif("sig0"))
    assert len(fetched) == 4

    # the parsed swaps reached the monitor → a snipe verdict is produced
    pc = await mon.recompute("MINT", 1030.0)
    assert pc is not None and pc.snipe is not None
    assert "jito_bundle_snipe" in pc.snipe.fired_signals


@pytest.mark.asyncio
async def test_logs_path_respects_fetch_cap():
    from gecko_core.trade_agent.hotpath import launch_runner as lr

    store = HotpathCache()
    mon = LaunchMonitor(store)
    ws = _FakeLogsWS()
    calls = {"n": 0}

    async def fake_fetch(sig: str):
        calls["n"] += 1
        return None  # parse result irrelevant; we're counting fetches

    runner = LaunchRunner(mon, ws, tx_fetcher=fake_fetch, tx_mode="logs")
    await runner.track_pool(mint="M", pool_addr="P", base_vault="BV", quote_vault="QV")
    cb = ws.logs_cbs[0]
    for i in range(lr.MAX_PARSED_FETCH_PER_POOL + 25):
        await cb(_logs_notif(f"s{i}"))
    assert calls["n"] == lr.MAX_PARSED_FETCH_PER_POOL  # capped (credit guard)
