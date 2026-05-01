"""S13-WALLET-01 — `~/.gecko/wallets.toml` reader/writer + types.

Single source of truth for the multi-wallet panel surfaced by `bb wallet`.
Tokens / private keys never live in the TOML — addresses + env-var
references only (per the spec at
``docs/strategy/wallet-panel-spec-2026-04-30.md`` § Storage shape).

The CLI is a transport. All config IO + balance/health resolution lives
here so the future MCP `gecko_wallet` surface can reuse the same code.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

DEFAULT_WALLETS_PATH = Path.home() / ".gecko" / "wallets.toml"

# Friendly kind labels — extensible enum kept as a Literal so mypy catches
# typos at the CLI boundary.
WalletKind = Literal[
    "frames",
    "twitsh",
    "awal",
    "publish-new",
    "paragraph",
    "custom",
]

KNOWN_KINDS: tuple[WalletKind, ...] = (
    "frames",
    "twitsh",
    "awal",
    "publish-new",
    "paragraph",
    "custom",
)


@dataclass(frozen=True)
class WalletEntry:
    """One configured wallet.

    `api_token_env` is the name of the env var holding the secret —
    NEVER the secret itself. `address` is the public payout / receive
    address, safe to render.
    """

    kind: WalletKind
    network: str  # CAIP-2 form (e.g. "solana:mainnet", "eip155:8453")
    address: str
    api_token_env: str | None = None
    mode: str | None = None  # "receive-only" etc.


@dataclass(frozen=True)
class WalletsConfig:
    """Parsed `wallets.toml`. `wallets[kind]` → `WalletEntry`."""

    default_payer: str | None = None
    default_receiver: str | None = None
    wallets: dict[str, WalletEntry] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def read_wallets_config(path: Path | None = None) -> WalletsConfig:
    """Parse `~/.gecko/wallets.toml` (or `path`). Missing file → empty config.

    Returns an empty :class:`WalletsConfig` rather than raising when the
    file is absent — the panel is defined for the "no wallets configured"
    state too (spec §First-run behavior).
    """
    p = path or DEFAULT_WALLETS_PATH
    if not p.exists():
        return WalletsConfig()
    raw = tomllib.loads(p.read_text())
    default_payer = raw.pop("default_payer", None)
    default_receiver = raw.pop("default_receiver", None)
    wallets: dict[str, WalletEntry] = {}
    for kind, body in raw.items():
        if not isinstance(body, dict):
            continue
        # Cast: KNOWN_KINDS is the Literal canon; unknown kinds get tagged
        # "custom" rather than rejected — community wallets show up as
        # custom rows in the panel.
        # Unknown kinds get tagged "custom" rather than rejected — community
        # wallets show up as custom rows in the panel.
        canonical: WalletKind = kind if kind in KNOWN_KINDS else "custom"
        wallets[kind] = WalletEntry(
            kind=canonical,
            network=str(body.get("network", "")),
            address=str(body.get("address", "")),
            api_token_env=body.get("api_token_env"),
            mode=body.get("mode"),
        )
    return WalletsConfig(
        default_payer=default_payer,
        default_receiver=default_receiver,
        wallets=wallets,
    )


# ---------------------------------------------------------------------------
# Write — minimal TOML emitter (we only write strings, no nesting beyond
# `[<kind>]` tables, no arrays). Standard library has no TOML writer in
# 3.12 and we don't want to add a runtime dep just for this.
# ---------------------------------------------------------------------------


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_wallets_config(cfg: WalletsConfig, path: Path | None = None) -> Path:
    """Serialize `cfg` to TOML and write to disk. Creates parent dir."""
    p = path or DEFAULT_WALLETS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if cfg.default_payer:
        lines.append(f'default_payer = "{_toml_escape(cfg.default_payer)}"')
    if cfg.default_receiver:
        lines.append(f'default_receiver = "{_toml_escape(cfg.default_receiver)}"')
    if lines:
        lines.append("")

    for kind, entry in cfg.wallets.items():
        lines.append(f"[{kind}]")
        lines.append(f'network = "{_toml_escape(entry.network)}"')
        lines.append(f'address = "{_toml_escape(entry.address)}"')
        if entry.api_token_env:
            lines.append(f'api_token_env = "{_toml_escape(entry.api_token_env)}"')
        if entry.mode:
            lines.append(f'mode = "{_toml_escape(entry.mode)}"')
        lines.append("")

    p.write_text("\n".join(lines).rstrip() + "\n")
    return p


def upsert_wallet(entry: WalletEntry, path: Path | None = None) -> WalletsConfig:
    """Read, replace `wallets[kind]`, write back. Returns the new config."""
    cfg = read_wallets_config(path)
    new_wallets = dict(cfg.wallets)
    new_wallets[entry.kind] = entry
    new_cfg = WalletsConfig(
        default_payer=cfg.default_payer or entry.kind,
        default_receiver=cfg.default_receiver,
        wallets=new_wallets,
    )
    write_wallets_config(new_cfg, path)
    return new_cfg


__all__ = [
    "DEFAULT_WALLETS_PATH",
    "KNOWN_KINDS",
    "WalletEntry",
    "WalletKind",
    "WalletsConfig",
    "read_wallets_config",
    "upsert_wallet",
    "write_wallets_config",
]
