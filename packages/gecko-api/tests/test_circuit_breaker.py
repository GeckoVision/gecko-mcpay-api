"""S12-HARDEN-04 — cost circuit breaker.

Tests the rolling-window tracker directly (unit) and against the live
/research + /plan endpoints (integration). The simulated-spend test
records 100 fake LLM completions at $0.10 each; the breaker opens after
the cumulative window exceeds the $5 threshold.
"""

from __future__ import annotations

import os
import sys
import time
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


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------


def test_breaker_opens_above_threshold() -> None:
    from gecko_api.circuit_breaker import CostCircuitBreaker

    b = CostCircuitBreaker(budget_usd_per_minute=5.0, window_seconds=60.0)
    assert not b.is_open()

    # Simulate 100 LLM completions at $0.10 each. Breaker should open
    # somewhere around call 50 (when cumulative > $5).
    open_at: int | None = None
    for i in range(100):
        b.record_spend(0.10)
        if open_at is None and b.is_open():
            open_at = i + 1
    assert open_at is not None, "breaker never opened with $10 cumulative spend"
    # Threshold $5, $0.10 each → opens after call 51.
    assert 45 <= open_at <= 55, f"breaker opened at call {open_at}; expected ~50"


def test_breaker_recovers_after_window_slides() -> None:
    from gecko_api.circuit_breaker import CostCircuitBreaker

    # Tiny window to keep test fast.
    b = CostCircuitBreaker(budget_usd_per_minute=1.0, window_seconds=0.5)
    for _ in range(20):
        b.record_spend(0.10)
    assert b.is_open()

    time.sleep(0.6)  # window slides past all entries
    assert not b.is_open()
    assert b.current_spend_per_minute() == 0.0


def test_breaker_ignores_zero_or_negative_spend() -> None:
    from gecko_api.circuit_breaker import CostCircuitBreaker

    b = CostCircuitBreaker()
    b.record_spend(0)
    b.record_spend(-1.0)
    assert b.current_spend_per_minute() == 0.0


# ---------------------------------------------------------------------------
# Integration — wired into /research and /plan
# ---------------------------------------------------------------------------


def test_research_returns_503_when_breaker_open(client: TestClient) -> None:
    from gecko_api.circuit_breaker import get_breaker, reset_breaker

    reset_breaker()
    # Saturate the breaker.
    breaker = get_breaker()
    for _ in range(100):
        breaker.record_spend(0.10)
    assert breaker.is_open()

    r = client.post(
        "/research",
        json={"idea": "valid test idea " * 3, "tier": "basic"},
        headers={"X-Payment": "bypass-rate-limit"},  # avoid rate limit confounding
    )
    assert r.status_code == 503, r.text
    assert r.headers.get("retry-after") == "30"
    reset_breaker()


def test_plan_returns_503_when_breaker_open(client: TestClient) -> None:
    from gecko_api.circuit_breaker import get_breaker, reset_breaker

    reset_breaker()
    breaker = get_breaker()
    for _ in range(100):
        breaker.record_spend(0.10)

    r = client.post(
        "/plan",
        json={"session_id": "11111111-1111-1111-1111-111111111111"},
        headers={"X-Payment": "bypass-rate-limit"},
    )
    assert r.status_code == 503, r.text
    assert r.headers.get("retry-after") == "30"
    reset_breaker()


def test_breaker_closed_research_returns_normal_status(client: TestClient) -> None:
    """Sanity: with the breaker closed, the endpoint returns its normal
    402 (no payment) — proving 503 is breaker-specific, not unconditional."""
    from gecko_api.circuit_breaker import reset_breaker

    reset_breaker()
    r = client.post("/research", json={"idea": "valid idea text", "tier": "basic"})
    assert r.status_code != 503
    # First unpaid request is a 402.
    assert r.status_code == 402
