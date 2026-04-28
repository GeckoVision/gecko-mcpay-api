"""Tests for `gecko project` CLI subcommand group (Phase B5 v2).

v2 seam: ``project_module._client`` returns a ``GeckoAPIClient``. We mock
that client to avoid real HTTP. The CLI no longer imports SessionStore.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from click.testing import CliRunner
from gecko_cli.commands import project as project_module
from gecko_cli.main import cli


def _project_payload(name: str = "demo", budget: float | None = 5.0) -> dict[str, object]:
    """Mimic the dict shape returned by GeckoAPIClient.create_project / get_project."""
    return {
        "project_id": str(uuid4()),
        "name": name,
        "budget_usd": budget,
        "wallet_address": None,
        "wallet_provider": "frames-policy",
        "created_at": datetime.now(tz=UTC).isoformat(),
    }


def _make_fake_api(**methods: AsyncMock) -> MagicMock:
    """Build a MagicMock that supports `async with _client() as api: ...`."""
    fake_api = MagicMock()
    for k, v in methods.items():
        setattr(fake_api, k, v)
    fake_api.__aenter__ = AsyncMock(return_value=fake_api)
    fake_api.__aexit__ = AsyncMock(return_value=None)
    return fake_api


@pytest.fixture
def fake_agent_wallet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stub `~/.agentwallet/config.json` with a known username."""
    cfg = tmp_path / "agentwallet" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"username": "alice", "apiToken": "xxx"}))
    monkeypatch.setattr(project_module, "AGENT_WALLET_CONFIG", cfg)
    return cfg


@pytest.fixture
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_init_creates_local_project_file(fake_agent_wallet: Path, isolated_cwd: Path) -> None:
    payload = _project_payload(name="demo", budget=5.0)
    fake_api = _make_fake_api(create_project=AsyncMock(return_value=payload))

    runner = CliRunner()
    with patch.object(project_module, "_client", return_value=fake_api):
        result = runner.invoke(cli, ["project", "init", "demo", "--budget", "5.00"])

    assert result.exit_code == 0, result.output
    fake_api.create_project.assert_awaited_once()
    kwargs = fake_api.create_project.await_args.kwargs
    assert kwargs["name"] == "demo"
    assert kwargs["budget_usd"] == 5.0

    written = isolated_cwd / ".gecko" / "project.json"
    assert written.exists()
    data = json.loads(written.read_text())
    assert data["project_id"] == payload["project_id"]
    assert data["name"] == "demo"
    assert data["frames_username"] == "alice"
    assert data["wallet_address"] is None
    assert data["wallet_provider"] == "frames-policy"
    assert data["budget_usd"] == 5.0


def test_list_renders_projects(fake_agent_wallet: Path) -> None:
    rows = [
        {
            "project_id": str(uuid4()),
            "name": "alpha",
            "budget_usd": 10.0,
            "total_spent_usd": 2.5,
            "sessions_count": 3,
        },
        {
            "project_id": str(uuid4()),
            "name": "beta",
            "budget_usd": None,
            "total_spent_usd": 0.0,
            "sessions_count": 0,
        },
    ]
    fake_api = _make_fake_api(list_projects=AsyncMock(return_value=rows))

    runner = CliRunner()
    with patch.object(project_module, "_client", return_value=fake_api):
        result = runner.invoke(cli, ["project", "list"])

    assert result.exit_code == 0, result.output
    fake_api.list_projects.assert_awaited_once_with()
    assert "alpha" in result.output
    assert "beta" in result.output
    assert "$10.00" in result.output


def test_list_empty(fake_agent_wallet: Path) -> None:
    fake_api = _make_fake_api(list_projects=AsyncMock(return_value=[]))

    runner = CliRunner()
    with patch.object(project_module, "_client", return_value=fake_api):
        result = runner.invoke(cli, ["project", "list"])

    assert result.exit_code == 0
    assert "No projects yet" in result.output


def test_show_renders_record_and_sessions(fake_agent_wallet: Path) -> None:
    record = _project_payload(name="demo", budget=10.0)
    record["total_spent_usd"] = 1.25
    record["budget_remaining_usd"] = 8.75
    record["sessions"] = [
        {
            "id": "abcd1234-0000-0000-0000-000000000000",
            "idea": "build a thing",
            "status": "complete",
            "cost_total_usd": 0.42,
            "created_at": "2026-04-27T00:00:00Z",
        }
    ]
    fake_api = _make_fake_api(get_project=AsyncMock(return_value=record))

    runner = CliRunner()
    with patch.object(project_module, "_client", return_value=fake_api):
        result = runner.invoke(cli, ["project", "show", "demo"])

    assert result.exit_code == 0, result.output
    assert "demo" in result.output
    assert "build a thing" in result.output


def test_delete_calls_api(fake_agent_wallet: Path) -> None:
    fake_api = _make_fake_api(delete_project=AsyncMock(return_value=None))
    runner = CliRunner()
    with patch.object(project_module, "_client", return_value=fake_api):
        result = runner.invoke(cli, ["project", "delete", "demo", "--yes"])
    assert result.exit_code == 0, result.output
    fake_api.delete_project.assert_awaited_once_with("demo")
    assert "Deleted" in result.output


def test_resolve_project_id_from_local_config(isolated_cwd: Path) -> None:
    pid = uuid4()
    project_module.write_local_project(
        {
            "project_id": str(pid),
            "name": "demo",
            "frames_username": "alice",
            "wallet_address": None,
            "wallet_provider": "frames-policy",
            "budget_usd": 5.0,
            "created_at": datetime.now(tz=UTC).isoformat(),
        }
    )
    assert project_module.resolve_project_id() == pid


def test_resolve_project_id_explicit_uuid(isolated_cwd: Path) -> None:
    pid = uuid4()
    assert project_module.resolve_project_id(str(pid)) == pid


def test_resolve_project_id_none_when_no_config(isolated_cwd: Path) -> None:
    assert project_module.resolve_project_id() is None


def test_init_aborts_when_no_agent_wallet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_cwd: Path
) -> None:
    monkeypatch.setattr(project_module, "AGENT_WALLET_CONFIG", tmp_path / "missing.json")
    runner = CliRunner()
    result = runner.invoke(cli, ["project", "init", "demo", "--budget", "5.00"])
    assert result.exit_code == 1
    assert "frames.ag" in result.output
