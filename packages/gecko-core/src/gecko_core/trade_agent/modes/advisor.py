"""Advisor mode — surface opportunities, never sign.

Per founder decision (memory ``project_trade_vertical_v01_decisions_2026_05_11``):
advisor is the v0.1 default. The mode evaluates an event against the
spec's entry primitive; on a hit, the runtime writes an ``opportunity``
journal entry and does NOT invoke the execution adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gecko_core.trade_agent.primitives.entry import EntryCandidate, evaluate_entry
from gecko_core.trade_agent.spec import AgentSpec


@dataclass
class AdvisorMode:
    spec: AgentSpec

    def evaluate(self, event: dict[str, Any]) -> EntryCandidate | None:
        """Return a candidate the user *could* act on, or ``None``.

        Pure / sync — no Mongo, no MCP, no exec adapter. The runtime is
        responsible for journaling the opportunity.
        """
        return evaluate_entry(self.spec.entry, event)


__all__ = ["AdvisorMode"]
