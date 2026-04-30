"""Tests for `gecko pulse` CLI command (S4-ADVISOR-05)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from click.testing import CliRunner
from gecko_cli.main import cli
from gecko_core.orchestration.advisor.models import (
    PANEL_VOICE_ORDER,
    AdvisorPanel,
    AdvisorVoice,
    PulseDelta,
    PulsePanel,
)


def _canned_pulse(sid: UUID, *, changed: bool) -> PulsePanel:
    voices = [
        AdvisorVoice(
            role=role,
            model_used=f"stub/{role.value}",
            output_md="x",
            closing_line=f"{role.value} now",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
        )
        for role in PANEL_VOICE_ORDER
    ]
    panel = AdvisorPanel(
        session_id=str(sid),
        voices=voices,
        total_cost_usd=0.0,
        generated_at=datetime.now().astimezone(),
    )
    deltas = [
        PulseDelta(
            role=role,
            previous_closing_line=f"{role.value} prev" if changed else None,
            current_closing_line=f"{role.value} now",
            changed=changed,
            reason="closing line shifted vs prior pulse" if changed else "no prior pulse on file",
        )
        for role in PANEL_VOICE_ORDER
    ]
    return PulsePanel(panel=panel, deltas=deltas, previous_panel_at=None)


def test_pulse_renders_delta_table_no_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = uuid4()

    async def _fake(session_id: UUID | str, **_: Any) -> PulsePanel:
        return _canned_pulse(sid, changed=False)

    import gecko_core.orchestration.advisor as advisor_core

    monkeypatch.setattr(advisor_core, "run_pulse", _fake)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["pulse", str(sid)],
        env={"COLUMNS": "240"},
    )
    assert result.exit_code == 0, result.output
    assert "Pulse" in result.output
    assert "no" in result.output.lower()  # changed column


def test_pulse_renders_changed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = uuid4()

    async def _fake(session_id: UUID | str, **_: Any) -> PulsePanel:
        return _canned_pulse(sid, changed=True)

    import gecko_core.orchestration.advisor as advisor_core

    monkeypatch.setattr(advisor_core, "run_pulse", _fake)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["pulse", str(sid)],
        env={"COLUMNS": "240"},
    )
    assert result.exit_code == 0, result.output
    assert "yes" in result.output.lower()
