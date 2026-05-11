"""Trader mode — gated execution.

v0.1 stub. The runtime will instantiate this only when ``--mode trader``
is requested. The evaluator raises :class:`NotImplementedError` with a
pointer to the AIML-2 ticket so users get a useful error rather than a
silent no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gecko_core.trade_agent.primitives.entry import EntryCandidate
from gecko_core.trade_agent.spec import AgentSpec


@dataclass
class TraderMode:
    spec: AgentSpec

    def evaluate(self, event: dict[str, Any]) -> EntryCandidate | None:
        raise NotImplementedError(
            "Trader mode evaluator is not implemented yet (AIML-2 in "
            "docs/strategy/2026-05-11-trade-vertical-expansion.md §7). "
            "Run the agent with --mode advisor for v0.1."
        )


__all__ = ["TraderMode"]
