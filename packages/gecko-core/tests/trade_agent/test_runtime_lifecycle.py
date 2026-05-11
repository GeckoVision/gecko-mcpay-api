"""Runtime lifecycle + heartbeat + journal contract tests.

Uses :class:`InMemoryStateStore` and a stub oracle. No hotpath imports —
the runtime accepts events via the public ``tick`` method, which is the
seam we test through.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from gecko_core.trade_agent.oracle import OracleWrapper, make_stub_caller
from gecko_core.trade_agent.runtime import AgentRuntime
from gecko_core.trade_agent.spec import AgentSpec, load_spec
from gecko_core.trade_agent.state.mongo import InMemoryStateStore


@pytest.fixture
def spec(valid_spec_dict) -> AgentSpec:
    return load_spec(valid_spec_dict)


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


def _make_runtime(spec, store) -> AgentRuntime:
    oracle = OracleWrapper(agent_id="a1", state_store=store, caller=make_stub_caller())
    return AgentRuntime(
        agent_id="a1",
        spec=spec,
        mode="advisor",
        state_store=store,
        oracle=oracle,
    )


async def test_start_persists_agent_state(spec, store):
    rt = _make_runtime(spec, store)
    try:
        await rt.start()
        state = await store.get_agent_state("a1")
        assert state is not None
        assert state.status == "running"
        assert state.mode == "advisor"
        assert state.spec_version == "0.1.0"
    finally:
        await rt.stop()


async def test_advisor_tick_writes_opportunity(spec, store):
    rt = _make_runtime(spec, store)
    try:
        await rt.start()
        await rt.tick(
            {
                "mint": "So111...",
                "drawdown_pct": 10,  # >= threshold of 5
            }
        )
        # Drain journal queue.
        await rt._journal_q.join()
        entries = await store.tail_journal("a1", limit=50)
        events = [e.event for e in entries]
        assert "opportunity" in events
    finally:
        await rt.stop()


async def test_advisor_tick_no_match_writes_nothing(spec, store):
    rt = _make_runtime(spec, store)
    try:
        await rt.start()
        await rt.tick({"mint": "So111...", "drawdown_pct": 1})  # below
        await rt._journal_q.join()
        entries = await store.tail_journal("a1", limit=50)
        events = [e.event for e in entries]
        assert "opportunity" not in events
    finally:
        await rt.stop()


async def test_stop_marks_stopped(spec, store):
    rt = _make_runtime(spec, store)
    await rt.start()
    await rt.stop()
    state = await store.get_agent_state("a1")
    assert state is not None
    assert state.status == "stopped"


async def test_heartbeat_updates(spec, store, monkeypatch):
    # Run a short heartbeat by patching the interval down.
    monkeypatch.setattr("gecko_core.trade_agent.runtime.HEARTBEAT_INTERVAL_S", 0.05)
    rt = _make_runtime(spec, store)
    try:
        await rt.start()
        # Capture heartbeat at startup, then again later.
        first = (await store.get_agent_state("a1")).last_heartbeat_at
        await asyncio.sleep(0.2)
        second = (await store.get_agent_state("a1")).last_heartbeat_at
        assert second >= first
    finally:
        await rt.stop()


async def test_resume_on_stale_heartbeat(spec, store):
    # Seed an existing "running" agent_state with a stale heartbeat,
    # simulating a crashed prior runtime — exactly the scenario the
    # resume path is meant to detect.
    rt = _make_runtime(spec, store)
    await rt.start()
    state = await store.get_agent_state("a1")
    assert state is not None
    state.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=300)
    state.status = "running"  # force — bypass the orderly stop
    await store.upsert_agent_state(state)
    # NB: deliberately do NOT call rt.stop() — simulate a crash by
    # cancelling background tasks and abandoning the runtime.
    if rt._journal_task is not None:
        rt._journal_task.cancel()
    if rt._heartbeat_task is not None:
        rt._heartbeat_task.cancel()
    await rt._scheduler.stop()

    rt2 = _make_runtime(spec, store)
    try:
        await rt2.start()
        await rt2._journal_q.join()
        entries = await store.tail_journal("a1", limit=50)
        events = [e.event for e in entries]
        assert "heartbeat_stale" in events
    finally:
        await rt2.stop()
