"""S23-REPORT-01 — POST /report/{session_id} route tests.

Covers:
- Happy path: valid session_id returns 200 text/html
- 404 on unknown session_id
- format=markdown returns JSON with "markdown" key
- 402 stub-mode flow (route is x402-gated)
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _purge_gecko_api_modules() -> None:
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)


def _build_fake_store(
    *,
    result_json: dict | None = None,
) -> AsyncMock:
    store = AsyncMock()
    store.create = AsyncMock(side_effect=lambda *a, **kw: uuid4())
    store.set_tx_signature = AsyncMock(return_value=None)
    store.set_price = AsyncMock(return_value=None)
    store.get = AsyncMock(return_value=None)
    store.get_result = AsyncMock(return_value=result_json)
    store.set_result = AsyncMock(return_value=None)
    store.set_error = AsyncMock(return_value=None)
    store.update_status = AsyncMock(return_value=None)
    store.set_session_project = AsyncMock(return_value=None)
    store._project_spend = AsyncMock(return_value=(0.0, 0))
    return store


def _minimal_result_json(session_id: str = "test-session-abc") -> dict:
    """Return a minimal valid ResearchResult JSON for store.get_result to return."""
    return {
        "session_id": session_id,
        "tier": "basic",
        "verdict": "REFINE",
        "verdict_hash": "deadbeef1234" + "0" * 52,
        "low_grounding": False,
        "low_explanation": False,
        "business_plan": {
            "problem": "Founders struggle to validate ideas.",
            "icp": "Early-stage founders",
            "solution": "Multi-agent debate",
            "market": "Startup tooling",
            "business_model": "Pay per verdict",
            "channels": "MCP",
            "risks": ["Competition"],
            "citations": [
                {
                    "source_url": "https://example.com/source",
                    "chunk_index": 0,
                    "similarity": 0.75,
                }
            ],
        },
        "validation_report": {
            "market_size_signal": "Large",
            "competitor_analysis": "Several",
            "demand_evidence": "High demand",
            "risk_flags": ["Key person risk"],
            "citations": [
                {
                    "source_url": "https://example.com/source",
                    "chunk_index": 0,
                    "similarity": 0.75,
                }
            ],
            "gap_classification": "Partial:UX",
            "gap_summary": "Lacks adversarial debate",
            "gap_explanation": "Competitors offer basic validation without debate.",
        },
        "prd": {
            "v1_scope": ["Basic verdict"],
            "v2_scope": ["Pro debate"],
            "v3_scope": ["Flywheel"],
            "acceptance_criteria": ["Verdict in < 30s"],
            "non_functional": ["99.9% uptime"],
            "success_metrics": ["50 sessions/day"],
            "citations": [
                {
                    "source_url": "https://example.com/source",
                    "chunk_index": 0,
                    "similarity": 0.75,
                }
            ],
        },
        "sources": [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_session_id() -> str:
    return str(uuid4())


@pytest.fixture
def client_with_result(valid_session_id: str) -> Iterator[TestClient]:
    """TestClient with a valid result_json seeded for the session."""
    os.environ["X402_MODE"] = "stub"
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_WALLET_ADDRESS_NOT_FOR_LIVE"
    os.environ["TAVILY_API_KEY"] = "test-tavily-key"
    _purge_gecko_api_modules()

    from gecko_api.main import app

    result_data = _minimal_result_json(session_id=valid_session_id)
    fake_store = _build_fake_store(result_json=result_data)

    with (
        patch("gecko_api.main.SessionStore.from_env", return_value=fake_store),
        patch("gecko_api.main._run_research_background", new=AsyncMock(return_value=None)),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


@pytest.fixture
def client_with_no_result(valid_session_id: str) -> Iterator[TestClient]:
    """TestClient where store.get_result returns None (session not found)."""
    os.environ["X402_MODE"] = "stub"
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_WALLET_ADDRESS_NOT_FOR_LIVE"
    os.environ["TAVILY_API_KEY"] = "test-tavily-key"
    _purge_gecko_api_modules()

    from gecko_api.main import app

    fake_store = _build_fake_store(result_json=None)

    with (
        patch("gecko_api.main.SessionStore.from_env", return_value=fake_store),
        patch("gecko_api.main._run_research_background", new=AsyncMock(return_value=None)),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_report_route_returns_402_without_payment(
    valid_session_id: str,
    client_with_result: TestClient,
) -> None:
    """Stub mode still issues a 402 challenge before serving the report."""
    r = client_with_result.post(f"/report/{valid_session_id}")
    assert r.status_code == 402


def test_report_route_advertises_price_in_402(
    valid_session_id: str,
    client_with_result: TestClient,
) -> None:
    """The 402 challenge header should contain the $0.05 price."""
    import base64
    import json

    r = client_with_result.post(f"/report/{valid_session_id}")
    assert r.status_code == 402
    payment_req = r.headers.get("payment-required")
    assert payment_req is not None
    decoded = json.loads(base64.b64decode(payment_req).decode("utf-8"))
    amounts = {entry["amount"] for entry in decoded["accepts"]}
    # $0.05 = 50_000 USDC lamports (6 decimals)
    assert "50000" in amounts, f"Expected 50000 in {amounts}"


def test_report_route_appears_in_well_known(
    client_with_result: TestClient,
) -> None:
    """The report route must be visible in /.well-known/x402."""
    r = client_with_result.get("/.well-known/x402")
    assert r.status_code == 200
    body = r.json()
    routes = {entry["route"] for entry in body["routes"]}
    # The route is registered as "POST /report/{session_id}"
    assert any("report" in route for route in routes), f"report route missing from {routes}"


def test_report_happy_path_html(
    valid_session_id: str,
    client_with_result: TestClient,
) -> None:
    """After x402 settle, report returns 200 text/html containing the session_id."""
    # In stub mode, we can inject a fake payment header to bypass the 402
    # challenge. The StubFacilitatorClient accepts any payment token.
    import base64
    import json

    # Get the 402 challenge first
    r_challenge = client_with_result.post(f"/report/{valid_session_id}")
    assert r_challenge.status_code == 402

    payment_req_b64 = r_challenge.headers["payment-required"]
    accepts_entry = json.loads(base64.b64decode(payment_req_b64).decode("utf-8"))["accepts"][0]

    payment_payload = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
        "accepted": accepts_entry,
    }
    payment_b64 = base64.b64encode(json.dumps(payment_payload).encode("utf-8")).decode("utf-8")

    r = client_with_result.post(
        f"/report/{valid_session_id}",
        headers={"PAYMENT-SIGNATURE": payment_b64},
    )
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert valid_session_id in r.text


def test_report_404_on_unknown_session(
    client_with_no_result: TestClient,
) -> None:
    """POST /report/{unknown_id} → 404 after payment (session not found)."""
    import base64
    import json

    unknown_id = str(uuid4())

    # Get the 402 challenge
    r_challenge = client_with_no_result.post(f"/report/{unknown_id}")
    assert r_challenge.status_code == 402

    payment_req_b64 = r_challenge.headers["payment-required"]
    accepts_entry = json.loads(base64.b64decode(payment_req_b64).decode("utf-8"))["accepts"][0]

    payment_payload = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
        "accepted": accepts_entry,
    }
    payment_b64 = base64.b64encode(json.dumps(payment_payload).encode("utf-8")).decode("utf-8")

    r = client_with_no_result.post(
        f"/report/{unknown_id}",
        headers={"PAYMENT-SIGNATURE": payment_b64},
    )
    assert r.status_code == 404


def test_report_markdown_format(
    valid_session_id: str,
    client_with_result: TestClient,
) -> None:
    """format=markdown returns JSON with a 'markdown' key."""
    import base64
    import json

    r_challenge = client_with_result.post(
        f"/report/{valid_session_id}", params={"format": "markdown"}
    )
    assert r_challenge.status_code == 402

    payment_req_b64 = r_challenge.headers["payment-required"]
    accepts_entry = json.loads(base64.b64decode(payment_req_b64).decode("utf-8"))["accepts"][0]

    payment_payload = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
        "accepted": accepts_entry,
    }
    payment_b64 = base64.b64encode(json.dumps(payment_payload).encode("utf-8")).decode("utf-8")

    r = client_with_result.post(
        f"/report/{valid_session_id}",
        params={"format": "markdown"},
        headers={"PAYMENT-SIGNATURE": payment_b64},
    )
    assert r.status_code == 200
    body = r.json()
    assert "markdown" in body
    assert isinstance(body["markdown"], str)
    assert len(body["markdown"]) > 0
