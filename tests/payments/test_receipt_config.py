"""Receipt feature-gate + config validation (pure, offline).

The anchor moves no real money but signs + broadcasts, so the gate is
safety-critical: it must be OFF by default and refuse a mainnet RPC. No
network, no Solana stack imported.
"""

from __future__ import annotations

import pytest
from gecko_core.payments.receipt.config import (
    ReceiptConfigError,
    ReceiptDisabled,
    is_enabled,
    load_config,
)


def test_disabled_by_default() -> None:
    assert is_enabled({}) is False
    assert is_enabled({"GECKO_RECEIPT_ENABLED": "0"}) is False
    assert is_enabled({"GECKO_RECEIPT_ENABLED": "false"}) is False


def test_enabled_truthy_values() -> None:
    for v in ("1", "true", "yes", "on", "TRUE"):
        assert is_enabled({"GECKO_RECEIPT_ENABLED": v}) is True


def test_load_config_raises_when_disabled() -> None:
    with pytest.raises(ReceiptDisabled):
        load_config({})


def test_load_config_requires_rpc_and_keypair() -> None:
    with pytest.raises(ReceiptConfigError, match="GECKO_RECEIPT_RPC_URL"):
        load_config({"GECKO_RECEIPT_ENABLED": "1"})
    with pytest.raises(ReceiptConfigError, match="GECKO_RECEIPT_ORACLE_KEYPAIR"):
        load_config(
            {
                "GECKO_RECEIPT_ENABLED": "1",
                "GECKO_RECEIPT_RPC_URL": "https://api.devnet.solana.com",
            }
        )


def test_load_config_rejects_mainnet_rpc() -> None:
    with pytest.raises(ReceiptConfigError, match="mainnet"):
        load_config(
            {
                "GECKO_RECEIPT_ENABLED": "1",
                "GECKO_RECEIPT_RPC_URL": "https://api.mainnet-beta.solana.com",
                "GECKO_RECEIPT_ORACLE_KEYPAIR": "/tmp/k.json",
            }
        )


def test_load_config_happy_path_devnet() -> None:
    cfg = load_config(
        {
            "GECKO_RECEIPT_ENABLED": "1",
            "GECKO_RECEIPT_RPC_URL": "https://api.devnet.solana.com",
            "GECKO_RECEIPT_ORACLE_KEYPAIR": "/tmp/devnet-oracle.json",
        }
    )
    assert cfg.enabled is True
    assert cfg.rpc_url == "https://api.devnet.solana.com"
    assert str(cfg.oracle_keypair_path) == "/tmp/devnet-oracle.json"
