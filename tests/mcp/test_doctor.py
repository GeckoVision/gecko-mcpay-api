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
    SERVER_SIDE_ENV_VARS,
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


# Sentinel key present in all "happy path" run_doctor tests.
# EMBED_PROVIDER defaults to voyage so VOYAGE_API_KEY must be set for exit_code 0.
_VOYAGE_KEY = "pa-test-key-ok-1234"


def test_doctor_thin_client_passes_with_empty_env() -> None:
    """Thin-client install: no server-side keys required — doctor must pass."""
    exit_code, report = run_doctor(environ={}, supabase_client=None)
    # Server-side keys (SUPABASE_URL etc.) surface as INFO, never FAIL.
    assert exit_code == 0, report
    assert "doctor: OK" in report
    # Server-side vars are mentioned as INFO so the user is aware.
    for var in SERVER_SIDE_ENV_VARS:
        assert var in report, f"doctor must mention server-side var {var}"


def test_doctor_fails_when_required_env_missing() -> None:
    """If REQUIRED_ENV_VARS is non-empty, missing vars should fail the doctor."""
    if not REQUIRED_ENV_VARS:
        pytest.skip("REQUIRED_ENV_VARS is empty (thin-client model — no required keys)")
    exit_code, report = run_doctor(environ={}, supabase_client=None)
    assert exit_code == 1
    assert "doctor: FAIL" in report
    for var in REQUIRED_ENV_VARS:
        assert var in report, f"doctor must name the missing var {var}"


def test_doctor_redacts_secrets_in_report() -> None:
    # Sanity: even when server-side vars are present, their values must not
    # be echoed — only the var name surfaces.
    env = {
        "SUPABASE_URL": "https://x.supabase.co",
        # missing the rest
    }
    _, report = run_doctor(environ=env, supabase_client=None)
    assert "https://x.supabase.co" not in report  # only the var name should appear
    assert "SUPABASE_URL" in report  # confirms we mention it without the value


def test_doctor_x402_default_stub_is_ok() -> None:
    # Include server-side creds so Supabase probes are exercised via the
    # injected fake client.
    env = {var: "x" for var in SERVER_SIDE_ENV_VARS} | {"VOYAGE_API_KEY": _VOYAGE_KEY}
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
    env = {var: "x" for var in SERVER_SIDE_ENV_VARS} | {"X402_MODE": "bogus"}
    exit_code, report = run_doctor(environ=env, supabase_client=_FakeSupabase({}))
    assert exit_code == 1
    assert "X402_MODE" in report


def test_doctor_passes_with_full_env_and_migrations() -> None:
    env = {var: "x" for var in SERVER_SIDE_ENV_VARS} | {
        "X402_MODE": "stub",
        "VOYAGE_API_KEY": _VOYAGE_KEY,
    }
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
    env = {var: "x" for var in SERVER_SIDE_ENV_VARS} | {
        "X402_MODE": "stub",
        "VOYAGE_API_KEY": _VOYAGE_KEY,
    }
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


def test_voyage_check_skipped_when_reranker_off() -> None:
    """S19-VOYAGE-API-KEY-01 — reranker unset → INFO row only, no api_key row."""
    from gecko_mcp.doctor import check_voyage_api_key

    rows = check_voyage_api_key(environ={})
    names = {r.name for r in rows}
    assert "reranker:kind" in names
    assert "voyage:api_key" not in names
    [info] = [r for r in rows if r.name == "reranker:kind"]
    assert info.ok is True
    assert info.info is True
    assert info.detail == "none"


def test_voyage_check_fails_when_key_missing() -> None:
    """GECKO_RERANKER=voyage with no VOYAGE_API_KEY → exit 1, names the var."""
    env = {var: "x" for var in SERVER_SIDE_ENV_VARS} | {
        "X402_MODE": "stub",
        "GECKO_RERANKER": "voyage",
    }
    manifest = {
        "extensions": list(REQUIRED_EXTENSIONS),
        "tables": list(REQUIRED_TABLES),
        "functions": list(REQUIRED_FUNCTIONS),
    }
    exit_code, report = run_doctor(environ=env, supabase_client=_FakeSupabase(manifest))
    assert exit_code == 1, report
    assert "VOYAGE_API_KEY" in report
    assert "voyage:api_key" in report


def test_voyage_check_passes_with_key() -> None:
    """Both env vars set → ok=True row, secret never appears in rendered output."""
    secret = "pa-test-secret-value-do-not-log"
    env = {var: "x" for var in SERVER_SIDE_ENV_VARS} | {
        "X402_MODE": "stub",
        "GECKO_RERANKER": "voyage",
        "VOYAGE_API_KEY": secret,
    }
    manifest = {
        "extensions": list(REQUIRED_EXTENSIONS),
        "tables": list(REQUIRED_TABLES),
        "functions": list(REQUIRED_FUNCTIONS),
    }
    exit_code, report = run_doctor(environ=env, supabase_client=_FakeSupabase(manifest))
    assert exit_code == 0, report
    assert "voyage:api_key" in report
    # The full secret must NEVER appear in rendered output.
    assert secret not in report
    # Only the prefix sentinel + last-4 suffix may surface.
    assert "pa-..." in report
    assert secret[-4:] in report  # last 4 chars are the only slice we expose


def test_embed_provider_voyage_default_no_key_thin_client() -> None:
    """S22-VOYAGE-EMBED — thin-client install: no server keys → key check skipped (INFO)."""
    from gecko_mcp.doctor import check_embed_provider

    # No server-side keys → thin-client mode → key validation skipped.
    rows = check_embed_provider(environ={})
    names = {r.name for r in rows}
    assert "embed:provider" in names
    # Key check must be INFO (skipped), not FAIL.
    fail_rows = [r for r in rows if not r.ok]
    assert not fail_rows, f"thin-client mode must not fail embed checks: {fail_rows}"


