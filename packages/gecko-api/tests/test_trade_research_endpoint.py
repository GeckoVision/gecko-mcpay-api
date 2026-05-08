"""Tests for POST /trade_research (Phase 8b).

Free endpoint (no x402 gate) — the FastAPI TestClient should hit it without
PAYMENT headers. Mocks ``run_trade_panel_with_retrieval`` so this never
fires AG2 or touches Mongo / OpenAI.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Force stub mode + a stub wallet BEFORE importing the app — settings are
# frozen at import time. Mirrors the test_route_endpoint.py fixture.
os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")


@pytest.fixture
def client() -> Iterator[TestClient]:
    os.environ["X402_NETWORK"] = "solana-devnet"
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)

    from gecko_api.main import app
    from gecko_core.orchestration.trade_panel import TradePanelTurn, TradePanelVerdict

    fake_verdict = TradePanelVerdict(
        verdict="act",
        confidence=0.7,
        key_drivers=["technical alignment", "TVL growth"],
        dissent_count=1,
        blocker_questions=["Does Pyth uptime hold?"],
        turns=[
            TradePanelTurn(
                agent="technical_analyst",
                content="bullish trend",
                parsed_verdict={"trend_verdict": "bullish"},
            ),
            TradePanelTurn(
                agent="coordinator",
                content='```json\n{"verdict": "act"}\n```',
                parsed_verdict={"verdict": "act"},
            ),
        ],
    )

    with (
        patch(
            "gecko_core.orchestration.trade_panel.run_trade_panel_with_retrieval",
            new=AsyncMock(return_value=fake_verdict),
        ),
        TestClient(app) as c,
    ):
        yield c


def test_trade_research_happy_path_returns_verdict(client: TestClient) -> None:
    r = client.post(
        "/trade_research",
        json={
            "idea": "Should I open a JTO long into the next FOMC?",
            "protocol": "jito",
            "vertical": "dex",
            "tier": "basic",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Verdict shape — must serialize the canonical TradePanelVerdict fields.
    assert body["verdict"] == "act"
    assert body["confidence"] == pytest.approx(0.7)
    assert body["dissent_count"] == 1
    assert "TVL growth" in body["key_drivers"]
    assert body["blocker_questions"] == ["Does Pyth uptime hold?"]
    # turns ship as a list of dicts, not the pydantic model itself.
    assert isinstance(body["turns"], list)
    assert all(isinstance(t, dict) for t in body["turns"])
    assert body["turns"][0]["agent"] == "technical_analyst"


def test_trade_research_missing_protocol_returns_422(client: TestClient) -> None:
    """Pydantic validation rejects requests without the required protocol field."""
    r = client.post(
        "/trade_research",
        json={"idea": "Should I act on this?", "vertical": "dex"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    # FastAPI surfaces the missing-field error with loc=["body", "protocol"].
    missing = [d for d in detail if d.get("loc", [])[-1] == "protocol"]
    assert missing, f"expected 'protocol' in 422 detail, got {detail!r}"


def test_trade_research_short_idea_returns_422(client: TestClient) -> None:
    """min_length=3 on idea catches degenerate inputs at the wire boundary."""
    r = client.post(
        "/trade_research",
        json={"idea": "x", "protocol": "jito"},
    )
    assert r.status_code == 422


def test_trade_research_is_free_no_402(client: TestClient) -> None:
    """Phase 8b ships unpaid — no PAYMENT-SIGNATURE header required."""
    r = client.post(
        "/trade_research",
        json={"idea": "valid idea here", "protocol": "drift"},
    )
    # Either 200 (mock) or 5xx (real call missing config) — but never 402.
    assert r.status_code != 402


def test_trade_research_defaults_vertical_to_dex(client: TestClient) -> None:
    """vertical is optional; default 'dex' matches the trading-oracle corpus."""
    r = client.post(
        "/trade_research",
        json={"idea": "Should I act here?", "protocol": "kamino"},
    )
    assert r.status_code == 200, r.text
    # The Pydantic default surfaces inside the handler — best we can assert
    # at the wire boundary is that the request succeeds without vertical.
