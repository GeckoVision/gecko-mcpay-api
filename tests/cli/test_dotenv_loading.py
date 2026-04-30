"""S10-CLI-01 — universal `.env` loading on the `bb` entrypoint.

Covers F17: every subcommand (not just `bb doctor`) must inherit env vars
loaded from `.env`. The parent `cli` Click group handles this once via
`python-dotenv`'s `find_dotenv()` walk-up, with `override=False` so a
shell-exported value beats the file (the precedence contract).
"""

from __future__ import annotations

import os
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from gecko_cli.main import cli


def _strip_env(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


@cli.command("__probe__")
def _probe() -> None:
    """Test-only subcommand. Echoes a marker var so we can prove the
    parent `cli` group ran its loader before the callback fired."""
    val = os.environ.get("S10_PROBE_VAR", "<unset>")
    click.echo(f"S10_PROBE_VAR={val}")


def test_dotenv_loaded_from_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A `.env` in cwd is picked up before the subcommand callback runs."""
    _strip_env(monkeypatch, "S10_PROBE_VAR")
    (tmp_path / ".env").write_text("S10_PROBE_VAR=from-cwd\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["__probe__"])
    assert result.exit_code == 0, result.output
    assert "S10_PROBE_VAR=from-cwd" in result.output


def test_dotenv_loaded_from_parent_when_cwd_has_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`find_dotenv()` walks up — a parent `.env` wins when cwd has none."""
    _strip_env(monkeypatch, "S10_PROBE_VAR")
    (tmp_path / ".env").write_text("S10_PROBE_VAR=from-parent\n")
    child = tmp_path / "subdir"
    child.mkdir()
    monkeypatch.chdir(child)

    result = CliRunner().invoke(cli, ["__probe__"])
    assert result.exit_code == 0, result.output
    assert "S10_PROBE_VAR=from-parent" in result.output


def test_missing_dotenv_does_not_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No `.env` anywhere on the walk-up path → silent no-op, no crash."""
    _strip_env(monkeypatch, "S10_PROBE_VAR")
    # tmp_path is fresh; pytest's tmp_path roots are outside the repo
    # so find_dotenv won't find one. Force HOME away from any real
    # ~/.gecko/.env fallback.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["__probe__"])
    assert result.exit_code == 0, result.output
    assert "S10_PROBE_VAR=<unset>" in result.output


def test_shell_env_wins_over_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`override=False` — value already in os.environ is not clobbered."""
    monkeypatch.setenv("S10_PROBE_VAR", "from-shell")
    (tmp_path / ".env").write_text("S10_PROBE_VAR=from-file\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["__probe__"])
    assert result.exit_code == 0, result.output
    assert "S10_PROBE_VAR=from-shell" in result.output


def test_explicit_env_file_flag_loads_custom_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--env-file PATH` overrides the walk-up search."""
    _strip_env(monkeypatch, "S10_PROBE_VAR")
    custom = tmp_path / "custom.env"
    custom.write_text("S10_PROBE_VAR=from-explicit\n")
    # Put a different value in cwd to prove --env-file wins.
    (tmp_path / ".env").write_text("S10_PROBE_VAR=from-cwd\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["--env-file", str(custom), "__probe__"])
    assert result.exit_code == 0, result.output
    assert "S10_PROBE_VAR=from-explicit" in result.output


def test_subcommand_inherits_env_via_os_environ(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Vars set in the file are visible via `os.environ` inside the
    subcommand callback — i.e. anything that reads `os.environ` (every
    `gecko_core` settings module) inherits the file values without
    needing `source .env`."""
    _strip_env(monkeypatch, "S10_PROBE_VAR")
    custom = tmp_path / "ci.env"
    custom.write_text("S10_PROBE_VAR=ci-value\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["--env-file", str(custom), "__probe__"])
    assert result.exit_code == 0, result.output
    # Proof: the subcommand callback read the value from os.environ.
    assert "S10_PROBE_VAR=ci-value" in result.output
    # And after the run, the value remains set in this process — that's
    # what enables `bb plan <session>` to inherit it without sourcing.
    assert os.environ.get("S10_PROBE_VAR") == "ci-value"
