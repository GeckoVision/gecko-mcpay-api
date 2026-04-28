"""Tests for `gecko-mcp doctor`.

The doctor is the canary for a clean Phase 8 install — these tests pin its
behaviour (exit codes, redaction, named-missing-vars) because the install
docs in `gecko-mcpay-skills` script around them.
"""

from __future__ import annotations

from typing import Any

import pytest
from gecko_mcp.doctor import (
    REQUIRED_ENV_VARS,
    REQUIRED_EXTENSIONS,
    REQUIRED_FUNCTIONS,
    REQUIRED_TABLES,
    run_doctor,
)


class _FakeSupabase:
    """Stand-in supabase client. Returns a manifest dict from `rpc`."""

    def __init__(self, manifest: dict[str, list[str]]) -> None:
        self._manifest = manifest

    def rpc(self, fn: str, params: dict[str, object]) -> Any:
        if fn == "gecko_doctor_ping":
            return {"ok": True}
        if fn == "gecko_doctor_manifest":
            return self._manifest
        raise RuntimeError(f"unexpected rpc: {fn}")


def test_doctor_fails_when_all_env_missing() -> None:
    exit_code, report = run_doctor(environ={}, supabase_client=None)
    assert exit_code == 1
    assert "doctor: FAIL" in report
    for var in REQUIRED_ENV_VARS:
        assert var in report, f"doctor must name the missing var {var}"


def test_doctor_redacts_secrets_in_report() -> None:
    # Sanity: even on FAIL, no value of a present var should be echoed.
    env = {
        "SUPABASE_URL": "https://x.supabase.co",
        # missing the rest
    }
    _, report = run_doctor(environ=env, supabase_client=None)
    assert "https://x.supabase.co" not in report  # only the var name should appear
    assert "SUPABASE_URL" in report  # confirms we mention it without the value


def test_doctor_x402_default_stub_is_ok() -> None:
    env = {var: "x" for var in REQUIRED_ENV_VARS}
    manifest = {
        "extensions": list(REQUIRED_EXTENSIONS),
        "tables": list(REQUIRED_TABLES),
        "functions": list(REQUIRED_FUNCTIONS),
    }
    exit_code, report = run_doctor(environ=env, supabase_client=_FakeSupabase(manifest))
    assert exit_code == 0, report
    assert "doctor: OK" in report
    assert "defaulting to 'stub'" in report


def test_doctor_x402_invalid_value_fails() -> None:
    env = {var: "x" for var in REQUIRED_ENV_VARS} | {"X402_MODE": "bogus"}
    exit_code, report = run_doctor(environ=env, supabase_client=_FakeSupabase({}))
    assert exit_code == 1
    assert "X402_MODE" in report


def test_doctor_passes_with_full_env_and_migrations() -> None:
    env = {var: "x" for var in REQUIRED_ENV_VARS} | {"X402_MODE": "stub"}
    manifest = {
        "extensions": list(REQUIRED_EXTENSIONS),
        "tables": list(REQUIRED_TABLES),
        "functions": list(REQUIRED_FUNCTIONS),
    }
    exit_code, report = run_doctor(environ=env, supabase_client=_FakeSupabase(manifest))
    assert exit_code == 0, report
    assert "doctor: OK" in report
    for tbl in REQUIRED_TABLES:
        assert tbl in report


def test_doctor_fails_when_migrations_missing() -> None:
    env = {var: "x" for var in REQUIRED_ENV_VARS} | {"X402_MODE": "stub"}
    manifest: dict[str, list[str]] = {"extensions": [], "tables": [], "functions": []}
    exit_code, report = run_doctor(environ=env, supabase_client=_FakeSupabase(manifest))
    assert exit_code == 1
    for tbl in REQUIRED_TABLES:
        assert f"missing table: {tbl}" in report
    for ext in REQUIRED_EXTENSIONS:
        assert f"missing extension: {ext}" in report
    for fn in REQUIRED_FUNCTIONS:
        assert f"missing function: {fn}" in report


def test_doctor_gecko_api_unset_is_info_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from gecko_mcp.doctor import check_gecko_api

    result = check_gecko_api(environ={})
    assert result.ok is True
    assert result.info is True
    assert "unset" in result.detail


def test_doctor_gecko_api_unreachable_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from gecko_mcp.doctor import check_gecko_api

    def _raise(*_args: object, **_kwargs: object) -> object:
        raise ConnectionError("nope")

    monkeypatch.setattr("httpx.get", _raise)
    result = check_gecko_api(environ={"GECKO_API_URL": "http://127.0.0.1:1"})
    assert result.ok is False
    assert "unreachable" in result.detail


def test_doctor_gecko_api_reachable_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from gecko_mcp.doctor import check_gecko_api

    def _ok(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr("httpx.get", _ok)
    result = check_gecko_api(environ={"GECKO_API_URL": "http://localhost:8000"})
    assert result.ok is True
    assert result.info is False
    assert "reachable" in result.detail


def test_doctor_cli_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: invoking the Click command with no env returns non-zero."""
    from click.testing import CliRunner
    from gecko_mcp.cli import main

    for var in REQUIRED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("X402_MODE", raising=False)
    # Don't auto-load ~/.gecko/.env during the test.
    monkeypatch.setattr("gecko_mcp.cli._load_env", lambda _: None)

    runner = CliRunner()
    result = runner.invoke(main, ["doctor"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "doctor: FAIL" in result.output
