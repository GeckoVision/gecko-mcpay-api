"""Advisor Panel orchestration shell (Sprint 4 Track A).

Five named leadership voices (CEO, CTO, business_manager, product_manager,
staff_manager) read a session's Pro debate output + scaffold artifacts +
flywheel + V1 source signal and produce opinionated, persona-anchored
advice.

Voices are INDEPENDENT, parallel ``asyncio.gather`` calls — NOT an AG2
GroupChat. The panel's value comes from voices DISAGREEING (CEO timing vs
CTO refactor timing is the canonical example); a conversational chat would
let one persona dominate. Per-voice model selection comes from
``routing.catalog.lookup_model``: at ``Tier.balanced`` the panel uses
five different models tuned for each voice's primary task profile.

Public surface:

- ``generate_panel(session_id, ...)`` — full 5-voice panel.
- ``generate_voice(session_id, voice, ...)`` — single voice (cheaper).
- ``run_pulse(panel, previous_panel)`` — delta detection vs prior run.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID

from openai import AsyncOpenAI

from gecko_core.orchestration.advisor.agents import run_voice
from gecko_core.orchestration.advisor.context import (
    AdvisorContext,
    load_context,
    render_context_block,
)
from gecko_core.orchestration.advisor.models import (
    PANEL_VOICE_ORDER,
    AdvisorError,
    AdvisorPanel,
    AdvisorSessionNotFoundError,
    AdvisorVoice,
    PulseDelta,
    PulsePanel,
)
from gecko_core.orchestration.advisor.prompts import REQUIRED_VOICES, load_prompts
from gecko_core.routing.catalog import AgentRole, Tier
from gecko_core.sessions.store import SessionStore

logger = logging.getLogger(__name__)


def _voice_role(voice: str | AgentRole) -> AgentRole:
    """Normalize a voice identifier (str or enum) to an AgentRole.

    Accepts both ``"ceo"`` / ``"cto"`` / ``"business_manager"`` / etc. and
    short aliases ``"bm"`` / ``"pm"`` / ``"sm"`` (used by MCP/CLI).
    """
    if isinstance(voice, AgentRole):
        return voice
    key = voice.strip().lower()
    aliases = {
        "bm": AgentRole.business_manager,
        "pm": AgentRole.product_manager,
        "sm": AgentRole.staff_manager,
    }
    if key in aliases:
        return aliases[key]
    try:
        role = AgentRole(key)
    except ValueError as exc:
        raise ValueError(
            f"unknown advisor voice {voice!r}; expected one of {list(REQUIRED_VOICES)} "
            "(or aliases bm/pm/sm)"
        ) from exc
    if role not in PANEL_VOICE_ORDER:
        raise ValueError(f"role {role.value!r} is not an Advisor Panel voice")
    return role


def _build_default_client() -> AsyncOpenAI:
    """Build an AsyncOpenAI client from orchestration settings (lazy)."""
    from gecko_core.orchestration.settings import get_orchestration_settings

    orch = get_orchestration_settings()
    return AsyncOpenAI(api_key=orch.llm_api_key, base_url=orch.llm_endpoint)


async def generate_voice(
    session_id: UUID | str,
    voice: str | AgentRole,
    *,
    tier_preset: Tier = Tier.balanced,
    store: SessionStore | None = None,
    output_dir: Path | None = None,
    v1_source_signal: str = "",
    openai_client: AsyncOpenAI | None = None,
    context: AdvisorContext | None = None,
) -> AdvisorVoice:
    """Run a single advisor voice. ~5x cheaper than a full panel.

    Args:
        session_id: UUID of an existing session (any verdict OK — kills
            still get advice on whether to pivot).
        voice: One of {ceo, cto, business_manager, product_manager,
            staff_manager} or aliases {bm, pm, sm}.
        tier_preset: Cost/quality preset; selects the per-voice model
            from the curated catalog. Default: balanced.
        store: SessionStore. Defaults to env-configured.
        output_dir: Workspace root for scaffold lookup. None skips it.
        v1_source_signal: Pre-rendered V1 block (caller owns dispatch).
        openai_client: AsyncOpenAI client. Defaults to env-configured.
        context: Pre-loaded context (used by ``generate_panel`` to share
            one load across all 5 voices). When None, this function
            loads context itself.

    Raises:
        AdvisorSessionNotFoundError: session row missing (only when this
            function loads context itself).
    """
    role = _voice_role(voice)

    if store is None:
        store = SessionStore.from_env()

    if context is None:
        context = await load_context(
            session_id,
            store=store,
            output_dir=output_dir,
            v1_source_signal=v1_source_signal,
        )

    if openai_client is None:
        openai_client = _build_default_client()

    prompts = load_prompts()
    user_prompt = render_context_block(context)

    return await run_voice(
        role=role,
        system_prompt=prompts[role.value],
        user_prompt=user_prompt,
        tier_preset=tier_preset,
        client=openai_client,
    )


async def generate_panel(
    session_id: UUID | str,
    *,
    tier_preset: Tier = Tier.balanced,
    store: SessionStore | None = None,
    output_dir: Path | None = None,
    v1_source_signal: str = "",
    openai_client: AsyncOpenAI | None = None,
) -> AdvisorPanel:
    """Run all 5 advisor voices in parallel and return the AdvisorPanel.

    Voices fan out via ``asyncio.gather`` — total wall-time is roughly
    the slowest single voice (~3x faster than sequential). Failures in one
    voice surface as an AdvisorVoice with empty ``output_md``; the panel
    still returns the other four.

    Voices are returned in ``PANEL_VOICE_ORDER`` (CEO first, staff_manager
    last) regardless of which finished first — staff_manager's prompt
    expects to see the others' outputs in CONTEXT, but in v1 each voice
    sees the same input context. Sprint 5 may chain staff_manager after
    the other four; for now the panel value is the parallel speed.
    """
    sid = session_id if isinstance(session_id, UUID) else UUID(str(session_id))

    if store is None:
        store = SessionStore.from_env()

    context = await load_context(
        sid,
        store=store,
        output_dir=output_dir,
        v1_source_signal=v1_source_signal,
    )

    if openai_client is None:
        openai_client = _build_default_client()

    prompts = load_prompts()
    user_prompt = render_context_block(context)

    async def _one(role: AgentRole) -> AdvisorVoice:
        return await run_voice(
            role=role,
            system_prompt=prompts[role.value],
            user_prompt=user_prompt,
            tier_preset=tier_preset,
            client=openai_client,
        )

    voices = await asyncio.gather(*(_one(r) for r in PANEL_VOICE_ORDER))
    total_cost = sum(v.cost_usd for v in voices if v.cost_usd is not None)

    return AdvisorPanel(
        session_id=str(sid),
        voices=list(voices),
        total_cost_usd=float(total_cost),
        generated_at=datetime.now().astimezone(),
    )


def compute_pulse_deltas(
    *,
    panel: AdvisorPanel,
    previous_panel: AdvisorPanel | None,
) -> list[PulseDelta]:
    """Compare ``panel.voices`` to ``previous_panel.voices`` by closing line.

    v1 heuristic: closing-line text equality. Embedding-based delta
    detection is Sprint 5. Returns one PulseDelta per voice in
    ``PANEL_VOICE_ORDER`` so callers can render a stable table.
    """
    prev_by_role: dict[AgentRole, str] = {}
    if previous_panel is not None:
        for v in previous_panel.voices:
            prev_by_role[v.role] = v.closing_line

    deltas: list[PulseDelta] = []
    for v in panel.voices:
        prev_line = prev_by_role.get(v.role)
        changed = prev_line is not None and prev_line.strip() != v.closing_line.strip()
        # If there was no prior, it's not a "change" — it's a new voice.
        # We surface that as changed=False with reason='no prior pulse'.
        reason: str | None
        if prev_line is None:
            reason = "no prior pulse on file"
        elif changed:
            reason = "closing line shifted vs prior pulse"
        else:
            reason = None
        deltas.append(
            PulseDelta(
                role=v.role,
                previous_closing_line=prev_line,
                current_closing_line=v.closing_line,
                changed=changed,
                reason=reason,
            )
        )
    return deltas


async def run_pulse(
    session_id: UUID | str,
    *,
    previous_panel: AdvisorPanel | None,
    tier_preset: Tier = Tier.balanced,
    store: SessionStore | None = None,
    output_dir: Path | None = None,
    v1_source_signal: str = "",
    openai_client: AsyncOpenAI | None = None,
) -> PulsePanel:
    """Re-run the panel and surface deltas vs the prior pulse (S4-ADVISOR-05).

    Caller is responsible for fetching ``previous_panel`` from
    persistence (the ``pulse_runs`` table once migration 018 lands; until
    then callers can pass None on the first pulse).
    """
    panel = await generate_panel(
        session_id,
        tier_preset=tier_preset,
        store=store,
        output_dir=output_dir,
        v1_source_signal=v1_source_signal,
        openai_client=openai_client,
    )
    deltas = compute_pulse_deltas(panel=panel, previous_panel=previous_panel)
    return PulsePanel(
        panel=panel,
        deltas=deltas,
        previous_panel_at=previous_panel.generated_at if previous_panel else None,
    )


__all__ = [
    "AdvisorContext",
    "AdvisorError",
    "AdvisorPanel",
    "AdvisorSessionNotFoundError",
    "AdvisorVoice",
    "PulseDelta",
    "PulsePanel",
    "compute_pulse_deltas",
    "generate_panel",
    "generate_voice",
    "load_context",
    "render_context_block",
    "run_pulse",
]
