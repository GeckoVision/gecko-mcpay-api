"""AG2 ConversableAgent builders for the 7-agent trade-panel GroupChat.

Mirrors ``orchestration/pro/agents.py``. AG2 (`autogen`) is imported lazily
inside ``build_groupchat`` so this module stays importable in environments
without AG2 (CLI doc builds, minimal containers).

v1 deliberately ships round-robin speaker selection (``"round_robin"``)
rather than ``"auto"``. Reasons:
  - 7 voices in canonical order is a deterministic spec.
  - No selector LLM call per round — saves cost + latency.
  - The panel's value comes from each persona contributing once; auto
    selection risks the same voice replying twice and starving another.
The driver in ``__init__.run_trade_panel`` still walks REQUIRED_AGENTS in
order; the GroupChat speaker_selection_method is a redundant safety net.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gecko_core.orchestration.trade_panel.personas import REQUIRED_AGENTS
from gecko_core.orchestration.trade_panel.prompts import load_prompts

if TYPE_CHECKING:  # pragma: no cover - typing-only
    from autogen import GroupChatManager


def _agent_specs() -> tuple[tuple[str, str], ...]:
    """Resolve (agent_name, system_message) pairs in canonical order."""
    prompts = load_prompts()
    return tuple((name, prompts[name]) for name in REQUIRED_AGENTS)


def build_groupchat(llm_config: dict[str, Any]) -> GroupChatManager:
    """Construct the 7-agent GroupChat for the trade panel.

    Args:
        llm_config: Base AG2 llm_config (router base_url + api_key + headers).

    AG2 is imported lazily so this module stays importable without AG2.
    """
    from autogen import ConversableAgent, GroupChat, GroupChatManager

    agents: list[Any] = []
    for name, sys_msg in _agent_specs():
        agents.append(
            ConversableAgent(
                name=name,
                system_message=sys_msg,
                llm_config=llm_config,
                human_input_mode="NEVER",
            )
        )

    chat = GroupChat(
        agents=agents,
        messages=[],
        # 7 voices, one turn each — leave headroom for the seed message.
        max_round=14,
        speaker_selection_method="round_robin",
    )
    return GroupChatManager(groupchat=chat, llm_config=llm_config)


__all__ = ["build_groupchat"]
