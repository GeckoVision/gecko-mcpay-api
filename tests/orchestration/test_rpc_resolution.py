"""Phase 0.1 — Solana RPC resolution for the contract-safety read.

The wedge was dark in prod: `_rpc_url()` read only QUICKNODE_RPC_URL, which is
absent from the API SSM map, so every safety read returned unavailable. These
tests pin the Helius fallback (Helius is the configured primary).
"""

from __future__ import annotations

import pytest

from gecko_core.orchestration.trade_panel.safety_check import _rpc_url


def test_quicknode_url_wins_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUICKNODE_RPC_URL", "https://example.quiknode.pro/abc/")
    monkeypatch.setenv("HELIUS_API_KEY", "heliuskey")
    assert _rpc_url() == "https://example.quiknode.pro/abc/"


def test_helius_fallback_when_quicknode_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUICKNODE_RPC_URL", raising=False)
    monkeypatch.setenv("HELIUS_API_KEY", "heliuskey")
    url = _rpc_url()
    assert url is not None
    assert url.startswith("https://mainnet.helius-rpc.com/")
    assert "heliuskey" in url  # fake key — built from HELIUS_API_KEY


def test_none_when_no_rpc_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUICKNODE_RPC_URL", raising=False)
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    assert _rpc_url() is None


def test_unset_sentinel_treated_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SSM `__unset__` sentinel must not build a broken Helius URL."""
    monkeypatch.setenv("QUICKNODE_RPC_URL", "__unset__")
    monkeypatch.setenv("HELIUS_API_KEY", "__unset__")
    assert _rpc_url() is None
