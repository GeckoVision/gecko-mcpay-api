"""Tests for pool discovery (logsSubscribe → resolve → track_pool)."""

from __future__ import annotations

import pytest
from gecko_core.trade_agent.hotpath.pool_discovery_runner import PoolDiscovery
from gecko_core.trade_agent.hotpath.pool_resolver import WSOL_MINT

LAUNCH_MINT = "Lnch1111111111111111111111111111111111111111"
BASE_VAULT = "BaseVau1t11111111111111111111111111111111111"
QUOTE_VAULT = "QuoteVau1t1111111111111111111111111111111111"
POOL_AUTH = "Po01Auth11111111111111111111111111111111111"


def _init_params(sig):
    return {
        "result": {
            "value": {
                "signature": sig,
                "logs": ["Program log: Instruction: initialize2"],
                "err": None,
            }
        }
    }


def _parsed_tx():
    keys = [POOL_AUTH, BASE_VAULT, QUOTE_VAULT]
    return {
        "blockTime": 1000,
        "transaction": {"message": {"accountKeys": [{"pubkey": k} for k in keys]}},
        "meta": {
            "postTokenBalances": [
                {
                    "accountIndex": 1,
                    "mint": LAUNCH_MINT,
                    "owner": POOL_AUTH,
                    "uiTokenAmount": {"uiAmount": 1_000_000.0},
                },
                {
                    "accountIndex": 2,
                    "mint": WSOL_MINT,
                    "owner": POOL_AUTH,
                    "uiTokenAmount": {"uiAmount": 80.0},
                },
            ]
        },
    }


class _FakeWS:
    def __init__(self):
        self.callbacks = []

    async def subscribe_logs(self, mentions, callback):
        self.callbacks.append(callback)
        return len(self.callbacks)


class _FakeRunner:
    def __init__(self):
        self.calls = []

    async def track_pool(self, **kw):
        self.calls.append(kw)


async def _fetch_ok(_sig):
    return _parsed_tx()


@pytest.mark.asyncio
async def test_init_log_resolves_and_tracks():
    ws, runner = _FakeWS(), _FakeRunner()
    d = PoolDiscovery(runner, ws, _fetch_ok, program_ids=("PROG",))
    await d.start()
    await ws.callbacks[0](_init_params("sig1"))
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["mint"] == LAUNCH_MINT
    assert call["base_vault"] == BASE_VAULT and call["quote_vault"] == QUOTE_VAULT
    assert d.stats["tracked"] == 1


@pytest.mark.asyncio
async def test_duplicate_signature_tracked_once():
    ws, runner = _FakeWS(), _FakeRunner()
    d = PoolDiscovery(runner, ws, _fetch_ok, program_ids=("PROG",))
    await d.start()
    await ws.callbacks[0](_init_params("sig1"))
    await ws.callbacks[0](_init_params("sig1"))
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_non_init_log_ignored():
    ws, runner = _FakeWS(), _FakeRunner()
    d = PoolDiscovery(runner, ws, _fetch_ok, program_ids=("PROG",))
    await d.start()
    params = {"result": {"value": {"signature": "s", "logs": ["Instruction: Swap"]}}}
    await ws.callbacks[0](params)
    assert runner.calls == [] and d.stats["inits_seen"] == 0


@pytest.mark.asyncio
async def test_cap_blocks_new_pools():
    ws, runner = _FakeWS(), _FakeRunner()
    d = PoolDiscovery(runner, ws, _fetch_ok, program_ids=("PROG",), max_pools=1)
    await d.start()
    await ws.callbacks[0](_init_params("sig1"))
    await ws.callbacks[0](_init_params("sig2"))
    assert len(runner.calls) == 1
    assert d.stats["skipped_cap"] == 1


@pytest.mark.asyncio
async def test_fetch_failure_fails_open():
    ws, runner = _FakeWS(), _FakeRunner()

    async def _fetch_none(_sig):
        return None

    d = PoolDiscovery(runner, ws, _fetch_none, program_ids=("PROG",))
    await d.start()
    await ws.callbacks[0](_init_params("sig1"))
    assert runner.calls == [] and d.stats["failed"] == 1
