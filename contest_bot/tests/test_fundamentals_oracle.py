"""Tests for FundamentalsOracle.

Light fakes only — no live network, no slow loops. Uses
``httpx.MockTransport`` to drive the x402 stub-payment dance.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

# Make the contest_bot package importable when pytest runs from the repo root.
_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from fundamentals_oracle import (  # noqa: E402
    DEFAULT_TIMEOUT_S,
    DEFAULT_TTL_S,
    FundamentalsOracle,
    FundamentalsVerdict,
)

# ── Helpers ────────────────────────────────────────────────────────────
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


def _b64_challenge(accepts: list[dict[str, Any]]) -> str:
    return base64.b64encode(
        json.dumps({"x402Version": 2, "accepts": accepts}).encode("utf-8")
    ).decode("ascii")


def _envelope(
    verdict: str = "defer",
    confidence: float = 0.55,
    drivers: list[str] | None = None,
    citations: int = 3,
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "confidence": confidence,
        "key_drivers": drivers or ["fundamentals_solid", "macro_neutral"],
        "blocker_questions": ["TVL trajectory in next 24h?"],
        "evidence_citations": [{"id": f"c{i}"} for i in range(citations)],
    }


def _make_oracle(handler: Any, **kwargs: Any) -> FundamentalsOracle:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return FundamentalsOracle(http_client=client, **kwargs)


_INSTRUMENTS_8 = [
    {"symbol": "JTO"},
    {"symbol": "JUP"},
    {"symbol": "PYTH"},
    {"symbol": "RAY"},
    {"symbol": "ORCA"},
    {"symbol": "BONK"},
    {"symbol": "WIF"},
    {"symbol": "HNT"},
]


# ── stub_mode contract ────────────────────────────────────────────────
def test_oracle_rejects_live_mode() -> None:
    with pytest.raises(ValueError, match="stub_mode=True"):
        FundamentalsOracle(stub_mode=False)


# ── 402 → paid dance + parsing ────────────────────────────────────────
def test_preload_runs_402_then_paid_dance_and_caches_all() -> None:
    call_counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        proto = body["protocol"]
        call_counts[proto] = call_counts.get(proto, 0) + 1
        if call_counts[proto] == 1:
            assert "PAYMENT-SIGNATURE" not in request.headers
            return httpx.Response(
                402,
                headers={"payment-required": _b64_challenge(_DEFAULT_ACCEPTS)},
                json={},
            )
        # Paid retry — both headers present, stub payload.
        assert request.headers.get("PAYMENT-SIGNATURE")
        assert request.headers.get("X-PAYMENT")
        sig = request.headers["PAYMENT-SIGNATURE"]
        decoded = json.loads(base64.b64decode(sig).decode())
        assert decoded["payload"] == {
            "signature": "stub-sig",
            "transaction": "stub-tx",
        }
        return httpx.Response(200, json=_envelope())

    oracle = _make_oracle(handler)
    result = asyncio.run(oracle.preload_for_instruments(_INSTRUMENTS_8))
    asyncio.run(oracle.close())

    assert set(result.keys()) == {i["symbol"] for i in _INSTRUMENTS_8}
    for v in result.values():
        assert isinstance(v, FundamentalsVerdict)
        assert v.verdict in ("act", "pass", "defer")
        assert v.citations_count == 3
        assert v.key_drivers
        assert v.blocker_questions
    # Each instrument: one 402 + one 200 = 2 calls.
    assert all(c == 2 for c in call_counts.values())


def test_preload_runs_in_parallel_not_sequential() -> None:
    """If gather were sequential the per-call delays would sum. We
    assert the wall-clock is closer to one call's delay than 8x."""
    call_started: list[float] = []

    async def handler_async(request: httpx.Request) -> httpx.Response:
        call_started.append(asyncio.get_event_loop().time())
        # First call returns 402.
        if "PAYMENT-SIGNATURE" not in request.headers:
            return httpx.Response(
                402,
                headers={"payment-required": _b64_challenge(_DEFAULT_ACCEPTS)},
                json={},
            )
        # Simulate panel latency.
        await asyncio.sleep(0.05)
        return httpx.Response(200, json=_envelope())

    transport = httpx.MockTransport(handler_async)
    client = httpx.AsyncClient(transport=transport)
    oracle = FundamentalsOracle(http_client=client)

    async def run() -> tuple[float, dict[str, FundamentalsVerdict]]:
        t0 = asyncio.get_event_loop().time()
        res = await oracle.preload_for_instruments(_INSTRUMENTS_8)
        t1 = asyncio.get_event_loop().time()
        await oracle.close()
        return (t1 - t0), res

    elapsed, result = asyncio.run(run())
    assert len(result) == 8
    # Sequential lower bound would be 8 * 0.05 = 0.4s. Parallel should
    # be well under that — typically <0.15s. Be generous to CI noise.
    assert elapsed < 0.35, f"preload ran sequentially: {elapsed:.3f}s"


