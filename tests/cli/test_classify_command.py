"""Tests for `gecko classify` CLI command."""

from __future__ import annotations

import pytest
from click.testing import CliRunner
from gecko_cli.commands import classify as classify_module
from gecko_cli.main import cli


async def _fake_classify(idea: str, **_: object) -> tuple[list[str], dict[str, float]]:
    assert idea == "a defi yield aggregator"
    return (
        ["crypto", "defi"],
        {
            "crypto": 0.71,
            "defi": 0.65,
            "devtools": 0.30,
            "saas": 0.20,
            "regulated": 0.10,
            "hackathon-team": 0.04,
        },
    )


def test_classify_command_renders_table(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch where the command imports it (lazy import inside the function),
    # i.e. the gecko_core.classify symbol.
    import gecko_core.classify as classify_core

    monkeypatch.setattr(classify_core, "classify_idea_with_scores", _fake_classify)

    runner = CliRunner()
    result = runner.invoke(cli, ["classify", "a defi yield aggregator"])
    assert result.exit_code == 0, result.output
    assert "Idea classification" in result.output
    assert "crypto" in result.output
    assert "defi" in result.output
    # Selected categories are flagged in the table.
    assert "yes" in result.output
    # Score formatting is to 3dp.
    assert "0.710" in result.output
    assert "selected:" in result.output


def test_classify_command_handles_empty_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_match(idea: str, **_: object) -> tuple[list[str], dict[str, float]]:
        return [], {
            c: 0.10 for c in ("crypto", "defi", "devtools", "saas", "regulated", "hackathon-team")
        }

    import gecko_core.classify as classify_core

    monkeypatch.setattr(classify_core, "classify_idea_with_scores", _no_match)

    runner = CliRunner()
    result = runner.invoke(cli, ["classify", "an unknown idea"])
    assert result.exit_code == 0, result.output
    assert "(none)" in result.output


def test_classify_command_module_exposes_command() -> None:
    # Ensure the command registers under the expected name.
    assert classify_module.classify_cmd.name == "classify"
