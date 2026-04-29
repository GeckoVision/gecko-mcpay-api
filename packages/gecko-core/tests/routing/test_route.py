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
    monkeypatch: pytest.MonkeyPatch,
    *,
    content: str,
    t_in: int,
    t_out: int,
    usage_cost_usd: float | None = None,
    upstream_cost_usd: float | None = None,
    model_used: str | None = None,
) -> None:
    """Replace `_call_model` so no AsyncOpenAI client is constructed."""
    from gecko_core import routing as routing_mod
    from gecko_core.routing import _CallOutcome

    async def _fake(*, model: str, prompt: str, fallback_model: str | None = None) -> _CallOutcome:
        del prompt, fallback_model
        return _CallOutcome(
            text=content,
            tokens_in=t_in,
            tokens_out=t_out,
            usage_cost_usd=usage_cost_usd,
            upstream_cost_usd=upstream_cost_usd,
            model_used=model_used or model,
        )

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


# ---------------------------------------------------------------------------
# S4-ROUTE-01 — surface OpenRouter `usage.cost` truth + drift warning
# ---------------------------------------------------------------------------


async def test_route_surfaces_usage_cost_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_call_model(
        monkeypatch,
        content="x",
        t_in=100,
        t_out=100,
        usage_cost_usd=0.0123,
        upstream_cost_usd=0.0091,
    )
    _patch_charge(monkeypatch)

    result = await route("hello", task_hint="default")
    assert result.usage_cost_usd == pytest.approx(0.0123)
    assert result.upstream_cost_usd == pytest.approx(0.0091)


async def test_route_usage_cost_none_for_direct_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `usage.cost` on the upstream response → field is None, no error."""
    _patch_call_model(monkeypatch, content="x", t_in=100, t_out=100)
    _patch_charge(monkeypatch)

    result = await route("hello", task_hint="default")
    assert result.usage_cost_usd is None
    assert result.upstream_cost_usd is None


async def test_route_warns_on_cost_drift(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 10x drift between estimate and truth fires the WARNING log."""
    import logging

    # Force a large truth-vs-estimate gap. Estimate is computed from token
    # counts; with t_in=100, t_out=100 on gpt-4o-mini estimate is ~$0.000075.
    # Setting truth to $0.05 makes the drift enormous (>>10%).
    _patch_call_model(
        monkeypatch,
        content="x",
        t_in=100,
        t_out=100,
        usage_cost_usd=0.05,
    )
    _patch_charge(monkeypatch)

    caplog.set_level(logging.WARNING, logger="gecko_core.routing")
    await route("hello", task_hint="default")
    assert any(
        "cost drift" in rec.message and rec.levelno == logging.WARNING for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# S4-ROUTE-03 — cross-provider fallback chain
# ---------------------------------------------------------------------------


async def test_route_falls_back_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """Primary 429 → one retry on the fallback model; result reflects success."""
    from gecko_core import routing as routing_mod
    from gecko_core.routing import _CallOutcome

    calls: list[str] = []

    class _FakeStatusError(Exception):
        status_code = 429

    async def _fake(*, model: str, prompt: str, fallback_model: str | None = None) -> _CallOutcome:
        del prompt, fallback_model
        calls.append(model)
        if len(calls) == 1:
            raise _FakeStatusError("upstream rate-limited")
        return _CallOutcome(
            text="ok",
            tokens_in=10,
            tokens_out=10,
            usage_cost_usd=None,
            upstream_cost_usd=None,
            model_used=model,
        )

    monkeypatch.setattr(routing_mod, "_call_model", _fake)
    _patch_charge(monkeypatch)

    result = await route("hello", task_hint="default", prefer_premium=False)
    # gpt-4o-mini is preferred; gpt-4o is the alternative tier candidate.
    assert calls == ["gpt-4o-mini", "gpt-4o"]
    assert result.model_requested == "gpt-4o-mini"
    assert result.model_used == "gpt-4o"


async def test_route_surfaces_model_used_when_router_swaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenRouter's server-side fallback returns a different `response.model`."""
    _patch_call_model(
        monkeypatch,
        content="x",
        t_in=10,
        t_out=10,
        model_used="anthropic/claude-haiku-4.5",
    )
    _patch_charge(monkeypatch)

    result = await route("hello", task_hint="default")
    assert result.model_requested == "gpt-4o-mini"
    assert result.model_used == "anthropic/claude-haiku-4.5"


async def test_route_fails_cleanly_when_both_models_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primary + fallback both 5xx — surface the second error, no infinite retry."""
    from gecko_core import routing as routing_mod

    calls: list[str] = []

    class _FakeStatusError(Exception):
        status_code = 503

    async def _fake(*, model: str, prompt: str, fallback_model: str | None = None) -> object:
        del prompt, fallback_model
        calls.append(model)
        raise _FakeStatusError(f"down: {model}")

    monkeypatch.setattr(routing_mod, "_call_model", _fake)
    _patch_charge(monkeypatch)

    with pytest.raises(_FakeStatusError):
        await route("hello", task_hint="default")
    # Exactly two attempts: primary + one fallback. No further retries.
    assert len(calls) == 2


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
