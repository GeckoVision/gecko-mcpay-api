"""Tests for `bb research` scripted-run flags (`--yes`, `--non-interactive`).

These verify that the CLI never blocks on a Rich `Confirm.ask` prompt when
either bypass is set — without relying on a TTY or piped stdin. We monkeypatch
`gecko_core.research` directly so the test is hermetic (no Supabase, no
network, no LLM).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from click.testing import CliRunner


def _fake_result() -> Any:
    from gecko_core.models import ResearchResult

    return ResearchResult.model_validate(
        {
            "session_id": "11111111-1111-1111-1111-111111111111",
            "tier": "basic",
            "business_plan": {
                "problem": "p",
                "icp": "i",
                "solution": "s",
                "market": "m",
                "business_model": "bm",
                "channels": "c",
                "risks": ["r1"],
                "citations": [],
            },
            "validation_report": {
                "market_size_signal": "msig",
                "competitor_analysis": "ca",
                "demand_evidence": "de",
                "risk_flags": [],
                "citations": [],
            },
            "prd": {
                "v1_scope": ["v1"],
                "v2_scope": [],
                "v3_scope": [],
                "acceptance_criteria": ["ac"],
                "non_functional": [],
                "success_metrics": [],
                "citations": [],
            },
            "sources": [
                {
                    "url": "https://example.com/a",
                    "type": "web",
                    "chunk_count": 3,
                    "indexed_at": datetime.now(UTC).isoformat(),
                }
            ],
        }
    )


@pytest.fixture
def patched_research(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch `gecko_core.research` and capture call kwargs."""
    captured: dict[str, Any] = {}

    async def _fake_research(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_result()

    import gecko_core
    from gecko_cli.commands import research as research_module

    monkeypatch.setattr(gecko_core, "research", _fake_research)
    monkeypatch.setattr(research_module.gecko_core, "research", _fake_research)
    # `bb research --project` may consult the local project file; force None.
    monkeypatch.setattr(research_module, "resolve_project_id", lambda *_a, **_k: None)
    return captured


def test_research_subcommand_yes_flag_does_not_hang(
    patched_research: dict[str, Any],
) -> None:
    """Per-command --yes flag is preserved (back-compat)."""
    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["research", "--idea", "scripted smoke", "--yes"],
        input="",  # no input piped: would hang if a prompt fired
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert patched_research["auto_approve"] is True
    assert patched_research["approval_callback"] is None


def test_research_top_level_yes_flag_propagates(
    patched_research: dict[str, Any],
) -> None:
    """Top-level `cli -y research --idea ...` should auto-approve."""
    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-y", "research", "--idea", "scripted smoke"],
        input="",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert patched_research["auto_approve"] is True
    assert patched_research["approval_callback"] is None


def test_research_non_interactive_implies_yes(
    patched_research: dict[str, Any],
) -> None:
    """--non-interactive auto-approves and never prompts."""
    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--non-interactive", "research", "--idea", "scripted smoke"],
        input="",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert patched_research["auto_approve"] is True
    assert patched_research["approval_callback"] is None


def test_default_behavior_unchanged(patched_research: dict[str, Any]) -> None:
    """Without flags, auto_approve is False and a callback is wired up."""
    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["research", "--idea", "scripted smoke"],
        input="",
        catch_exceptions=False,
    )
    # The fake `research()` doesn't actually invoke the callback, so this still
    # exits 0 — but we assert the wiring is intact for the real pipeline.
    assert result.exit_code == 0, result.output
    assert patched_research["auto_approve"] is False
    assert patched_research["approval_callback"] is not None


def test_non_interactive_blocks_destructive_default_false() -> None:
    """`_prompt.confirm(default=False)` errors fast under --non-interactive."""
    import click
    from gecko_cli._prompt import NonInteractiveError, confirm

    @click.group()
    @click.pass_context
    def root(ctx: click.Context) -> None:
        ctx.ensure_object(dict)
        ctx.obj["yes"] = True
        ctx.obj["non_interactive"] = True

    @root.command()
    def sub() -> None:
        try:
            confirm("really delete?", default=False)
        except NonInteractiveError as e:
            raise click.ClickException(str(e)) from e

    runner = CliRunner()
    result = runner.invoke(root, ["sub"])
    assert result.exit_code != 0
    assert "non-interactive" in result.output.lower()
