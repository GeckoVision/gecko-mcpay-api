"""Recorded-fixture contract tests for :mod:`gecko_core.trade_agent.oracle_client`.

Pattern C (per CLAUDE.md "Recurring patterns"): every payment-touching
client ships with a recorded-fixture contract test that exercises the
real wire shapes — 402 challenge dance, payment-signature retry, and
the production verdict envelope — against an in-process
``httpx.MockTransport``. No real network I/O.

The one live-network smoke test is marked ``@pytest.mark.live`` so CI
skips it; an operator runs ``pytest -m live`` once after a deploy to
verify production answers a Kamino question.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from gecko_core.trade_agent.oracle_client import (
    GeckoOracleClient,
    OracleNotReachable,
    OraclePaymentRequired,
    OracleResponseInvalid,
    VerdictPayload,
)


def _encode_challenge(accepts: list[dict]) -> str:
    """Build a base64-encoded x402 v2 challenge for the
    ``payment-required`` response header."""
    return base64.b64encode(json.dumps({"x402Version": 2, "accepts": accepts}).encode()).decode()


def _verdict_body(*, with_backtest: bool = False) -> dict:
    """Production-shaped verdict envelope. Mirrors the assertions in
    ``gecko-mcpay-app/public/test.sh``."""
    body = {
        "verdict": "act",
        "confidence": 0.72,
        "citations": [
            {
                "id": "c1",
                "source": "kamino.fi",
                "url": "https://kamino.fi/lend",
                "chunk_id": "abc123",
                "provider_kind": "paysh_live",
                "freshness_tier": "live",
                "snippet": "Kamino USDC reserve current APY is 6.4%.",
            }
        ],
        "turns": [{"agent": "bull", "content": "..."}],
        "dissent_count": 1,
    }
    if with_backtest:
        body["backtest"] = {"sharpe": 1.2, "pnl_pct": 0.043}
    return body


def _basic_accepts() -> list[dict]:
    return [
        {
            "scheme": "exact",
            "network": "solana-mainnet",
            "payTo": "9xQeWv...",
            "asset": "EPjFW...USDC",
            "maxAmountRequired": "250000",
            "resource": "https://api.geckovision.tech/trade_research",
            "maxTimeoutSeconds": 60,
        }
    ]


# ---------------------------------------------------------------------------
# Fixture 1 — 402 challenge → stub retry → 200 verdict.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_402_then_stub_paid_retry_returns_verdict() -> None:
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.headers)))
        if "PAYMENT-SIGNATURE" in request.headers:
            return httpx.Response(200, json=_verdict_body())
        return httpx.Response(
            402,
            headers={"payment-required": _encode_challenge(_basic_accepts())},
            json={"error": "payment required"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GeckoOracleClient(
            api_base="https://api.geckovision.tech",
            x402_mode="stub",
            http_client=http,
        )
        verdict = await client.call(idea="kamino lend usdc", protocol="kamino", vertical="dex")

    assert isinstance(verdict, VerdictPayload)
    assert verdict.verdict == "act"
    assert verdict.confidence == 0.72
    assert len(verdict.citations) == 1
    assert verdict.citations[0].provider_kind == "paysh_live"
    # Two requests: probe + paid retry, both to /trade_research.
    assert [path for path, _ in seen] == ["/trade_research", "/trade_research"]
    # Second request must carry both PAYMENT-SIGNATURE and X-PAYMENT.
    _, paid_headers = seen[1]
    assert "payment-signature" in {k.lower() for k in paid_headers}
    assert "x-payment" in {k.lower() for k in paid_headers}


@pytest.mark.asyncio
async def test_pro_tier_hits_pro_path_and_carries_backtest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" in request.headers:
            return httpx.Response(200, json=_verdict_body(with_backtest=True))
        return httpx.Response(
            402,
            headers={"payment-required": _encode_challenge(_basic_accepts())},
            json={},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GeckoOracleClient(
            api_base="https://api.geckovision.tech",
            x402_mode="stub",
            http_client=http,
        )
        verdict = await client.call(
            idea="kamino lend usdc",
            protocol="kamino",
            tier="pro",
        )

    assert verdict.backtest is not None
    assert verdict.backtest["sharpe"] == 1.2


# ---------------------------------------------------------------------------
# Fixture 2 — scheme="upto" still builds stub payload (with warning).
# Issue #17: the deployed stub-mode server still accepts the payload, but
# the upto scheme is not signature-satisfiable in principle.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upto_scheme_still_builds_stub_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    accepts = [{**_basic_accepts()[0], "scheme": "upto"}]

    def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" in request.headers:
            return httpx.Response(200, json=_verdict_body())
        return httpx.Response(
            402,
            headers={"payment-required": _encode_challenge(accepts)},
            json={},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GeckoOracleClient(
            api_base="https://api.geckovision.tech",
            x402_mode="stub",
            http_client=http,
        )
        with caplog.at_level("WARNING", logger="gecko_core.trade_agent.oracle_client"):
            verdict = await client.call(idea="x", protocol="kamino")

    assert verdict.verdict == "act"
    assert any("upto" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Fixture 3 — 500 on probe → OracleNotReachable.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_500_probe_raises_not_reachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream blew up")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GeckoOracleClient(
            api_base="https://api.geckovision.tech",
            x402_mode="stub",
            http_client=http,
        )
        with pytest.raises(OracleNotReachable):
            await client.call(idea="x", protocol="kamino")


# ---------------------------------------------------------------------------
# Fixture 4 — 200 with malformed JSON → OracleResponseInvalid.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_verdict_raises_response_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" in request.headers:
            return httpx.Response(
                200,
                content=b"not json at all",
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            402,
            headers={"payment-required": _encode_challenge(_basic_accepts())},
            json={},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GeckoOracleClient(
            api_base="https://api.geckovision.tech",
            x402_mode="stub",
            http_client=http,
        )
        with pytest.raises(OracleResponseInvalid):
            await client.call(idea="x", protocol="kamino")


@pytest.mark.asyncio
async def test_200_with_shape_violation_raises_response_invalid() -> None:
    """``verdict`` not in {act,pass,defer} must fail validation."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" in request.headers:
            # confidence out of range + bad verdict literal
            return httpx.Response(200, json={"verdict": "maybe", "confidence": 1.7})
        return httpx.Response(
            402,
            headers={"payment-required": _encode_challenge(_basic_accepts())},
            json={},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GeckoOracleClient(
            api_base="https://api.geckovision.tech",
            x402_mode="stub",
            http_client=http,
        )
        with pytest.raises(OracleResponseInvalid):
            await client.call(idea="x", protocol="kamino")


# ---------------------------------------------------------------------------
# Live-mode guard: refuses to run, raises OraclePaymentRequired.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_mode_refuses_to_sign() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            headers={"payment-required": _encode_challenge(_basic_accepts())},
            json={},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GeckoOracleClient(
            api_base="https://api.geckovision.tech",
            x402_mode="live",
            http_client=http,
        )
        with pytest.raises(OraclePaymentRequired):
            await client.call(idea="x", protocol="kamino")


# ---------------------------------------------------------------------------
# Live smoke — production-validates-the-build assertion.
# Marked @pytest.mark.live so CI skips it; run with `pytest -m live`.
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_kamino_question_returns_citations() -> None:
    client = GeckoOracleClient(
        api_base="https://api.geckovision.tech",
        x402_mode="stub",
    )
    try:
        verdict = await client.call(
            idea=("Should a trader deposit USDC into the Kamino USDC reserve right now?"),
            protocol="kamino",
            vertical="dex",
        )
    finally:
        await client.aclose()

    assert verdict.verdict in {"act", "pass", "defer"}
    assert len(verdict.citations) >= 1
    provider_kinds = {c.provider_kind for c in verdict.citations if c.provider_kind}
    assert len(provider_kinds) >= 2, (
        f"expected citations to span >=2 provider_kinds, got {provider_kinds!r}"
    )
