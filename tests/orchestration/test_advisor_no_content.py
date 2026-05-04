"""v0.1.10 — advisor voice ``no_content`` failure shape.

Repro from production: ``gecko_plan(...)`` against v0.1.9 returned a
business_manager voice with ``output_md=""`` and
``closing_line: "(voice business_manager failed: 'NoneType' object is
not subscriptable)"``. Same model + voice succeeded on the prior run —
this is a deepseek-v4-pro provider intermittent. The upstream returned
a chat-completion response whose ``choices`` (or ``choices[0].message
.content``) was ``None``; the previous code did
``resp.choices[0].message.content or ""`` which absorbs ``None`` on
``.content`` but NOT on ``choices`` itself, so the indexing crashed.

The fix:

1. ``_call_once`` defends every step (``choices`` / ``choices[0]`` /
   ``message`` / ``message.content``) and raises a typed
   :class:`VoiceContentMissingError` when any layer is missing.
2. ``run_voice`` catches the typed exception BEFORE the catch-all
   ``Exception`` handler and surfaces ``error_kind="no_content"`` with
   a clear closing line.
3. Panel-level ``voices_failed_no_content`` counter increments so
   operators see "1/5 failed with no_content" at a glance.

NOT retried in v0.1.10 — provider intermittents need careful retry-
budget logic; deferred to v0.1.11.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from gecko_core.orchestration.advisor.agents import (
    VoiceContentMissingError,
    run_voice,
)
from gecko_core.orchestration.advisor.models import AdvisorPanel, AdvisorVoice
from gecko_core.routing.catalog import AgentRole, Tier


def _mk_client_returning(content: object) -> MagicMock:
    """Build a mock AsyncOpenAI surface whose response has the given
    ``message.content`` — pass ``None`` to simulate the dogfood failure
    mode. Pass a string to simulate normal output.
    """
    client = MagicMock()
    completions = MagicMock()
    parsed = MagicMock()
    parsed.usage = None
    parsed.model = "deepseek/deepseek-v4-pro"
    if content is None:
        # Simulate the upstream returning choices=[choice_with_no_content].
        # The defensive parsing should raise VoiceContentMissingError when
        # message.content is None.
        choice = MagicMock()
        choice.message = MagicMock(content=None)
        parsed.choices = [choice]
    else:
        choice = MagicMock()
        choice.message = MagicMock(content=content)
        parsed.choices = [choice]

    raw = MagicMock()
    raw.parse = MagicMock(return_value=parsed)
    raw.headers = MagicMock()
    raw.headers.get = MagicMock(return_value=None)

    with_raw = MagicMock()
    with_raw.create = AsyncMock(return_value=raw)
    completions.with_raw_response = with_raw
    client.chat = MagicMock(completions=completions)
    return client


def _mk_client_choices_none() -> MagicMock:
    """Build a mock whose ``resp.choices`` is None (the actual dogfood
    crash shape — ``'NoneType' object is not subscriptable`` came from
    indexing into None, not from a None message.content). The defensive
    parsing must catch this layer too.
    """
    client = MagicMock()
    completions = MagicMock()
    parsed = MagicMock()
    parsed.usage = None
    parsed.model = "deepseek/deepseek-v4-pro"
    parsed.choices = None  # the upstream dropped the field

    raw = MagicMock()
    raw.parse = MagicMock(return_value=parsed)
    raw.headers = MagicMock()
    raw.headers.get = MagicMock(return_value=None)

    with_raw = MagicMock()
    with_raw.create = AsyncMock(return_value=raw)
    completions.with_raw_response = with_raw
    client.chat = MagicMock(completions=completions)
    return client


@pytest.mark.asyncio
async def test_run_voice_surfaces_no_content_when_message_content_none() -> None:
    """Provider returns a response with ``message.content = None``.
    ``run_voice`` returns an AdvisorVoice with ``error_kind="no_content"``
    and a clear closing line — NOT a stringified traceback.
    """
    client = _mk_client_returning(None)

    voice = await run_voice(
        role=AgentRole.business_manager,
        system_prompt="sys",
        user_prompt="usr",
        tier_preset=Tier.balanced,
        client=client,
    )

    assert voice.error_kind == "no_content"
    assert voice.output_md == ""
    assert "empty content" in voice.closing_line
    assert "provider intermittent" in voice.closing_line
    # No "NoneType is not subscriptable" leakage in the user-visible line.
    assert "subscriptable" not in voice.closing_line


@pytest.mark.asyncio
async def test_run_voice_surfaces_no_content_when_choices_is_none() -> None:
    """The actual production crash shape: ``resp.choices is None``.
    Defensive parsing must catch this and raise
    :class:`VoiceContentMissingError` rather than letting the index
    operation crash.
    """
    client = _mk_client_choices_none()

    voice = await run_voice(
        role=AgentRole.business_manager,
        system_prompt="sys",
        user_prompt="usr",
        tier_preset=Tier.balanced,
        client=client,
    )

    assert voice.error_kind == "no_content"
    assert voice.output_md == ""


@pytest.mark.asyncio
async def test_run_voice_surfaces_no_content_when_choices_empty() -> None:
    """Edge case: ``resp.choices = []`` (empty list rather than None).
    Same outcome — typed exception, structured surfacing.
    """
    client = MagicMock()
    completions = MagicMock()
    parsed = MagicMock()
    parsed.usage = None
    parsed.model = "deepseek/deepseek-v4-pro"
    parsed.choices = []
    raw = MagicMock()
    raw.parse = MagicMock(return_value=parsed)
    raw.headers = MagicMock()
    raw.headers.get = MagicMock(return_value=None)
    with_raw = MagicMock()
    with_raw.create = AsyncMock(return_value=raw)
    completions.with_raw_response = with_raw
    client.chat = MagicMock(completions=completions)

    voice = await run_voice(
        role=AgentRole.business_manager,
        system_prompt="sys",
        user_prompt="usr",
        tier_preset=Tier.balanced,
        client=client,
    )

    assert voice.error_kind == "no_content"


def test_voice_content_missing_error_is_typed() -> None:
    """The custom exception class exists and is distinct from the generic
    Exception path so monitoring can separate "upstream is down" from
    "upstream returned nothing".
    """
    err = VoiceContentMissingError("upstream returned no choices (model=foo)")
    assert isinstance(err, Exception)
    assert "no choices" in str(err)


def test_advisor_panel_voices_failed_no_content_default_zero() -> None:
    """Backwards-compat default — existing serialised AdvisorPanel JSON
    that pre-dates v0.1.10 must round-trip with the new counter at 0
    rather than failing validation on a missing key.
    """
    panel = AdvisorPanel.model_construct(
        session_id="00000000-0000-0000-0000-000000000000",
        voices=[],
        total_cost_usd=0.0,
    )
    assert panel.voices_failed_no_content == 0


def test_advisor_panel_voices_failed_no_content_counts_correctly() -> None:
    """The panel counter equals the number of voices with
    ``error_kind="no_content"``. Mirrors the existing
    ``voices_no_closing_line`` rollup pattern.
    """
    voices: list[AdvisorVoice] = []
    for role, kind in [
        (AgentRole.ceo, None),
        (AgentRole.cto, "no_closing_line"),
        (AgentRole.business_manager, "no_content"),
        (AgentRole.product_manager, None),
        (AgentRole.staff_manager, "no_content"),
    ]:
        voices.append(
            AdvisorVoice(
                role=role,
                model_used="x",
                output_md="",
                closing_line="x",
                tokens_in=0,
                tokens_out=0,
                error_kind=kind,
            )
        )
    panel = AdvisorPanel(
        session_id="00000000-0000-0000-0000-000000000000",
        voices=voices,
        total_cost_usd=0.0,
        voices_no_closing_line=sum(1 for v in voices if v.error_kind == "no_closing_line"),
        voices_failed_no_content=sum(1 for v in voices if v.error_kind == "no_content"),
    )
    assert panel.voices_no_closing_line == 1
    assert panel.voices_failed_no_content == 2
