"""Phase 2.1 — ENV-gated NewsProvider factory tests.

Asserts the fail-OPEN + provider-neutral contract:
  - default (flag unset / none) → None (today's behavior, no news)
  - okx flag WITHOUT provisioned key/url → None (never hard-enabled)
  - okx flag WITH both provisioned → an OKX http provider (NewsProvider-shaped)
  - unknown flag value → None (fail-OPEN, don't guess)

Light fakes, no network.
"""

from __future__ import annotations

import pytest
from gecko_core.orchestration.trade_panel.news_factory import build_news_provider
from gecko_core.orchestration.trade_panel.news_provider import NewsProvider

_FLAG = "GECKO_NEWS_PROVIDER"
_URL = "OKX_NEWS_API_URL"
_KEY = "OKX_API_KEY"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (_FLAG, _URL, _KEY):
        monkeypatch.delenv(name, raising=False)


def test_default_unset_returns_none() -> None:
    assert build_news_provider() is None


@pytest.mark.parametrize("val", ["none", "off", "0", "false", "", "NONE"])
def test_explicit_off_values_return_none(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv(_FLAG, val)
    assert build_news_provider() is None


def test_okx_flag_without_key_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """okx requested but key/url unprovisioned → None (never hard-enabled)."""
    monkeypatch.setenv(_FLAG, "okx")
    assert build_news_provider() is None


def test_okx_flag_with_sentinel_key_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSM ``__unset__`` sentinel is treated as truly unset → None."""
    monkeypatch.setenv(_FLAG, "okx")
    monkeypatch.setenv(_URL, "__unset__")
    monkeypatch.setenv(_KEY, "__unset__")
    assert build_news_provider() is None


def test_okx_flag_with_url_only_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_FLAG, "okx")
    monkeypatch.setenv(_URL, "https://news.example/okx")
    assert build_news_provider() is None


def test_okx_flag_fully_provisioned_builds_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_FLAG, "okx")
    monkeypatch.setenv(_URL, "https://news.example/okx")
    monkeypatch.setenv(_KEY, "real-key-value")
    provider = build_news_provider()
    assert provider is not None
    # Provider-neutral: it satisfies the protocol the panel knows.
    assert isinstance(provider, NewsProvider)


def test_unknown_flag_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_FLAG, "tavily-typo")
    assert build_news_provider() is None
