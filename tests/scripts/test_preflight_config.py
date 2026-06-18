"""Tests for scripts/preflight_config.py — the pre-deploy config-parity check.

Focus: the pure provider-discovery + local-status logic (no AWS, no network).
SSM read-back is shelled to the `aws` CLI and is exercised only via a stubbed
``_ssm_state`` so the test stays offline and secret-clean.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "preflight_config",
    Path(__file__).resolve().parents[2] / "scripts" / "preflight_config.py",
)
assert _SPEC and _SPEC.loader
preflight = importlib.util.module_from_spec(_SPEC)
sys.modules["preflight_config"] = preflight
_SPEC.loader.exec_module(preflight)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wipe every var the discovery touches so each test starts from "all off".
    for var in (
        "GECKO_NEWS_PROVIDER",
        "OKX_TRADING_API_KEY",
        "OKX_TRADING_SECRET_KEY",
        "OKX_TRADING_PASSPHRASE",
        "OKX_ONCHAINOS_API_KEY",
        "HELIUS_API_KEY",
        "QUICKNODE_RPC_URL",
        "DUNE_API_KEY",
        "EMBED_PROVIDER",
        "GECKO_RERANKER",
        "GECKO_CHUNK_STORE",
        "GECKO_TRANSCRIPT_STORE",
        "MONGODB_URI",
        "VOYAGE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_sentinel_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DUNE_API_KEY", "__unset__")
    assert preflight._clean("DUNE_API_KEY") == ""


def test_okx_news_disabled_by_default() -> None:
    enabled = [p for p in preflight._discover_providers() if p.enabled]
    assert "okx-news" not in {p.name for p in enabled}


def test_okx_news_enabled_but_missing_secret_fails_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The exact prod bug: flag on, key present, secret missing → BAD locally.
    monkeypatch.setenv("GECKO_NEWS_PROVIDER", "okx")
    monkeypatch.setenv("OKX_TRADING_API_KEY", "realkey")
    # secret + passphrase left unset
    providers = {p.name: p for p in preflight._discover_providers()}
    okx = providers["okx-news"]
    assert okx.enabled
    ok, problems = preflight._local_status(okx)
    assert not ok
    assert any("OKX_TRADING_SECRET_KEY" in p for p in problems)


def test_okx_news_fully_provisioned_passes_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GECKO_NEWS_PROVIDER", "okx")
    monkeypatch.setenv("OKX_TRADING_API_KEY", "realkey")
    monkeypatch.setenv("OKX_TRADING_SECRET_KEY", "realsecret")
    okx = {p.name: p for p in preflight._discover_providers()}["okx-news"]
    ok, problems = preflight._local_status(okx)
    assert ok and not problems


def test_solana_rpc_needs_at_least_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HELIUS_API_KEY", "h-real")
    rpc = {p.name: p for p in preflight._discover_providers()}["solana-rpc"]
    assert rpc.enabled
    ok, _ = preflight._local_status(rpc)
    assert ok


def test_drift_local_real_ssm_sentinel_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Local has real OKX creds, SSM has the sentinel → the drift this script
    # exists to catch. Stub the SSM read so no AWS call happens.
    monkeypatch.setenv("GECKO_NEWS_PROVIDER", "okx")
    monkeypatch.setenv("OKX_TRADING_API_KEY", "realkey")
    monkeypatch.setenv("OKX_TRADING_SECRET_KEY", "realsecret")
    monkeypatch.setattr(preflight, "_ssm_state", lambda *_a, **_k: "sentinel")
    monkeypatch.setattr(sys, "argv", ["preflight_config.py", "--check-ssm"])
    rc = preflight.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "DRIFT" in out
    assert "PREFLIGHT FAILED" in out
    # secret values must never appear
    assert "realsecret" not in out and "realkey" not in out


def test_all_disabled_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["preflight_config.py"])
    rc = preflight.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "PREFLIGHT PASSED" in out
