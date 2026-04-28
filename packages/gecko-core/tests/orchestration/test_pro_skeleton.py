"""Skeleton tests — public surface imports, NotImplementedError, lazy AG2 import."""

from __future__ import annotations

import builtins
import sys

import pytest


def test_public_surface_imports() -> None:
    from gecko_core.orchestration.pro import (  # noqa: F401
        AgentEvent,
        AgentTurn,
        BudgetExceeded,
        BudgetGuard,
        DebateTranscript,
        generate,
        transcript_from_events,
    )


async def test_generate_requires_llm_config() -> None:
    """A4 wired the AG2 path. Without llm_config we raise ValueError fast
    rather than letting AG2 surface a less-clean error downstream.
    """
    from gecko_core.orchestration.pro import generate

    with pytest.raises(ValueError, match="llm_config is required"):
        await generate(idea="x", rag_context="y")


async def test_generate_with_stubbed_groupchat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full happy-path with `build_groupchat` stubbed to return a fake manager.

    The fake yields one canned reply per agent. We assert the event ordering
    (turn_start/turn_end pairs in agent order, plus a final), and that the
    transcript contains 5 turns with content matching the canned replies.
    """
    from gecko_core.orchestration import pro as pro_mod
    from gecko_core.orchestration.pro import AgentEvent, generate

    canned: dict[str, str] = {
        "analyst": "TAM looks plausible.",
        "critic": "But the wedge is fuzzy.",
        "architect": "Next.js + Supabase + Solana Pay.",
        "scoper": "V1: 4 days. V2: 1 week.",
        "judge": "7/10 — ship to creator segment.",
    }

    class _FakeAgent:
        def __init__(self, name: str) -> None:
            self.name = name

        async def a_generate_reply(self, messages: object = None) -> str:
            return canned[self.name]

    class _FakeChat:
        def __init__(self) -> None:
            self.agents = [_FakeAgent(n) for n in canned]
            self.messages: list[dict[str, object]] = []

    class _FakeManager:
        def __init__(self) -> None:
            self.groupchat = _FakeChat()

    def _fake_build(_cfg: dict[str, object]) -> _FakeManager:
        return _FakeManager()

    monkeypatch.setattr(pro_mod, "build_groupchat", _fake_build)

    events: list[AgentEvent] = []

    async def _on_event(ev: AgentEvent) -> None:
        events.append(ev)

    transcript = await generate(
        idea="a habit tracker",
        rag_context="example context",
        llm_config={"config_list": [{"model": "x", "api_key": "y", "base_url": "z"}]},
        on_event=_on_event,
    )

    # Five turns, in agent order, with canned content.
    assert [t.agent for t in transcript.turns] == [
        "analyst",
        "critic",
        "architect",
        "scoper",
        "judge",
    ]
    assert [t.content for t in transcript.turns] == list(canned.values())
    assert transcript.budget_halt_reason is None

    # Event stream: 5 * (turn_start, turn_end) + 1 final = 11.
    types = [e.type for e in events]
    assert types.count("turn_start") == 5
    assert types.count("turn_end") == 5
    assert types[-1] == "final"
    # Final carries the judge's verdict.
    assert events[-1].content == canned["judge"]


def test_build_groupchat_lazy_import_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify AG2 is imported lazily — module loads even when `autogen` is gone."""
    from gecko_core.orchestration.pro import agents as agents_mod

    # The module itself must already be loaded without touching `autogen`.
    assert hasattr(agents_mod, "build_groupchat")

    # Simulate AG2 not being installed: block the autogen import inside
    # build_groupchat. We do this by stubbing __import__ rather than
    # mutating sys.modules with None, which can interact poorly with
    # already-cached submodules.
    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "autogen" or name.startswith("autogen."):
            raise ImportError("autogen not installed (simulated)")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    # Drop any cached autogen modules so the next import goes through __import__.
    for mod in [m for m in sys.modules if m == "autogen" or m.startswith("autogen.")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(ImportError):
        agents_mod.build_groupchat({"model": "gpt-4o-mini"})
