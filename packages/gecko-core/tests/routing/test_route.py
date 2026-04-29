"""Tests for `gecko_core.routing.route` end-to-end (S3-05).

Mocks the OpenAI client + x402 stub. No network calls.
"""

from __future__ import annotations

from typing import Any

import pytest
from gecko_core.payments.models import PaymentResult
from gecko_core.routing import RoutePaymentError, route
from gecko_core.routing.models import RouteResult


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


def _patch_call_model(
    monkeypatch: pytest.MonkeyPatch, *, content: str, t_in: int, t_out: int
) -> None:
    """Replace `_call_model` so no AsyncOpenAI client is constructed."""
    from gecko_core import routing as routing_mod

    async def _fake(*, model: str, prompt: str) -> tuple[str, int, int]:
        del model, prompt
        return content, t_in, t_out

    monkeypatch.setattr(routing_mod, "_call_model", _fake)


def _patch_charge(monkeypatch: pytest.MonkeyPatch, *, status: str = "success") -> dict[str, Any]:
    """Replace `get_client` with a recorder so we can assert charge() was hit."""
    from gecko_core import routing as routing_mod

    seen: dict[str, Any] = {}

    class _RecordingClient:
        async def charge(self, intent: Any) -> PaymentResult:
            seen["intent"] = intent
            return PaymentResult(
                intent_id=intent.intent_id,
                status=status,  # type: ignore[arg-type]
                tx_signature=None,
                error=None if status == "success" else "stub-fail",
            )

    monkeypatch.setattr(routing_mod, "get_client", lambda: _RecordingClient())
    return seen


async def test_route_returns_route_result_with_savings(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call_model(monkeypatch, content="hello", t_in=500, t_out=500)
    seen = _patch_charge(monkeypatch)

    result = await route("write a haiku about gas fees", task_hint="default")

    assert isinstance(result, RouteResult)
    assert result.response == "hello"
    assert result.model_used == "gpt-4o-mini"
    assert result.tokens_in == 500
    assert result.tokens_out == 500
    assert result.cost_usd > 0.0
    # default-tier (gpt-4o-mini) vs premium (gpt-4o) — premium is more
    # expensive so savings must be strictly positive.
    assert result.savings_vs_premium > 0.0
    # x402 was charged with the estimated cost.
    assert "intent" in seen
    assert seen["intent"].tier == "basic"


async def test_route_premium_path_picks_premium_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call_model(monkeypatch, content="x", t_in=10, t_out=10)
    _patch_charge(monkeypatch)

    result = await route("refactor this", task_hint="code", prefer_premium=True)
    assert result.model_used == "claude-opus-4-7"
    # When the premium tier IS chosen, savings vs the same premium tier is 0.
    assert result.savings_vs_premium == pytest.approx(0.0)


async def test_route_charge_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call_model(monkeypatch, content="x", t_in=10, t_out=10)
    _patch_charge(monkeypatch, status="failed")

    with pytest.raises(RoutePaymentError):
        await route("anything", task_hint="default")


async def test_route_downshifts_under_tight_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even with prefer_premium, a tight budget forces the cheap candidate.
    _patch_call_model(monkeypatch, content="x", t_in=10_000, t_out=10_000)
    _patch_charge(monkeypatch)

    result = await route(
        "x" * 40_000,
        task_hint="default",
        prefer_premium=True,
        max_cost_usd=0.02,
    )
    assert result.model_used == "gpt-4o-mini"


async def test_route_emits_demo_log_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GECKO_ROUTE_LOG", "1")
    _patch_call_model(monkeypatch, content="x", t_in=100, t_out=100)
    _patch_charge(monkeypatch)

    await route("hello", task_hint="code")
    captured = capsys.readouterr()
    assert "[gecko_route]" in captured.out
    assert "task=code" in captured.out
    assert "saved $" in captured.out
