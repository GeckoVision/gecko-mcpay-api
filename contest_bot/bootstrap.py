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
import os

from voices.chart_analyst import ChartAnalystVoice
from voices.coordinator_rules import coordinator
from voices.memory_voice import (
    MemoryVoice,  # noqa: F401 — kept for v1 callers; v2 replaces in panel
)
from voices.market_researcher import MarketResearcherVoice
from voices.memory_voice_v2 import MemoryVoiceV2
from voices.oracle_voice import OracleVoice
from voices.regime_analyst import RegimeAnalystVoice
from voices.risk_voice import RiskVoice
from voices.strategist_voice import StrategistVoice


def _market_researcher_enabled() -> bool:
    """Sprint 28: voice is env-gated default OFF. Skips construction
    entirely when off — no LLM cost, no Mongo poll, no panel impact.
    """
    return os.environ.get("GECKO_MARKET_RESEARCHER_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _oracle_voice_enabled() -> bool:
    """Sprint 29: 7th voice is env-gated default OFF. Skips construction
    entirely when off — no Mongo poll, no panel cardinality change.
    """
    return os.environ.get("GECKO_ORACLE_VOICE_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def build_local_panel(memory: LocalMemory) -> LocalPanel:
    """Construct + wire the local-panel voices into a LocalPanel.

    Raises :class:`llm_client.OpenRouterConfigError` if
    ``OPENROUTER_API_KEY`` is unset — caller (the bot's broad-except
    block) catches and degrades.
    """
    # One shared client across all LLM-backed voices — each voice's HTTP
    # call uses the same connection pool. The OpenRouterClient is
    # cheap to construct but the httpx.Client inside is not, so we
    # only build one.
    client = OpenRouterClient()
    # Annotated explicitly because each voice class is its own type;
    # the literal-list narrows to the most specific common type
    # without an explicit annotation, which mypy --strict rejects.
    voices: list[LocalVoice] = [
        ChartAnalystVoice(client=client),
        # Sprint 6 Phase C 2026-05-27: replaced LLM-based MemoryVoice (v1) with
        # pure-Python feature-rule MemoryVoiceV2. v2 reads Phase B by-symbol
        # cohorts + indicator exhaustion + realized outcomes. Zero LLM cost,
        # ~10ms latency vs v1's ~1500ms. Same wire-name 'memory_voice' so
        # dashboard plumbing unchanged.
        MemoryVoiceV2(),
        RiskVoice(client=client),
        # B3 (S40): deterministic chop/trend classifier — votes + logs now;
        # the coordinator wires it into the rule chain as a gate-modulator in B6.
        RegimeAnalystVoice(client=client),
        # Sprint 20 #1 (2026-05-28): devil's advocate — pre-execution adversarial
        # voice that challenges the chart_analyst's bullish thesis. Closes the
        # architectural hole the founder flagged (executor was effectively
        # rubber-stamping chart_analyst's signals). Observable-first: the voice
        # surfaces its opinion in artifact log + dashboard + Sprint 20 Dissent:
        # line; gating via coordinator_rules.py is a follow-up ticket (coord
        # file has parallel WIP that lands first).
        StrategistVoice(client=client),
    ]
    # Sprint 28 (2026-06-01): market_researcher voice — env-gated,
    # default OFF. Reads market_news Mongo collection (DATA-2). Zero
    # LLM cost on the grade path; the LLM sentiment classification is
    # done at ingest time by scripts/data/classify_news_rows.py.
    if _market_researcher_enabled():
        voices.append(MarketResearcherVoice())
    # Sprint 29 (2026-06-01): oracle_voice — 7th voice, env-gated default
    # OFF. Reads cross-source price snapshots (Pyth + Jupiter from the
    # oracle_snapshots Mongo collection) and grades cross-source agreement.
    # Zero LLM calls; deterministic confidence. NOTE: when this voice is
    # enabled, also set GECKO_QUORUM_VETO_BEARISH=5 to preserve the
    # ~60% bearish-quorum bar at the higher panel cardinality (3/5≈4/6≈5/7).
    if _oracle_voice_enabled():
        voices.append(OracleVoice())
    return LocalPanel(voices=voices, memory=memory, coordinator=coordinator)


__all__ = ["build_local_panel"]
