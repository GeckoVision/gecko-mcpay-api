"""S12-HARDEN-02 — body-size cap + idea field constraint.

The cap is enforced two ways:
  1. Pydantic field constraint (`idea: max_length=2000`) — rejects with 422
     when the payload reaches the route handler.
  2. ASGI body-size middleware — rejects with 400 BEFORE the handler runs
     when the raw body exceeds 10KB. This is the one that matters for OOM
     defense; an attacker who sends 100MB of garbage shouldn't get to
     allocate that on the server side at all.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    os.environ.setdefault("X402_MODE", "stub")
    os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_TEST_WALLET")
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)
    from gecko_api.main import app

    with TestClient(app) as c:
        yield c


def test_oversize_idea_rejected_with_400(client: TestClient) -> None:
    """100KB idea → 400 from the body-size middleware (before handler runs)."""
    huge = "x" * 100_000
    r = client.post("/research", json={"idea": huge, "tier": "basic"})
    assert r.status_code == 400, r.text
    assert "exceeds" in r.json()["detail"].lower()


def test_nine_kb_payload_passes_body_check(client: TestClient) -> None:
    """A 9KB payload (under the 10KB cap) reaches the handler — meaning we
    see a 402 from x402 (or a 422 from Pydantic if idea > 2000 chars), but
    NOT a 400 from the body-size middleware."""
    # 9KB of valid characters; idea must stay under 2000 chars too, so
    # we pad the JSON with a comment-like ignored field instead.
    idea = "valid idea " * 100  # ~1100 chars
    big_padding = "x" * 8000
    r = client.post(
        "/research",
        json={
            "idea": idea,
            "tier": "basic",
            # extra unknown fields are ignored by Pydantic but count toward
            # the raw body byte total, exercising the streaming check.
            "_padding": big_padding,
        },
    )
    # Should NOT be 400 from body-size. Either 402 (rate-limit not yet
    # hit, x402 demands payment) or 422 (Pydantic rejects unknown shape)
    # are both valid pass cases here.
    assert r.status_code != 400, r.text


def test_idea_field_constraints_enforced_on_pydantic_model() -> None:
    """The ResearchRequest schema has min_length=10 / max_length=2000.

    We assert this at the Pydantic level rather than over HTTP because x402's
    middleware returns 402 on unpaid POSTs before FastAPI ever runs request
    validation. The schema constraint still matters: it's the layer that
    catches a 1.5KB-but-valid-payment idea before the handler kicks off the
    expensive workflow.
    """
    import pytest as _pytest
    from gecko_api.main import ResearchRequest
    from pydantic import ValidationError

    # Boundary cases — accepted.
    ResearchRequest(idea="x" * 10)
    ResearchRequest(idea="x" * 2000)

    # Too short.
    with _pytest.raises(ValidationError):
        ResearchRequest(idea="short")

    # Too long.
    with _pytest.raises(ValidationError):
        ResearchRequest(idea="x" * 2001)


def test_oversize_plan_payload_rejected(client: TestClient) -> None:
    """/plan also gets the body-size cap."""
    huge = "x" * 100_000
    r = client.post(
        "/plan",
        json={
            "session_id": "11111111-1111-1111-1111-111111111111",
            "_padding": huge,
        },
    )
    assert r.status_code == 400, r.text
