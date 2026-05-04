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


# ---------------------------------------------------------------------------
# frames.ag Email+OTP connect flow (S26-W3-02)
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal httpx.Response stub for frames.ag API calls."""

    def __init__(self, status_code: int, body: dict) -> None:
        self._status_code = status_code
        self._body = body

    @property
    def status_code(self) -> int:
        return self._status_code

    def raise_for_status(self) -> None:
        if self._status_code >= 400:
            import httpx

            req = httpx.Request("POST", "https://frames.ag/api/connect/start")
            resp = httpx.Response(self._status_code, json=self._body, request=req)
            raise httpx.HTTPStatusError(f"HTTP {self._status_code}", request=req, response=resp)

    def json(self) -> dict:
        return self._body


@pytest.fixture
def tmp_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CONFIG_PATH to a tmp location so tests don't touch ~/.agentwallet."""
    import gecko_mcp.wallet as wallet_mod

    target = tmp_path / ".agentwallet" / "config.json"
    monkeypatch.setattr(wallet_mod, "CONFIG_PATH", target)
    return target


def test_frames_connect_happy_path(tmp_config_path: Path) -> None:
    """_frames_connect returns correct credential dict on successful OTP flow."""
    import unittest.mock as mock

    from gecko_mcp.wallet import _frames_connect

    start = _FakeResponse(200, {"username": "alice"})
    complete = _FakeResponse(
        200,
        {
            "apiToken": "mf_test_token_abc123",
            "solanaAddress": "SolAddr1234567890",
            "evmAddress": "0xEvmAddr",
        },
    )

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, path: str, **kwargs):
            if "start" in path:
                return start
            if "complete" in path:
                return complete
            raise AssertionError(f"unexpected path: {path}")

    with (
        mock.patch("gecko_mcp.wallet.httpx.Client", return_value=_FakeClient()),
        mock.patch("click.prompt", return_value="123456"),
    ):
        result = _frames_connect("user@example.com")

    assert result["username"] == "alice"
    assert result["apiToken"] == "mf_test_token_abc123"
    assert result["solanaAddress"] == "SolAddr1234567890"
    assert result["evmAddress"] == "0xEvmAddr"


def test_frames_wallet_new_writes_config_and_prints_address(tmp_config_path: Path) -> None:
    """wallet new runs OTP flow, writes config, prints address — no browser required."""
    import unittest.mock as mock

    from gecko_mcp.wallet import wallet

    start = _FakeResponse(200, {"username": "alice"})
    complete = _FakeResponse(
        200,
        {
            "apiToken": "mf_test_token",
            "solanaAddress": "SolAddr999",
            "evmAddress": "0xEvm999",
        },
    )

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, path: str, **kwargs):
            return start if "start" in path else complete

    runner = CliRunner()
    with mock.patch("gecko_mcp.wallet.httpx.Client", return_value=_FakeClient()):
        # Provide email via --email option; OTP via stdin prompt.
        result = runner.invoke(wallet, ["new", "--email", "user@example.com"], input="123456\n")

    assert result.exit_code == 0, result.output
    assert "Wallet ready" in result.output
    assert "@alice" in result.output
    assert "SolAddr999" in result.output
    # apiToken must NOT appear anywhere in output.
    assert "mf_test_token" not in result.output

    # Config must be written with chmod 600.
    import stat

    assert tmp_config_path.exists()
    payload = json.loads(tmp_config_path.read_text())
    assert payload["username"] == "alice"
    assert payload["apiToken"] == "mf_test_token"
    mode = stat.S_IMODE(tmp_config_path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_frames_wallet_new_already_connected_shows_info(tmp_config_path: Path) -> None:
    """wallet new when config already exists prints summary and exits 0."""
    import gecko_mcp.wallet as wallet_mod

    config = {
        "username": "bob",
        "solanaAddress": "BobAddr",
        "evmAddress": "0xBob",
        "apiToken": "mf_existing",
    }
    tmp_config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_config_path.write_text(json.dumps(config))

    runner = CliRunner()
    result = runner.invoke(wallet_mod.wallet, ["new"])
    assert result.exit_code == 0, result.output
    assert "Already connected" in result.output
    assert "@bob" in result.output
    assert "BobAddr" in result.output
    # apiToken must not appear.
    assert "mf_existing" not in result.output


def test_frames_wallet_new_invalid_otp_rejected(tmp_config_path: Path) -> None:
    """wallet new aborts cleanly when user enters a non-6-digit OTP."""
    import unittest.mock as mock

    from gecko_mcp.wallet import wallet

    start = _FakeResponse(200, {"username": "alice"})

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, path: str, **kwargs):
            return start

    runner = CliRunner()
    with mock.patch("gecko_mcp.wallet.httpx.Client", return_value=_FakeClient()):
        result = runner.invoke(wallet, ["new", "--email", "user@example.com"], input="abc\n")

    assert result.exit_code != 0
    assert "6 digit" in result.output.lower() or "6-digit" in result.output.lower()


def test_frames_wallet_new_start_failure_propagated(tmp_config_path: Path) -> None:
    """wallet new surfaces frames.ag error verbatim when /connect/start fails."""
    import unittest.mock as mock

    from gecko_mcp.wallet import wallet

    start = _FakeResponse(429, {"code": "RATE_LIMITED", "message": "too many requests"})

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, path: str, **kwargs):
            return start

    runner = CliRunner()
    with mock.patch("gecko_mcp.wallet.httpx.Client", return_value=_FakeClient()):
        result = runner.invoke(wallet, ["new", "--email", "user@example.com"])

    assert result.exit_code != 0
