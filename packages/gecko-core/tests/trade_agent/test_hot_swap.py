"""Hot-swap mechanics — spec v1 → v2 with open position preserved."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from gecko_core.trade_agent.oracle import OracleWrapper, make_stub_caller
from gecko_core.trade_agent.runtime import AgentRuntime, RuntimeError_
from gecko_core.trade_agent.spec import load_spec
from gecko_core.trade_agent.state.models import AgentPosition
from gecko_core.trade_agent.state.mongo import InMemoryStateStore


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


async def test_hot_swap_preserves_open_position(valid_spec_dict, store):
    v1 = load_spec(valid_spec_dict)
    rt = _make_runtime(v1, store)
    await rt.start()
    try:
        # Seed an open position.
        await store.upsert_position(
            AgentPosition(
                agent_id="a1",
                position_id="p1",
                status="open",
                mint="So11",
                size_usd=100,
                entry_price=50.0,
                opened_at=datetime.now(UTC),
            )
        )

        # New spec v2 — bump version and tweak risk.
        v2_dict = dict(valid_spec_dict)
        v2_dict["version"] = "0.2.0"
        v2_dict["risk"] = {**valid_spec_dict["risk"], "max_concurrent_positions": 5}
        v2 = load_spec(v2_dict)

        await rt.hot_swap_to(v2)
        await rt._journal_q.join()

        state = await store.get_agent_state("a1")
        assert state is not None
        assert state.spec_version == "0.2.0"
        assert state.spec_fingerprint == v2.fingerprint()

        # Position survived (we don't touch agent_positions on swap).
        positions = await store.list_open_positions("a1")
        assert len(positions) == 1
        assert positions[0].position_id == "p1"

        # Journal records the swap.
        journal = await store.tail_journal("a1", limit=50)
        events = [e.event for e in journal]
        assert "spec_swap" in events
    finally:
        await rt.stop()


async def test_hot_swap_rejects_lower_version(valid_spec_dict, store):
    v1 = load_spec(valid_spec_dict)
    rt = _make_runtime(v1, store)
    await rt.start()
    try:
        v_lower_dict = dict(valid_spec_dict)
        v_lower_dict["version"] = "0.0.5"
        v_lower = load_spec(v_lower_dict)
        with pytest.raises(RuntimeError_, match="version >"):
            await rt.hot_swap_to(v_lower)
    finally:
        await rt.stop()


async def test_hot_swap_replaces_evaluator(valid_spec_dict, store):
    v1 = load_spec(valid_spec_dict)
    rt = _make_runtime(v1, store)
    await rt.start()
    try:
        v2_dict = dict(valid_spec_dict)
        v2_dict["version"] = "0.2.0"
        v2_dict["entry"] = {
            "primitive": "momentum_follow",
            "params": {"min_momentum": 0.9},
            "rule_id": "r-entry",
        }
        v2 = load_spec(v2_dict)
        await rt.hot_swap_to(v2)
        # New evaluator should respect the new threshold.
        await rt.tick({"mint": "So11", "momentum": 0.5})
        await rt._journal_q.join()
        journal = await store.tail_journal("a1", limit=50)
        assert "opportunity" not in [e.event for e in journal]
        await rt.tick({"mint": "So11", "momentum": 0.95})
        await rt._journal_q.join()
        journal = await store.tail_journal("a1", limit=50)
        assert "opportunity" in [e.event for e in journal]
    finally:
        await rt.stop()
