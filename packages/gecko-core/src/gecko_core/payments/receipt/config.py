"""Decision-Receipt configuration + feature gate (devnet only, default off).

The anchor path moves NO real money (devnet airdrop SOL pays the ~5000-lamport
fee), but it DOES sign and broadcast a transaction, so it is gated hard:

  * ``GECKO_RECEIPT_ENABLED``     — must be ``"1"``/``"true"`` to anchor. Unset
    or anything else → :class:`ReceiptDisabled` raised by the anchor.
  * ``GECKO_RECEIPT_RPC_URL``     — explicit devnet RPC endpoint. REQUIRED when
    enabled. We refuse to default to a mainnet URL.
  * ``GECKO_RECEIPT_ORACLE_KEYPAIR`` — path to the devnet oracle keypair JSON
    (a 64-int byte array, the Solana CLI format). gitignored; ``.env.example``
    ships empty. NEVER logged.

A safety check rejects any RPC URL that looks like mainnet. v0 is devnet-only;
mainnet anchoring is the v1 PDA program, not this code path.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENABLED_ENV = "GECKO_RECEIPT_ENABLED"
RPC_URL_ENV = "GECKO_RECEIPT_RPC_URL"
ORACLE_KEYPAIR_ENV = "GECKO_RECEIPT_ORACLE_KEYPAIR"

# Substrings that mark an RPC URL as mainnet — we refuse to anchor against
# these in v0. Defensive, not exhaustive: the operator still controls the env.
_MAINNET_MARKERS = ("mainnet", "mainnet-beta", "api.mainnet")

_TRUTHY = {"1", "true", "yes", "on"}


class ReceiptConfigError(RuntimeError):
    """Receipt env is misconfigured (missing RPC / keypair, or mainnet URL)."""


class ReceiptDisabled(RuntimeError):
    """Anchor invoked while ``GECKO_RECEIPT_ENABLED`` is off."""


@dataclass(frozen=True)
class ReceiptConfig:
    """Resolved, validated receipt configuration."""

    enabled: bool
    rpc_url: str
    oracle_keypair_path: Path


def is_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Cheap gate check without touching the RPC / keypair."""
    src = env if env is not None else os.environ
    return src.get(ENABLED_ENV, "").strip().lower() in _TRUTHY


def _assert_devnet(rpc_url: str) -> None:
    low = rpc_url.lower()
    if any(marker in low for marker in _MAINNET_MARKERS):
        raise ReceiptConfigError(
            "GECKO_RECEIPT_RPC_URL looks like mainnet; the v0 Decision Receipt "
            "is devnet-only. Point it at a devnet RPC (e.g. "
            "https://api.devnet.solana.com)."
        )


def load_config(env: Mapping[str, str] | None = None) -> ReceiptConfig:
    """Resolve + validate the receipt config from the environment.

    Raises :class:`ReceiptDisabled` if the feature gate is off, and
    :class:`ReceiptConfigError` if enabled but RPC / keypair are missing or the
    RPC looks like mainnet. Never logs the keypair path's contents.
    """
    src = env if env is not None else os.environ

    if not is_enabled(src):
        raise ReceiptDisabled(
            f"{ENABLED_ENV} is not set; Decision-Receipt anchoring is disabled "
            "(default). Set it to '1' on a devnet deploy to enable."
        )

    rpc_url = src.get(RPC_URL_ENV, "").strip()
    if not rpc_url:
        raise ReceiptConfigError(
            f"{RPC_URL_ENV} is required when {ENABLED_ENV} is on; set it to a devnet RPC endpoint."
        )
    _assert_devnet(rpc_url)

    keypair_raw = src.get(ORACLE_KEYPAIR_ENV, "").strip()
    if not keypair_raw:
        raise ReceiptConfigError(
            f"{ORACLE_KEYPAIR_ENV} is required when {ENABLED_ENV} is on; set it "
            "to the path of the devnet oracle keypair JSON."
        )

    return ReceiptConfig(
        enabled=True,
        rpc_url=rpc_url,
        oracle_keypair_path=Path(keypair_raw),
    )


__all__ = [
    "ENABLED_ENV",
    "ORACLE_KEYPAIR_ENV",
    "RPC_URL_ENV",
    "ReceiptConfig",
    "ReceiptConfigError",
    "ReceiptDisabled",
    "is_enabled",
    "load_config",
]
