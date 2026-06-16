"""ENV-gated NewsProvider factory tests (reworked 2026-06-16).

Asserts the fail-OPEN + provider-neutral contract for the OKX V5 HMAC adapter,
driven by the account-associated trading creds:
  - default (flag unset / none) → None (today's behavior, no news)
  - okx flag WITHOUT provisioned key/secret → None (never hard-enabled)
  - SSM ``__unset__`` sentinel treated as unset → None
  - okx flag WITH key+secret → an OKX provider (NewsProvider-shaped); passphrase
    is OPTIONAL (OKX V5 keys may or may not carry one)
  - unknown flag value → None (fail-OPEN, don't guess)

Light fakes, no network.
"""

from __future__ import annotations

import pytest
from gecko_core.orchestration.trade_panel.news_factory import build_news_provider
from gecko_core.orchestration.trade_panel.news_provider import NewsProvider

_FLAG = "GECKO_NEWS_PROVIDER"
_KEY = "OKX_TRADING_API_KEY"
_SECRET = "OKX_TRADING_SECRET_KEY"
_PASS = "OKX_TRADING_PASSPHRASE"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (_FLAG, _KEY, _SECRET, _PASS):
        monkeypatch.delenv(name, raising=False)


def test_default_unset_returns_none() -> None:
    assert build_news_provider() is None


@pytest.mark.parametrize("val", ["none", "off", "0", "false", "", "NONE"])
def test_explicit_off_values_return_none(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv(_FLAG, val)
    assert build_news_provider() is None


def test_okx_flag_without_creds_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """okx requested but key/secret unprovisioned → None (never hard-enabled)."""
    monkeypatch.setenv(_FLAG, "okx")
    assert build_news_provider() is None


def test_okx_flag_with_sentinel_creds_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSM ``__unset__`` sentinel is treated as truly unset → None."""
    monkeypatch.setenv(_FLAG, "okx")
    monkeypatch.setenv(_KEY, "__unset__")
    monkeypatch.setenv(_SECRET, "__unset__")
    monkeypatch.setenv(_PASS, "__unset__")
    assert build_news_provider() is None


def test_okx_flag_with_key_only_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Key present but secret missing → None (both required)."""
    monkeypatch.setenv(_FLAG, "okx")
    monkeypatch.setenv(_KEY, "real-key-value")
    assert build_news_provider() is None


def test_okx_flag_with_secret_only_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_FLAG, "okx")
    monkeypatch.setenv(_SECRET, "real-secret-value")
    assert build_news_provider() is None


def test_okx_flag_provisioned_no_passphrase_builds_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passphrase is optional — key+secret alone build the provider."""
    monkeypatch.setenv(_FLAG, "okx")
    monkeypatch.setenv(_KEY, "real-key-value")
    monkeypatch.setenv(_SECRET, "real-secret-value")
    provider = build_news_provider()
    assert provider is not None
    assert isinstance(provider, NewsProvider)


def test_okx_flag_fully_provisioned_builds_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_FLAG, "okx")
    monkeypatch.setenv(_KEY, "real-key-value")
    monkeypatch.setenv(_SECRET, "real-secret-value")
    monkeypatch.setenv(_PASS, "real-passphrase")
    provider = build_news_provider()
    assert provider is not None
    # Provider-neutral: it satisfies the protocol the panel knows.
    assert isinstance(provider, NewsProvider)


def test_unknown_flag_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_FLAG, "tavily-typo")
    assert build_news_provider() is None
