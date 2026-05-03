"""Tests for the POST /pulse endpoint (S8-API-01).

session_id path calls run_pulse_v14 (returns PulseResult).
project_id-only path calls run_pulse (returns PulsePanel).
Free when PULSE_CALL_PRICE=$0.00 (explicit in every fixture — default is $0.50).

    1. Returns PulseResult JSON when session_id given.
    2. Returns 200 when project_id given.
    3. Missing both session_id and project_id -> 400.
    4. Invalid session_id -> 400.
    5. session_id wins over project_id (dispatches to run_pulse_v14).
    6. /.well-known/x402 does NOT advertise /pulse when price is $0.00.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

os.environ["X402_MODE"] = "stub"
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")
os.environ.pop("PULSE_CALL_PRICE", None)


def _make_panel() -> Any:
    from gecko_core.orchestration.advisor.models import (
        PANEL_VOICE_ORDER,
        AdvisorPanel,
        AdvisorVoice,
    )

    voices = [
        AdvisorVoice(
            role=role,
            model_used=f"stub/{role.value}",
            output_md=f"# {role.value}",
            closing_line=f"closing-{role.value}",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
        )
        for role in PANEL_VOICE_ORDER
    ]
    return AdvisorPanel(
        session_id="00000000-0000-0000-0000-000000000999",
        voices=voices,
        total_cost_usd=0.0,
        generated_at=datetime.now(tz=UTC),
    )


def _make_pulse_result(parent_session_id: str = "00000000-0000-0000-0000-000000000111") -> Any:
    from gecko_core.models import Verdict
    from gecko_core.orchestration.advisor.models import PulseResult

    return PulseResult(
        parent_session_id=parent_session_id,
        pulse_session_id="00000000-0000-0000-0000-000000000999",
        idea="hotel guide",
        verdict=Verdict.REFINE,
        gap_classification="Partial:segment",
        panel=_make_panel(),
        summary_bullets=["signal stable"],
    )


def _make_pulse_panel() -> Any:
    from gecko_core.orchestration.advisor.models import (
        PANEL_VOICE_ORDER,
        AdvisorPanel,
        AdvisorVoice,
        PulseDelta,
        PulsePanel,
    )

    voices = [
        AdvisorVoice(
            role=role,
            model_used=f"stub/{role.value}",
            output_md=f"# {role.value}",
            closing_line=f"closing-{role.value}",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
        )
        for role in PANEL_VOICE_ORDER
    ]
    deltas = [
        PulseDelta(
            role=role,
            previous_closing_line=None,
            current_closing_line=f"closing-{role.value}",
            changed=False,
            reason=None,
        )
        for role in PANEL_VOICE_ORDER
    ]
    panel = AdvisorPanel(
        session_id="00000000-0000-0000-0000-000000000111",
        voices=voices,
        total_cost_usd=0.0,
        generated_at=datetime.now(tz=UTC),
    )
    return PulsePanel(panel=panel, deltas=deltas, previous_panel_at=None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    os.environ["X402_MODE"] = "stub"
    os.environ.pop("X402_NETWORK", None)
    os.environ["PULSE_CALL_PRICE"] = "$0.00"
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)

    from gecko_api.main import app

    fake_result = _make_pulse_result()
    fake_panel = _make_pulse_panel()

    with (
        patch(
            "gecko_core.orchestration.advisor.run_pulse_v14",
            new=AsyncMock(return_value=fake_result),
        ),
        patch(
            "gecko_core.orchestration.advisor.run_pulse",
            new=AsyncMock(return_value=fake_panel),
        ),
        TestClient(app) as c,
    ):
        yield c


def test_pulse_returns_result_for_session(client: TestClient) -> None:
    r = client.post(
        "/pulse",
        json={"session_id": "00000000-0000-0000-0000-000000000111"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # PulseResult shape: parent_session_id + panel.voices
    assert body["parent_session_id"] == "00000000-0000-0000-0000-000000000111"
    assert len(body["panel"]["voices"]) == 5


def test_pulse_returns_panel_for_project(client: TestClient) -> None:
    r = client.post(
        "/pulse",
        json={"project_id": "00000000-0000-0000-0000-000000000222"},
    )
    assert r.status_code == 200, r.text


def test_pulse_requires_session_or_project(client: TestClient) -> None:
    r = client.post("/pulse", json={})
    assert r.status_code == 400, r.text
    assert "session_id or project_id" in r.text


def test_pulse_invalid_session_id(client: TestClient) -> None:
    r = client.post("/pulse", json={"session_id": "not-a-uuid"})
    assert r.status_code == 400, r.text
    assert "invalid session_id" in r.text


def test_pulse_session_id_dispatches_to_v14() -> None:
    """session_id → run_pulse_v14(parent_session_id=sid). project_id ignored."""
    os.environ["X402_MODE"] = "stub"
    os.environ.pop("X402_NETWORK", None)
    os.environ["PULSE_CALL_PRICE"] = "$0.00"
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)
    from gecko_api.main import app

    fake_result = _make_pulse_result()
    captured: dict[str, object] = {}

    async def _spy_v14(parent_session_id: object, **kwargs: object) -> object:
        captured["parent_session_id"] = parent_session_id
        return fake_result

    with (
        patch("gecko_core.orchestration.advisor.run_pulse_v14", new=_spy_v14),
        TestClient(app) as c,
    ):
        r = c.post(
            "/pulse",
            json={
                "session_id": "00000000-0000-0000-0000-000000000111",
                "project_id": "00000000-0000-0000-0000-000000000333",
            },
        )
    assert r.status_code == 200, r.text
    # session_id wins: run_pulse_v14 called with the session UUID
    assert captured["parent_session_id"] == UUID("00000000-0000-0000-0000-000000000111")


def test_well_known_does_not_advertise_pulse_at_zero_price(client: TestClient) -> None:
    r = client.get("/.well-known/x402")
    assert r.status_code == 200
    routes = {entry["route"] for entry in r.json()["routes"]}
    assert "POST /pulse" not in routes
