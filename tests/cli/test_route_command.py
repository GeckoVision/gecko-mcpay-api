"""Tests for `gecko route` CLI command (S3-05)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner
from gecko_cli.main import cli
from gecko_core.routing.models import RouteResult


def _make_result(model: str = "gpt-4o-mini") -> RouteResult:
    return RouteResult(
        response="hello world",
        model_used=model,
        cost_usd=0.0012,
        tokens_in=50,
        tokens_out=80,
        savings_vs_premium=0.0048,
    )


def test_route_command_prints_response_and_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    import gecko_core.routing as routing_mod

    captured: dict[str, object] = {}

    async def _fake(
        prompt: str,
        task_hint: str = "default",
        max_cost_usd: float = 0.05,
        prefer_premium: bool = False,
    ) -> RouteResult:
        captured["prompt"] = prompt
        captured["task_hint"] = task_hint
        captured["prefer_premium"] = prefer_premium
        captured["max_cost_usd"] = max_cost_usd
        return _make_result()

    monkeypatch.setattr(routing_mod, "route", _fake)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["route", "explain x402", "--task-hint", "summary", "--max-cost", "0.01"],
    )
    assert result.exit_code == 0, result.output
    assert "hello world" in result.output
    assert "gpt-4o-mini" in result.output
    assert "$0.0012" in result.output
    assert "$0.0048" in result.output
    assert captured["task_hint"] == "summary"
    assert captured["max_cost_usd"] == 0.01


def test_route_command_passes_prefer_premium(monkeypatch: pytest.MonkeyPatch) -> None:
    import gecko_core.routing as routing_mod

    captured: dict[str, object] = {}

    async def _fake(
        prompt: str,
        task_hint: str = "default",
        max_cost_usd: float = 0.05,
        prefer_premium: bool = False,
    ) -> RouteResult:
        captured["prefer_premium"] = prefer_premium
        return _make_result(model="claude-opus-4-7")

    monkeypatch.setattr(routing_mod, "route", _fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["route", "refactor this", "--prefer-premium"])
    assert result.exit_code == 0, result.output
    assert captured["prefer_premium"] is True
    assert "claude-opus-4-7" in result.output


def test_route_command_handles_budget_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import gecko_core.routing as routing_mod

    async def _fake(*_args: object, **_kwargs: object) -> RouteResult:
        raise routing_mod.RouteBudgetError("too tight")

    monkeypatch.setattr(routing_mod, "route", _fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["route", "x", "--max-cost", "0.0001"])
    assert result.exit_code == 2
    assert "budget exceeded" in result.output


def test_route_command_handles_payment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import gecko_core.routing as routing_mod

    async def _fake(*_args: object, **_kwargs: object) -> RouteResult:
        raise routing_mod.RoutePaymentError("x402 down")

    monkeypatch.setattr(routing_mod, "route", _fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["route", "x"])
    assert result.exit_code == 3
    assert "payment failed" in result.output
