"""Unit tests for the boot-time provider-status resolver.

Covers the LIVE / DARK / disabled state machine against the real
``infra/secrets-manifest.yml`` plus a small inline manifest for the edge cases
(requires_together partial set, requires_any_of). Also pins the secret-safety
invariant: no ProviderStatus field ever carries a secret value.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gecko_core.config.provider_status import (
    ProviderStatus,
    _env_state,
    resolve_all,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "infra" / "secrets-manifest.yml"


@pytest.fixture(autouse=True)
def _clear_manifest_cache() -> None:
    # _load_manifest is lru_cached on path; tests write distinct temp files so
    # there's no cross-contamination, but clear to be safe across the suite.
    from gecko_core.config import provider_status

    provider_status._load_manifest.cache_clear()


def _by_name(statuses: list[ProviderStatus], name: str) -> ProviderStatus:
    return next(s for s in statuses if s.name == name)


def test_env_state_classifies_without_returning_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_REAL", "sk-abc123")
    monkeypatch.setenv("X_SENT", "__unset__")
    monkeypatch.delenv("X_MISSING", raising=False)
    monkeypatch.setenv("X_EMPTY", "  ")
    assert _env_state("X_REAL") == "real"
    assert _env_state("X_SENT") == "sentinel"
    assert _env_state("X_MISSING") == "unset"
    assert _env_state("X_EMPTY") == "unset"


def test_disabled_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GECKO_NEWS_PROVIDER", "none")
    monkeypatch.setenv("OKX_TRADING_API_KEY", "real-key")
    monkeypatch.setenv("OKX_TRADING_SECRET_KEY", "real-secret")
    okx = _by_name(resolve_all(_MANIFEST), "okx_news")
    assert okx.status == "disabled"
    assert okx.enabled is False


def test_dark_when_enabled_but_cred_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GECKO_NEWS_PROVIDER", "okx")
    monkeypatch.setenv("OKX_TRADING_API_KEY", "real-key")
    monkeypatch.setenv("OKX_TRADING_SECRET_KEY", "__unset__")  # partial set
    okx = _by_name(resolve_all(_MANIFEST), "okx_news")
    assert okx.status == "DARK"
    assert okx.is_dark is True
    # requires_together => the missing var is named in the reason (a NAME, not a value).
    assert "OKX_TRADING_SECRET_KEY" in okx.reason
    assert "real-key" not in okx.reason  # never leak the real value


def test_live_when_enabled_and_creds_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GECKO_NEWS_PROVIDER", "okx")
    monkeypatch.setenv("OKX_TRADING_API_KEY", "real-key")
    monkeypatch.setenv("OKX_TRADING_SECRET_KEY", "real-secret")
    okx = _by_name(resolve_all(_MANIFEST), "okx_news")
    assert okx.status == "LIVE"
    assert okx.enabled is True


def test_safety_rpc_requires_any_of(monkeypatch: pytest.MonkeyPatch) -> None:
    # Enabled when HELIUS_API_KEY present; LIVE if EITHER Helius or QuickNode real.
    monkeypatch.setenv("HELIUS_API_KEY", "helius-key")
    monkeypatch.delenv("QUICKNODE_RPC_URL", raising=False)
    rpc = _by_name(resolve_all(_MANIFEST), "safety_rpc")
    assert rpc.status == "LIVE"


def test_supabase_always_enabled_dark_without_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    sup = _by_name(resolve_all(_MANIFEST), "supabase")
    assert sup.enabled is True
    assert sup.status == "DARK"


def test_requires_any_of_all_unset_is_dark(tmp_path: Path) -> None:
    manifest = tmp_path / "m.yml"
    manifest.write_text(
        "providers:\n"
        "  rpc:\n"
        "    enabled_when: {flag: FLAG_A, present: true}\n"
        "    requires: []\n"
        "    requires_any_of: [VAR_A, VAR_B]\n"
        "    fail_mode: open\n"
        "boot_required: []\n"
    )
    import os

    os.environ["FLAG_A"] = "x"
    os.environ.pop("VAR_A", None)
    os.environ.pop("VAR_B", None)
    try:
        rpc = _by_name(resolve_all(manifest), "rpc")
        assert rpc.status == "DARK"
        assert "VAR_A" in rpc.reason and "VAR_B" in rpc.reason
    finally:
        os.environ.pop("FLAG_A", None)


def test_no_status_field_carries_a_secret_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # Set EVERY known cred to a recognizable secret string; assert it never
    # appears in any ProviderStatus field (name/status/reason/fail_mode).
    secret = "SUPERSECRET_DO_NOT_LEAK"
    for var in (
        "OKX_TRADING_API_KEY",
        "OKX_TRADING_SECRET_KEY",
        "OKX_ONCHAINOS_API_KEY",
        "HELIUS_API_KEY",
        "QUICKNODE_RPC_URL",
        "DUNE_API_KEY",
        "VOYAGE_API_KEY",
        "MONGODB_URI",
        "CDP_API_KEY_ID",
        "CDP_API_KEY_SECRET",
        "PRIVY_APP_ID",
        "PRIVY_APP_SECRET",
        "TWITSH_WALLET_PRIVATE_KEY",
        "TWITSH_WALLET_ADDRESS",
        "OPENROUTER_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "TAVILY_API_KEY",
    ):
        monkeypatch.setenv(var, secret)
    # Enable a few providers so creds are actually consulted.
    monkeypatch.setenv("GECKO_NEWS_PROVIDER", "okx")
    monkeypatch.setenv("LLM_ROUTER", "openrouter")
    monkeypatch.setenv("EMBED_PROVIDER", "voyage")
    for s in resolve_all(_MANIFEST):
        blob = f"{s.name}{s.status}{s.reason}{s.fail_mode}"
        assert secret not in blob, f"secret leaked into provider {s.name!r} status"
