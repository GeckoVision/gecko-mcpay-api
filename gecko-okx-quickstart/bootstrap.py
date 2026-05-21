"""Wire the three local voices + coordinator into a LocalPanel.

Keeps the bot file minimal: the bot imports ``build_local_panel`` from
here, hands it the shared :class:`LocalMemory`, and gets back a fully
wired :class:`LocalPanel`. If ``OPENROUTER_API_KEY`` is unset, the
:class:`OpenRouterClient` constructor raises and the bot's broad-except
falls back to "no local panel — bot still runs against price_breakout
alone."

See ``docs/strategy/lab-validated/2026-05-20-local-panel-voices-spec.md``
§6.3 — voices live under ``contest_bot/voices/`` and never import from
``gecko_core/``.
"""

from __future__ import annotations

from llm_client import OpenRouterClient
from local_memory import LocalMemory
from local_panel import LocalPanel
from voices.base import LocalVoice
from voices.chart_analyst import ChartAnalystVoice
from voices.coordinator_rules import coordinator
from voices.memory_voice import MemoryVoice
from voices.regime_analyst import RegimeAnalystVoice
from voices.risk_voice import RiskVoice


def build_local_panel(memory: LocalMemory) -> LocalPanel:
    """Construct + wire the three v0.1 voices into a LocalPanel.

    Raises :class:`llm_client.OpenRouterConfigError` if
    ``OPENROUTER_API_KEY`` is unset — caller (the bot's broad-except
    block) catches and degrades.
    """
    # One shared client across all three voices — each voice's HTTP
    # call uses the same connection pool. The OpenRouterClient is
    # cheap to construct but the httpx.Client inside is not, so we
    # only build one.
    client = OpenRouterClient()
    # Annotated explicitly because each voice class is its own type;
    # the literal-list narrows to the most specific common type
    # without an explicit annotation, which mypy --strict rejects.
    voices: list[LocalVoice] = [
        ChartAnalystVoice(client=client),
        MemoryVoice(client=client),
        RiskVoice(client=client),
        # B3 (S40): deterministic chop/trend classifier — votes + logs now;
        # the coordinator wires it into the rule chain as a gate-modulator in B6.
        RegimeAnalystVoice(client=client),
    ]
    return LocalPanel(voices=voices, memory=memory, coordinator=coordinator)


__all__ = ["build_local_panel"]
