"""Tests for the contest_bot Gecko wrap layer.

Light fakes only — no live network, no slow loops.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

# Make the contest_bot package importable when pytest runs from the
# repo root. ``contest_bot`` is not a uv-workspace member so we splice
# its parent onto sys.path explicitly.
_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from gecko_wrap import (  # noqa: E402
    ArtifactLogger,
    GeckoGate,
    HourlyCircuitBreaker,
)


# ── Helpers ────────────────────────────────────────────────────────────
def _b64_challenge(accepts: list[dict[str, Any]]) -> str:
    return base64.b64encode(
        json.dumps({"x402Version": 2, "accepts": accepts}).encode("utf-8")
    ).decode("ascii")


def _make_gate_with_handler(handler: Any, **gate_kwargs: Any) -> GeckoGate:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return GeckoGate(http_client=client, **gate_kwargs)


_DEFAULT_ACCEPTS = [
    {
        "scheme": "exact",
        "network": "solana",
        "payTo": "addr",
        "asset": "USDC",
        "maxAmountRequired": "10000",
        "resource": "/trade_research",
    }
]


# ── GeckoGate ──────────────────────────────────────────────────────────
def test_gate_does_402_then_paid_dance_and_allows_high_conf_act() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        # First call → 402 with challenge header.
        if len(calls) == 1:
            assert "PAYMENT-SIGNATURE" not in request.headers
            return httpx.Response(
                402,
                headers={"payment-required": _b64_challenge(_DEFAULT_ACCEPTS)},
                json={},
            )
        # Second call → paid, must carry both headers.
        assert request.headers.get("PAYMENT-SIGNATURE")
        assert request.headers.get("X-PAYMENT")
        # Verify stub payload shape.
        sig = request.headers["PAYMENT-SIGNATURE"]
        decoded = json.loads(base64.b64decode(sig).decode())
        assert decoded["x402Version"] == 2
        assert decoded["payload"] == {"signature": "stub-sig", "transaction": "stub-tx"}
        assert decoded["accepted"] == _DEFAULT_ACCEPTS[0]
        return httpx.Response(
            200,
            json={
                "verdict": "act",
                "confidence": 0.82,
                "key_drivers": ["uptrend confirmed", "vol stable"],
                "evidence_citations": [{"id": 1}, {"id": 2}],
            },
        )

    gate = _make_gate_with_handler(handler)
    decision = asyncio.run(gate.check_entry("JTO", {"spot_price": 0.4127, "change_24h_pct": -1.23}))
    assert len(calls) == 2
    assert decision.allow is True
    assert decision.verdict == "act"
    assert decision.confidence == pytest.approx(0.82)
    assert decision.citations_count == 2
    assert decision.key_drivers == ["uptrend confirmed", "vol stable"]
    gate.close()


def test_gate_blocks_when_verdict_not_act() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" not in request.headers:
            return httpx.Response(
                402,
                headers={"payment-required": _b64_challenge(_DEFAULT_ACCEPTS)},
            )
        return httpx.Response(200, json={"verdict": "defer", "confidence": 0.9})

    gate = _make_gate_with_handler(handler)
    decision = asyncio.run(gate.check_entry("JTO", {"spot_price": 0.4}))
    assert decision.allow is False
    assert decision.verdict == "defer"
    gate.close()


def test_gate_blocks_when_confidence_below_threshold() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" not in request.headers:
            return httpx.Response(
                402,
                headers={"payment-required": _b64_challenge(_DEFAULT_ACCEPTS)},
            )
        return httpx.Response(200, json={"verdict": "act", "confidence": 0.55})

    gate = _make_gate_with_handler(handler)
    decision = asyncio.run(gate.check_entry("JTO", {"spot_price": 0.4}))
    assert decision.allow is False
    assert decision.verdict == "act"
    gate.close()


def test_gate_blocks_on_non_200_paid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" not in request.headers:
            return httpx.Response(
                402,
                headers={"payment-required": _b64_challenge(_DEFAULT_ACCEPTS)},
            )
        return httpx.Response(500, text="oops")

    gate = _make_gate_with_handler(handler)
    decision = asyncio.run(gate.check_entry("JTO", {"spot_price": 0.4}))
    assert decision.allow is False
    assert decision.verdict == "error"
    assert decision.error and "500" in decision.error
    gate.close()


def test_gate_blocks_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network down")

    gate = _make_gate_with_handler(handler)
    decision = asyncio.run(gate.check_entry("JTO", {"spot_price": 0.4}))
    assert decision.allow is False
    assert decision.verdict == "error"
    gate.close()


def test_gate_caches_identical_market_state() -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if "PAYMENT-SIGNATURE" not in request.headers:
            return httpx.Response(
                402,
                headers={"payment-required": _b64_challenge(_DEFAULT_ACCEPTS)},
            )
        return httpx.Response(200, json={"verdict": "act", "confidence": 0.75})

    gate = _make_gate_with_handler(handler)
    state = {"spot_price": 0.4127, "change_24h_pct": -1.23, "range_24h_pct": 6.91}
    d1 = asyncio.run(gate.check_entry("JTO", state))
    d2 = asyncio.run(gate.check_entry("JTO", state))
    # The handler does 2 HTTP calls per dance; only ONE dance should happen.
    assert call_count["n"] == 2
    assert d1.allow is True
    assert d2.allow is True
    assert d2.cached is True
    assert d1.cached is False
    gate.close()


def test_gate_rejects_live_mode_in_v1() -> None:
    with pytest.raises(ValueError, match="stub_mode"):
        GeckoGate(stub_mode=False)


# ── HourlyCircuitBreaker ───────────────────────────────────────────────
def test_breaker_pauses_when_rolling_pnl_below_threshold(tmp_path: Path) -> None:
    state = tmp_path / "br.json"
    cb = HourlyCircuitBreaker(state_path=state)
    now = time.time()
    # Three losses sum to -$3.5 within the rolling window.
    cb.record_pnl_delta(-1.0, ts=now - 30)
    cb.record_pnl_delta(-1.0, ts=now - 20)
    paused, _ = cb.check()
    assert paused is False
    cb.record_pnl_delta(-1.5, ts=now - 10)
    paused, reason = cb.check()
    assert paused is True
    assert "circuit_breaker" in reason


def test_breaker_does_not_pause_on_old_losses_outside_window(tmp_path: Path) -> None:
    state = tmp_path / "br.json"
    cb = HourlyCircuitBreaker(state_path=state)
    now = time.time()
    # Losses are 2h old → outside the 60m window → should NOT trip.
    cb.record_pnl_delta(-5.0, ts=now - 7200)
    cb.record_pnl_delta(-5.0, ts=now - 7100)
    paused, _ = cb.check()
    assert paused is False


def test_breaker_persists_across_instances(tmp_path: Path) -> None:
    state = tmp_path / "br.json"
    cb1 = HourlyCircuitBreaker(state_path=state)
    now = time.time()
    cb1.record_pnl_delta(-2.0, ts=now)
    cb1.record_pnl_delta(-2.0, ts=now)  # cumulative -4 → trips
    paused1, _ = cb1.check()
    assert paused1 is True

    # Fresh instance reading the same file.
    cb2 = HourlyCircuitBreaker(state_path=state)
    paused2, _ = cb2.check()
    assert paused2 is True
    assert cb2.cumulative_pnl() == pytest.approx(-4.0)


# ── ArtifactLogger ─────────────────────────────────────────────────────
def test_artifact_logger_appends_and_is_immutable(tmp_path: Path) -> None:
    al = ArtifactLogger(directory=tmp_path)
    rid1 = al.log("gate_call", {"instrument": "JTO"})
    rid2 = al.log("position_open", {"price": 0.41}, decision_id=rid1)
    al.patch_outcome(rid1, {"pnl_usd": 1.23})

    path = al.current_path
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) == 3
    assert rows[0]["kind"] == "gate_call"
    assert rows[0]["decision_id"] == rid1
    assert rows[1]["decision_id"] == rid1  # caller passed the same id
    assert rows[2]["kind"] == "outcome_patch"
    assert rows[2]["payload"]["references"] == rid1

    # Re-open and append; assert prior rows untouched.
    al2 = ArtifactLogger(directory=tmp_path)
    al2.log("breaker_trip", {"reason": "test"})
    rows_after = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows_after) == 4
    assert rows_after[:3] == rows  # no rewrite of earlier rows
    assert rid2  # silence unused-var lint


# ── Integration ────────────────────────────────────────────────────────
def test_integration_decision_logged_breaker_consulted_gate_called(
    tmp_path: Path,
) -> None:
    """One simulated market tick: gate is called, decision is logged,
    breaker is consulted before any swap fires."""
    gate_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" not in request.headers:
            return httpx.Response(
                402,
                headers={"payment-required": _b64_challenge(_DEFAULT_ACCEPTS)},
            )
        gate_calls.append("paid")
        return httpx.Response(200, json={"verdict": "act", "confidence": 0.81})

    gate = _make_gate_with_handler(handler)
    breaker = HourlyCircuitBreaker(state_path=tmp_path / "br.json")
    logger = ArtifactLogger(directory=tmp_path)

    swap_fired: list[str] = []

    def fake_swap_execute(token: str, usd: float) -> None:
        swap_fired.append(token)

    # ── Simulated _attempt_entry ─────────────────────────────────────
    market_state = {"spot_price": 0.4127, "change_24h_pct": -1.23, "range_24h_pct": 6.91}
    paused, reason = breaker.check()
    logger.log("breaker_check", {"paused": paused, "reason": reason})
    assert paused is False

    decision = asyncio.run(gate.check_entry("JTO", market_state))
    logger.log(
        "gate_allow" if decision.allow else "gate_block",
        {
            "instrument": "JTO",
            "verdict": decision.verdict,
            "confidence": decision.confidence,
            "citations_count": decision.citations_count,
        },
        decision_id=decision.decision_id,
    )
    if decision.allow:
        fake_swap_execute("JTO", 25.0)
        logger.log("position_open", {"token": "JTO", "usd": 25.0}, decision_id=decision.decision_id)

    # ── Assertions ────────────────────────────────────────────────────
    assert gate_calls == ["paid"]
    assert swap_fired == ["JTO"]

    rows = [
        json.loads(line) for line in logger.current_path.read_text().splitlines() if line.strip()
    ]
    kinds = [r["kind"] for r in rows]
    assert kinds == ["breaker_check", "gate_allow", "position_open"]
    gate.close()
