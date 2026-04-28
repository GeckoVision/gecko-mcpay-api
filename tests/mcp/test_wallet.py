"""Tests for the `gecko-mcp wallet` subcommand group.

The wallet file is the only credential in v2, so its on-disk shape, file
mode, and round-trip behaviour are the contract these tests pin.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from cryptography.fernet import InvalidToken
from gecko_mcp import wallet_self_custody as wallet_module
from gecko_mcp.wallet_self_custody import (
    _load_keypair,
    _save_keypair,
    get_keypair_for_signing,
    wallet,
)
from solders.keypair import Keypair


@pytest.fixture
def tmp_wallet_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect WALLET_PATH to a tmp location for the duration of the test."""
    target = tmp_path / ".gecko" / "wallet.json"
    monkeypatch.setattr(wallet_module, "WALLET_PATH", target)
    return target


def test_wallet_new_creates_file_with_correct_shape_and_mode(tmp_wallet_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(wallet, ["new", "--passphrase", "test"])
    assert result.exit_code == 0, result.output
    assert tmp_wallet_path.exists()

    payload = json.loads(tmp_wallet_path.read_text())
    assert set(payload.keys()) == {"version", "public_key", "encrypted_secret"}
    assert payload["version"] == 1
    assert isinstance(payload["public_key"], str) and len(payload["public_key"]) > 0
    assert isinstance(payload["encrypted_secret"], str) and len(payload["encrypted_secret"]) > 0

    mode = stat.S_IMODE(tmp_wallet_path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_wallet_new_prompts_for_overwrite_when_file_exists(tmp_wallet_path: Path) -> None:
    runner = CliRunner()
    first = runner.invoke(wallet, ["new", "--passphrase", "test"])
    assert first.exit_code == 0

    original = tmp_wallet_path.read_text()
    # Decline overwrite.
    decline = runner.invoke(wallet, ["new", "--passphrase", "test"], input="n\n")
    assert decline.exit_code != 0  # click.confirm(abort=True) aborts
    assert tmp_wallet_path.read_text() == original

    # Accept overwrite.
    accept = runner.invoke(wallet, ["new", "--passphrase", "test"], input="y\n")
    assert accept.exit_code == 0
    assert tmp_wallet_path.read_text() != original


def test_save_load_roundtrip_yields_same_keypair(tmp_wallet_path: Path) -> None:
    kp = Keypair()
    _save_keypair(kp, "rocinante")
    loaded = _load_keypair("rocinante")
    assert str(loaded.pubkey()) == str(kp.pubkey())
    assert bytes(loaded) == bytes(kp)


def test_load_with_wrong_passphrase_raises(tmp_wallet_path: Path) -> None:
    _save_keypair(Keypair(), "right")
    with pytest.raises(InvalidToken):
        _load_keypair("wrong")


def test_wallet_address_prints_pubkey(tmp_wallet_path: Path) -> None:
    kp = Keypair()
    _save_keypair(kp, "test")
    runner = CliRunner()
    result = runner.invoke(wallet, ["address"])
    assert result.exit_code == 0
    assert str(kp.pubkey()) in result.output


def test_get_keypair_for_signing_uses_env_passphrase(
    tmp_wallet_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kp = Keypair()
    _save_keypair(kp, "from-env")
    monkeypatch.setenv("GECKO_WALLET_PASSPHRASE", "from-env")
    loaded = get_keypair_for_signing()
    assert str(loaded.pubkey()) == str(kp.pubkey())


def test_get_keypair_for_signing_explicit_passphrase_wins(
    tmp_wallet_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kp = Keypair()
    _save_keypair(kp, "explicit")
    monkeypatch.setenv("GECKO_WALLET_PASSPHRASE", "wrong")
    loaded = get_keypair_for_signing(passphrase="explicit")
    assert str(loaded.pubkey()) == str(kp.pubkey())


def test_get_keypair_for_signing_defaults_when_no_passphrase(
    tmp_wallet_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GECKO_WALLET_PASSPHRASE", raising=False)
    kp = Keypair()
    _save_keypair(kp, "default")
    loaded = get_keypair_for_signing()
    assert str(loaded.pubkey()) == str(kp.pubkey())


def test_balance_command_calls_rpc_and_formats_usdc(
    tmp_wallet_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kp = Keypair()
    _save_keypair(kp, "default")

    fake_response_body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "value": [
                {
                    "account": {
                        "data": {
                            "parsed": {
                                "info": {
                                    "tokenAmount": {"amount": "12500000"},
                                }
                            }
                        }
                    }
                }
            ]
        },
    }

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return fake_response_body

    captured: dict[str, Any] = {}

    def fake_post(url: str, *, json: dict[str, Any], timeout: float) -> _FakeResponse:
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    with patch.object(wallet_module.httpx, "post", side_effect=fake_post):
        runner = CliRunner()
        result = runner.invoke(wallet, ["balance"])

    assert result.exit_code == 0, result.output
    assert "12.50 USDC" in result.output
    assert "devnet" in result.output
    # The RPC request must scope by the devnet USDC mint.
    assert captured["json"]["params"][1]["mint"] == wallet_module.USDC_MINT_DEVNET
    assert captured["json"]["params"][0] == str(kp.pubkey())


def test_balance_command_handles_no_token_account(
    tmp_wallet_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_keypair(Keypair(), "default")

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": 1, "result": {"value": []}}

    monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
    with patch.object(wallet_module.httpx, "post", return_value=_FakeResponse()):
        runner = CliRunner()
        result = runner.invoke(wallet, ["balance"])

    assert result.exit_code == 0, result.output
    assert "0.00 USDC" in result.output


def test_balance_command_picks_mainnet_mint_when_rpc_is_mainnet(
    tmp_wallet_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_keypair(Keypair(), "default")

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": 1, "result": {"value": []}}

    captured: dict[str, Any] = {}

    def fake_post(url: str, *, json: dict[str, Any], timeout: float) -> _FakeResponse:
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    with patch.object(wallet_module.httpx, "post", side_effect=fake_post):
        runner = CliRunner()
        result = runner.invoke(wallet, ["balance"])

    assert result.exit_code == 0
    assert captured["json"]["params"][1]["mint"] == wallet_module.USDC_MINT_MAINNET
    assert "mainnet" in result.output


def test_address_command_errors_when_no_wallet(tmp_wallet_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(wallet, ["address"])
    assert result.exit_code != 0
    assert "No wallet" in result.output