def test_embed_provider_voyage_default_no_key_server_stack() -> None:
    """S22-VOYAGE-EMBED — server-stack install: EMBED_PROVIDER=voyage, no key → FAIL."""
    from gecko_mcp.doctor import check_embed_provider

    # SUPABASE_URL present signals server stack → key validation is enforced.
    rows = check_embed_provider(environ={"SUPABASE_URL": "https://x.supabase.co"})
    names = {r.name for r in rows}
    assert "embed:provider" in names
    assert "embed:voyage_api_key" in names
    fail_row = next(r for r in rows if r.name == "embed:voyage_api_key")
    assert fail_row.ok is False
    assert "VOYAGE_API_KEY" in fail_row.detail


def test_embed_provider_voyage_with_key() -> None:
    """EMBED_PROVIDER=voyage + valid key on server stack → PASS, secret never in output."""
    from gecko_mcp.doctor import check_embed_provider

    secret = "pa-test-secret-do-not-log"
    rows = check_embed_provider(
        environ={
            "EMBED_PROVIDER": "voyage",
            "VOYAGE_API_KEY": secret,
            "SUPABASE_URL": "https://x.supabase.co",  # server-stack signal
        }
    )
    fail_rows = [r for r in rows if not r.ok]
    assert not fail_rows, fail_rows
    key_row = next(r for r in rows if r.name == "embed:voyage_api_key")
    assert key_row.ok is True
    assert secret not in key_row.detail
    assert "pa-..." in key_row.detail
    assert secret[-4:] in key_row.detail


def test_embed_provider_openai_no_key() -> None:
    """EMBED_PROVIDER=openai with no OPENAI_API_KEY → FAIL when server stack present."""
    from gecko_mcp.doctor import check_embed_provider

    # SUPABASE_URL signals server stack → key validation enforced.
    rows = check_embed_provider(
        environ={"EMBED_PROVIDER": "openai", "SUPABASE_URL": "https://x.supabase.co"}
    )
    fail_row = next((r for r in rows if not r.ok), None)
    assert fail_row is not None
    assert "OPENAI_API_KEY" in fail_row.detail


def test_embed_provider_openai_with_key() -> None:
    """EMBED_PROVIDER=openai + OPENAI_API_KEY set → PASS on server stack."""
    from gecko_mcp.doctor import check_embed_provider

    rows = check_embed_provider(
        environ={
            "EMBED_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test-key-1234",
            "SUPABASE_URL": "https://x.supabase.co",  # server-stack signal
        }
    )
    fail_rows = [r for r in rows if not r.ok]
    assert not fail_rows, fail_rows


def test_embed_provider_unknown_fails() -> None:
    """Unrecognised EMBED_PROVIDER → FAIL with helpful message (server stack)."""
    from gecko_mcp.doctor import check_embed_provider

    # Server-stack signal so the provider validation is enforced.
    rows = check_embed_provider(
        environ={"EMBED_PROVIDER": "cohere", "SUPABASE_URL": "https://x.supabase.co"}
    )
    fail_rows = [r for r in rows if not r.ok]
    assert fail_rows
    assert "cohere" in fail_rows[0].detail


def test_embed_provider_in_run_doctor_fails_without_voyage_key() -> None:
    """run_doctor exit_code=1 when EMBED_PROVIDER=voyage and VOYAGE_API_KEY missing."""
    # Server-side creds present so Supabase probes run via injected fake.
    env = {var: "x" for var in SERVER_SIDE_ENV_VARS} | {
        "X402_MODE": "stub",
        "EMBED_PROVIDER": "voyage",
    }
    manifest = {
        "extensions": list(REQUIRED_EXTENSIONS),
        "tables": list(REQUIRED_TABLES),
        "functions": list(REQUIRED_FUNCTIONS),
    }
    exit_code, report = run_doctor(environ=env, supabase_client=_FakeSupabase(manifest))
    assert exit_code == 1, report
    assert "embed:voyage_api_key" in report


def test_doctor_cli_passes_with_no_server_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: thin-client with no server-side keys → exit 0 (doctor: OK).

    This is the key regression guard: an external user who only has
    GECKO_API_URL + X402_MODE must be able to run `gecko-mcp doctor` and see
    green without supplying SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, or
    TAVILY_API_KEY.
    """
    from click.testing import CliRunner
    from gecko_mcp.cli import main

    # Clear all server-side keys so the test is a clean thin-client simulation.
    for var in (
        *SERVER_SIDE_ENV_VARS,
        "X402_MODE",
        "VOYAGE_API_KEY",
        "EMBED_PROVIDER",
        "GECKO_API_URL",
        "GECKO_RERANKER",
        # Force supabase chunk store so the test doesn't try to reach MongoDB Atlas.
        # An external user won't have GECKO_CHUNK_STORE set at all — the default is
        # supabase which returns a single INFO row without any network probe.
        "GECKO_CHUNK_STORE",
        "MONGODB_URI",
    ):
        monkeypatch.delenv(var, raising=False)
    # Don't auto-load ~/.gecko/.env during the test.
    monkeypatch.setattr("gecko_mcp.cli._load_env", lambda _: None)

    runner = CliRunner()
    result = runner.invoke(main, ["doctor"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "doctor: OK" in result.output
    # Server-side vars must be mentioned as INFO (not FAIL).
    for var in SERVER_SIDE_ENV_VARS:
        assert var in result.output