# ── Cache lookup semantics ────────────────────────────────────────────
def test_get_for_instrument_cold_cache_is_none() -> None:
    oracle = FundamentalsOracle()
    assert oracle.get_for_instrument("JTO") is None
    asyncio.run(oracle.close())


def test_get_for_instrument_returns_fresh_then_expires() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        # Single-shot 200 (skip the 402 path) for speed.
        return httpx.Response(200, json=_envelope(verdict="act", confidence=0.7))

    oracle = _make_oracle(handler, ttl_seconds=DEFAULT_TTL_S)
    asyncio.run(oracle.preload_for_instruments([{"symbol": "JTO"}]))
    fresh = oracle.get_for_instrument("JTO")
    assert fresh is not None
    assert fresh.verdict == "act"
    assert fresh.confidence == 0.7

    # Synthesize TTL expiry by backdating the cached entry.
    fresh_backdated = fresh.model_copy(
        update={"ts": datetime.now(UTC) - timedelta(seconds=DEFAULT_TTL_S + 60)}
    )
    oracle._cache["JTO"] = fresh_backdated  # type: ignore[attr-defined]
    assert oracle.get_for_instrument("JTO") is None
    asyncio.run(oracle.close())


# ── refresh_if_stale ──────────────────────────────────────────────────
def test_refresh_if_stale_fires_when_stale_skips_when_fresh() -> None:
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_envelope(verdict="pass", confidence=0.4))

    oracle = _make_oracle(handler)
    # Cold → fires.
    v1 = asyncio.run(oracle.refresh_if_stale("RAY", "ray"))
    assert v1 is not None
    assert len(calls) == 1
    # Fresh → no call.
    v2 = asyncio.run(oracle.refresh_if_stale("RAY", "ray"))
    assert v2 is not None
    assert len(calls) == 1
    # Backdate → stale → fires again.
    oracle._cache["RAY"] = v1.model_copy(  # type: ignore[attr-defined]
        update={"ts": datetime.now(UTC) - timedelta(seconds=DEFAULT_TTL_S + 60)}
    )
    v3 = asyncio.run(oracle.refresh_if_stale("RAY", "ray"))
    assert v3 is not None
    assert len(calls) == 2
    asyncio.run(oracle.close())


# ── Timeout / client config ───────────────────────────────────────────
def test_default_timeout_is_120s() -> None:
    """The whole point of this layer is to give PRD enough wall time."""
    oracle = FundamentalsOracle()
    # The client is lazily built; force construction.
    client = oracle._client()  # type: ignore[attr-defined]
    # httpx.AsyncClient stores timeout as Timeout; pull the read field.
    assert client.timeout.read == DEFAULT_TIMEOUT_S
    assert DEFAULT_TIMEOUT_S >= 120.0
    asyncio.run(oracle.close())


# ── Degraded-mode error path ──────────────────────────────────────────
def test_prd_500_yields_none_lookup_and_no_crash() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    oracle = _make_oracle(handler)
    result = asyncio.run(oracle.preload_for_instruments([{"symbol": "JTO"}]))
    # 500 → no verdict cached, no crash.
    assert result == {}
    assert oracle.get_for_instrument("JTO") is None
    asyncio.run(oracle.close())


def test_partial_failure_isolates_one_bad_instrument() -> None:
    """One 500 must not poison the batch."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        proto = body["protocol"]
        if proto == "bonk":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_envelope())

    oracle = _make_oracle(handler)
    result = asyncio.run(oracle.preload_for_instruments(_INSTRUMENTS_8))
    # 7 succeed, BONK is absent.
    assert "BONK" not in result
    assert len(result) == 7
    assert oracle.get_for_instrument("BONK") is None
    assert oracle.get_for_instrument("JTO") is not None
    asyncio.run(oracle.close())


# ── Idea prompt sanity ────────────────────────────────────────────────
def test_idea_prompt_disclaims_short_horizon_ta() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(200, json=_envelope())

    oracle = _make_oracle(handler)
    asyncio.run(oracle.preload_for_instruments([{"symbol": "JTO"}]))
    asyncio.run(oracle.close())
    assert captured
    idea = captured[0]["idea"]
    # The framing MUST tell the panel not to grade short-horizon TA.
    assert "NOT to grade" in idea or "NOT grade" in idea or "not grade" in idea.lower()
    assert "fundamentals" in idea.lower()
    assert "regime" in idea.lower()
    assert "risk" in idea.lower()
    assert captured[0]["vertical"] == "dex"
