"""Oracle cache-then-charge contract tests."""

from __future__ import annotations

import pytest
from gecko_core.trade_agent.oracle import (
    OracleWrapper,
    RateLimitedError,
    idea_hash,
    make_stub_caller,
)
from gecko_core.trade_agent.state.mongo import InMemoryStateStore


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


@pytest.mark.asyncio
async def test_cache_miss_calls_through(store: InMemoryStateStore):
    calls: list[str] = []

    async def fake_caller(*, idea, tier, agent_id):
        calls.append(str(idea))
        return {"verdict": "act", "confidence": 0.8}

    oracle = OracleWrapper(agent_id="a1", state_store=store, caller=fake_caller)
    v = await oracle.get_verdict(idea="kamino:lend SOL", tier="basic")
    assert v["verdict"] == "act"
    assert calls == ["kamino:lend SOL"]


@pytest.mark.asyncio
async def test_cache_hit_avoids_caller(store: InMemoryStateStore):
    calls: list[str] = []

    async def fake_caller(*, idea, tier, agent_id):
        calls.append(str(idea))
        return {"verdict": "act"}

    oracle = OracleWrapper(agent_id="a1", state_store=store, caller=fake_caller)
    await oracle.get_verdict(idea="kamino:lend SOL")
    await oracle.get_verdict(idea="kamino:lend SOL")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_idea_hash_normalisation_collapses_whitespace_and_case():
    a = idea_hash("Kamino: Lend SOL")
    b = idea_hash("  kamino:   lend sol  ")
    assert a == b


@pytest.mark.asyncio
async def test_manual_rate_limit_enforced(store: InMemoryStateStore):
    oracle = OracleWrapper(
        agent_id="a1",
        state_store=store,
        caller=make_stub_caller({"verdict": "act"}),
    )
    # First manual call charges (cache miss).
    await oracle.get_verdict(idea="x", trigger="manual", force_refresh=True)
    # Second manual call within ceiling must raise.
    with pytest.raises(RateLimitedError):
        await oracle.get_verdict(idea="y", trigger="manual", force_refresh=True)


@pytest.mark.asyncio
async def test_entry_gate_no_rate_limit(store: InMemoryStateStore):
    # Entry-gate ceiling is None — back-to-back forced refreshes allowed.
    oracle = OracleWrapper(
        agent_id="a1",
        state_store=store,
        caller=make_stub_caller({"verdict": "act"}),
    )
    await oracle.get_verdict(idea="x", trigger="entry_gate", force_refresh=True)
    await oracle.get_verdict(idea="y", trigger="entry_gate", force_refresh=True)


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache(store: InMemoryStateStore):
    calls = 0

    async def fake_caller(*, idea, tier, agent_id):
        nonlocal calls
        calls += 1
        return {"verdict": "act"}

    oracle = OracleWrapper(agent_id="a1", state_store=store, caller=fake_caller)
    await oracle.get_verdict(idea="x", trigger="entry_gate")
    await oracle.get_verdict(idea="x", trigger="entry_gate", force_refresh=True)
    assert calls == 2
