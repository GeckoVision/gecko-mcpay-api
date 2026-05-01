"""S13-WALLET-01 — `bb wallet` panel tests.

Coverage:
  - Empty config → all placeholder rows render with health="—".
  - Configured frames + TWITSH → ok / low rows with truncated address.
  - `bb wallet show` end-to-end via CliRunner.
  - `bb wallet test frames` runs in stub mode and prints success.
  - `bb wallet --help` lists all subcommands.
  - TOML round-trip preserves wallet entries.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from click.testing import CliRunner
from gecko_cli.commands.wallet import (
    aggregate_rows,
    has_any_wallet,
    render_wallet_panel,
    wallet_cmd,
)
from gecko_core.wallets.config import (
    WalletEntry,
    WalletsConfig,
    read_wallets_config,
    upsert_wallet,
    write_wallets_config,
)

# ---------------------------------------------------------------------------
# aggregate_rows
# ---------------------------------------------------------------------------


def test_aggregate_rows_empty_config_yields_placeholders() -> None:
    rows = asyncio.run(aggregate_rows(WalletsConfig(), env={}))
    kinds = {r.kind for r in rows}
    # All known kinds (sans "custom") render even with no config.
    assert "frames" in kinds
    assert "twitsh" in kinds
    assert "awal" in kinds
    assert "publish-new" in kinds
    assert "paragraph" in kinds
    # All placeholder rows have health="—".
    assert all(r.health == "—" for r in rows)


def test_aggregate_rows_surfaces_twitsh_from_env_only() -> None:
    rows = asyncio.run(
        aggregate_rows(
            WalletsConfig(),
            env={"TWITSH_WALLET_ADDRESS": "0x7a3eC0FFEE0FEEDD91c1234567890abcdef0D91c"},
        )
    )
    twitsh_row = next(r for r in rows if r.kind == "twitsh")
    assert twitsh_row.health == "ok"
    assert "0x7a" in twitsh_row.address_display
    assert "D91c" in twitsh_row.address_display


def test_aggregate_rows_marks_default_payer() -> None:
    cfg = WalletsConfig(
        default_payer="frames",
        wallets={
            "frames": WalletEntry(
                kind="frames",
                network="solana:mainnet",
                address="9xKpAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaF2Q",
                api_token_env="FRAMES_API_TOKEN",
            )
        },
    )
    rows = asyncio.run(aggregate_rows(cfg, env={}))
    frames_row = next(r for r in rows if r.kind == "frames")
    assert frames_row.is_default_payer is True


# ---------------------------------------------------------------------------
# Render — smoke (renders without raising)
# ---------------------------------------------------------------------------


def test_render_wallet_panel_smoke() -> None:
    cfg = WalletsConfig()
    rows = asyncio.run(aggregate_rows(cfg, env={}))
    panel = render_wallet_panel(rows, cfg)
    # Render to a string buffer to ensure no exceptions in any cell.
    import io

    from rich.console import Console

    buf = io.StringIO()
    Console(file=buf, width=120, force_terminal=False).print(panel)
    out = buf.getvalue()
    assert "Wallets" in out
    assert "frames" in out
    assert "twitsh" in out


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_wallet_show_runs_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gecko_core.wallets.config.DEFAULT_WALLETS_PATH", tmp_path / "wallets.toml")
    runner = CliRunner()
    result = runner.invoke(wallet_cmd, ["show"])
    assert result.exit_code == 0, result.output
    assert "frames" in result.output


def test_wallet_help_lists_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(wallet_cmd, ["--help"])
    assert result.exit_code == 0
    for sub in ("show", "add", "fund", "test"):
        assert sub in result.output


def test_wallet_test_frames_stub_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "stub")
    runner = CliRunner()
    result = runner.invoke(wallet_cmd, ["test", "frames"])
    assert result.exit_code == 0, result.output
    assert "stub charge" in result.output
    assert "frames" in result.output


def test_wallet_test_skips_when_not_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    runner = CliRunner()
    result = runner.invoke(wallet_cmd, ["test", "frames"])
    assert result.exit_code == 0
    assert "skipping" in result.output


# ---------------------------------------------------------------------------
# Config IO
# ---------------------------------------------------------------------------


def test_wallets_toml_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "wallets.toml"
    cfg = WalletsConfig(
        default_payer="frames",
        wallets={
            "frames": WalletEntry(
                kind="frames",
                network="solana:mainnet",
                address="9xKp1234aF2Q",
                api_token_env="FRAMES_API_TOKEN",
            ),
            "twitsh": WalletEntry(
                kind="twitsh",
                network="eip155:8453",
                address="0x7a3e1234D91c",
                api_token_env="TWITSH_API_TOKEN",
            ),
        },
    )
    write_wallets_config(cfg, path)
    loaded = read_wallets_config(path)
    assert loaded.default_payer == "frames"
    assert "frames" in loaded.wallets
    assert loaded.wallets["frames"].address == "9xKp1234aF2Q"
    assert loaded.wallets["twitsh"].api_token_env == "TWITSH_API_TOKEN"


def test_upsert_wallet_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "wallets.toml"
    entry = WalletEntry(
        kind="frames",
        network="solana:mainnet",
        address="9xKp1234aF2Q",
        api_token_env="FRAMES_API_TOKEN",
    )
    cfg = upsert_wallet(entry, path)
    assert path.exists()
    assert cfg.default_payer == "frames"
    assert cfg.wallets["frames"].address == "9xKp1234aF2Q"


def test_has_any_wallet_false_when_missing(tmp_path: Path) -> None:
    assert has_any_wallet(tmp_path / "absent.toml") is False


def test_has_any_wallet_true_after_upsert(tmp_path: Path) -> None:
    path = tmp_path / "wallets.toml"
    upsert_wallet(
        WalletEntry(
            kind="frames",
            network="solana:mainnet",
            address="9xKp1234aF2Q",
        ),
        path,
    )
    assert has_any_wallet(path) is True


# ---------------------------------------------------------------------------
# Doesn't break existing commands
# ---------------------------------------------------------------------------


def test_bb_doctor_still_runs() -> None:
    """`bb wallet` must not perturb `bb doctor` registration."""
    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "doctor" in result.output


def test_bb_cli_help_lists_wallet() -> None:
    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "wallet" in result.output
