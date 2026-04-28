"""Tests for the demo agent.

We don't make real network calls and we don't load a real wallet. Instead:
- `get_keypair_for_signing` is patched to return a fresh ephemeral keypair
- httpx is patched to use a MockTransport that simulates the API
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable

import httpx
import pytest
from click.testing import CliRunner
from gecko_demo_agent import main as demo_main
from solders.keypair import Keypair
from x402 import PaymentRequired
from x402.schemas import PaymentRequirements


def _payment_required_header(price_usdc_cents: int = 2000) -> str:
    """Build a base64-encoded PAYMENT-REQUIRED header (V2 spec).

    Pricing convention: USDC has 6 decimals → $20 = 20_000_000 base units.
    """
    amount = str(int(price_usdc_cents / 100 * 1_000_000))
    fee_payer = str(Keypair().pubkey())
    pr = PaymentRequired(
        x402_version=2,
        error="Payment Required",
        accepts=[
            PaymentRequirements(
                scheme="exact",
                network="solana-devnet",
                asset="4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
                amount=amount,
                pay_to=str(Keypair().pubkey()),
                max_timeout_seconds=60,
                # x402 SVM exact scheme requires feePayer in extra (the
                # facilitator's address that pays SOL gas on behalf of the
                # payer). The server middleware adds this from supportedKind.
                extra={"feePayer": fee_payer},
            )
        ],
    )
    return base64.b64encode(pr.model_dump_json(by_alias=True).encode()).decode()


def _patch_wallet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid touching ~/.gecko/wallet.json — use an ephemeral in-memory keypair."""
    monkeypatch.setattr(demo_main, "get_keypair_for_signing", lambda: Keypair())


def _patch_async_client(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Replace `httpx.AsyncClient` with one backed by a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def test_research_happy_path_402_then_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_wallet(monkeypatch)
    calls: list[httpx.Request] = []
    research_payload = {
        "session_id": "sess-123",
        "business_plan": {"summary": "test"},
        "validation_report": {},
        "prd": {},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "PAYMENT-SIGNATURE" in request.headers or "payment-signature" in request.headers:
            return httpx.Response(
                200,
                json=research_payload,
                headers={
                    "X-PAYMENT-RESPONSE": base64.b64encode(
                        json.dumps(
                            {"transaction": "stub-abc123", "network": "solana-devnet"}
                        ).encode()
                    ).decode(),
                },
            )
        return httpx.Response(
            402,
            json={},
            headers={"PAYMENT-REQUIRED": _payment_required_header()},
        )

    _patch_async_client(monkeypatch, handler)

    runner = CliRunner()
    result = runner.invoke(demo_main.cli, ["research", "a hotel guide for Brazil"])

    assert result.exit_code == 0, result.output
    assert "402 received" in result.output
    assert "Documents received." in result.output
    assert "sess-123" in result.output
    # stub-prefixed tx should be flagged, not turned into an explorer link
    assert "stub-abc123" in result.output
    assert "explorer.solana.com" not in result.output
    # exactly two POSTs: unauthenticated probe, then signed retry
    assert len(calls) == 2


def test_research_402_then_500_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_wallet(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" in request.headers or "payment-signature" in request.headers:
            return httpx.Response(500, text="facilitator exploded")
        return httpx.Response(
            402, json={}, headers={"PAYMENT-REQUIRED": _payment_required_header()}
        )

    _patch_async_client(monkeypatch, handler)

    runner = CliRunner()
    result = runner.invoke(demo_main.cli, ["research", "an idea worth ten thousand"])

    assert result.exit_code == 1
    assert "request failed" in result.output
    assert "HTTP 500" in result.output


def test_ask_command_prints_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_wallet(monkeypatch)
    answer_payload = {
        "answer": "the strongest validation signal is repeat demand",
        "citations": [{"source_id": "s1", "url": "https://example.com"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sessions/sess-123/ask"
        assert request.method == "POST"
        return httpx.Response(200, json=answer_payload)

    _patch_async_client(monkeypatch, handler)

    runner = CliRunner()
    result = runner.invoke(
        demo_main.cli, ["ask", "sess-123", "what's the strongest validation signal?"]
    )

    assert result.exit_code == 0, result.output
    assert "repeat demand" in result.output
    assert "example.com" in result.output
