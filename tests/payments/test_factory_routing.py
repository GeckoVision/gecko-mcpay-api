"""S12-CDP-02 — network-aware factory routing.

Asserts the (network, mode) → client class table:

| X402_NETWORK            | X402_MODE | client class       |
|-------------------------|-----------|--------------------|
| solana-devnet           | live      | LiveX402Client     |
| solana-mainnet          | live      | LiveX402Client     |
| solana-devnet           | frames    | FramesX402Client   |
| eip155:8453             | live      | CDPX402Client      |
| base-mainnet            | live      | CDPX402Client      |
| base-sepolia            | live      | CDPX402Client      |
| <any>                   | stub      | StubX402Client     |
| ethereum-mainnet        | live      | ValueError         |

Tests run entirely off env + the factory; no network IO.
"""

from __future__ import annotations

import pytest
from gecko_core.payments import (
    CDPX402Client,
    FramesX402Client,
    LiveX402Client,
    NetworkKind,
    StubX402Client,
    facilitator_id_for_network,
    resolve_client_for_network,
)
from gecko_core.payments.x402_client import _reset_settings_cache, _resolve_network_kind


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with a fresh settings cache + clean payment env."""
    for k in (
        "X402_MODE",
        "X402_NETWORK",
        "X402_FACILITATOR_URL",
        "GECKO_WALLET_ADDRESS",
        "GECKO_WALLET_ADDRESS_BASE",
        "CDP_API_KEY_ID",
        "CDP_API_KEY_SECRET",
        "FRAMES_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    _reset_settings_cache()
    yield
    _reset_settings_cache()


# ---------------------------------------------------------------------------
# NetworkKind resolution — pure function, no IO.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("solana-mainnet", NetworkKind.SOLANA_MAINNET),
        ("solana-devnet", NetworkKind.SOLANA_DEVNET),
        ("base-mainnet", NetworkKind.BASE_MAINNET),
        ("base-sepolia", NetworkKind.BASE_SEPOLIA),
        ("eip155:8453", NetworkKind.BASE_MAINNET),
        ("eip155:84532", NetworkKind.BASE_SEPOLIA),
        # Solana CAIP-2 by USDC mint
        ("solana:EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", NetworkKind.SOLANA_MAINNET),
        ("solana:4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", NetworkKind.SOLANA_DEVNET),
        # Negatives
        ("eip155:1", NetworkKind.UNKNOWN),
        ("solana:badmint", NetworkKind.UNKNOWN),
        ("ethereum-mainnet", NetworkKind.UNKNOWN),
        ("", NetworkKind.UNKNOWN),
    ],
)
def test_network_kind_resolution(value: str, expected: NetworkKind) -> None:
    assert _resolve_network_kind(value) is expected


# ---------------------------------------------------------------------------
# Factory routing
# ---------------------------------------------------------------------------


def test_solana_mainnet_routes_to_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    client = resolve_client_for_network("solana-mainnet")
    assert isinstance(client, LiveX402Client)


def test_solana_devnet_routes_to_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    client = resolve_client_for_network("solana-devnet")
    assert isinstance(client, LiveX402Client)


def test_solana_with_frames_mode_routes_to_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "frames")
    _reset_settings_cache()
    client = resolve_client_for_network("solana-mainnet")
    assert isinstance(client, FramesX402Client)


def test_base_mainnet_caip2_routes_to_cdp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    client = resolve_client_for_network("eip155:8453")
    assert isinstance(client, CDPX402Client)


def test_base_mainnet_friendly_routes_to_cdp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    client = resolve_client_for_network("base-mainnet")
    assert isinstance(client, CDPX402Client)


def test_base_sepolia_routes_to_cdp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    client = resolve_client_for_network("base-sepolia")
    assert isinstance(client, CDPX402Client)


def test_stub_mode_short_circuits_regardless_of_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("X402_MODE", "stub")
    _reset_settings_cache()
    for net in ("solana-mainnet", "base-mainnet", "eip155:8453", ""):
        assert isinstance(resolve_client_for_network(net), StubX402Client), net


def test_unknown_network_raises_with_value_in_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    with pytest.raises(ValueError, match="ethereum-mainnet"):
        resolve_client_for_network("ethereum-mainnet")


def test_explicit_mode_override_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "stub")
    _reset_settings_cache()
    # Explicit live override → real Solana client even with stub env.
    client = resolve_client_for_network("solana-mainnet", mode="live")
    assert isinstance(client, LiveX402Client)


# ---------------------------------------------------------------------------
# facilitator_id_for_network — drives `bb doctor`.
# ---------------------------------------------------------------------------


def test_facilitator_id_stub_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "stub")
    _reset_settings_cache()
    # Stub short-circuits regardless of network.
    assert facilitator_id_for_network("solana-mainnet") == "stub"
    assert facilitator_id_for_network("base-mainnet") == "stub"


def test_facilitator_id_solana(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    assert facilitator_id_for_network("solana-mainnet") == "frames-solana"
    assert facilitator_id_for_network("solana-devnet") == "frames-solana"


def test_facilitator_id_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    assert facilitator_id_for_network("base-mainnet") == "cdp-base"
    assert facilitator_id_for_network("eip155:8453") == "cdp-base"
    assert facilitator_id_for_network("eip155:84532") == "cdp-base"


def test_facilitator_id_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    assert facilitator_id_for_network("ethereum-mainnet") == "unknown"
    assert facilitator_id_for_network(None) == "unknown"


# ---------------------------------------------------------------------------
# get_client mode dispatch — ensure cdp mode works.
# ---------------------------------------------------------------------------


def test_get_client_cdp_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from gecko_core.payments import get_client

    monkeypatch.setenv("X402_MODE", "cdp")
    _reset_settings_cache()
    client = get_client()
    assert isinstance(client, CDPX402Client)


# ---------------------------------------------------------------------------
# S13-PAY-01 — reserved Cloudflare slot.
# ---------------------------------------------------------------------------


def test_cloudflare_slot_raises_not_implemented(monkeypatch: pytest.MonkeyPatch) -> None:
    """``http-cloudflare`` is reserved for Sprint 15 and must fail fast.

    Generic ``KeyError`` / ``ValueError`` would mask the deliberate "not
    yet implemented" intent. The error message must name Sprint 15.
    """
    from gecko_core.payments.factory import CLOUDFLARE_NETWORK_ID

    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()

    with pytest.raises(NotImplementedError, match="Sprint 15"):
        resolve_client_for_network(CLOUDFLARE_NETWORK_ID)


def test_cloudflare_slot_short_circuited_in_stub_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stub mode wins over the reserved slot — dev/CI never crash."""
    from gecko_core.payments.factory import CLOUDFLARE_NETWORK_ID

    monkeypatch.setenv("X402_MODE", "stub")
    _reset_settings_cache()
    assert isinstance(resolve_client_for_network(CLOUDFLARE_NETWORK_ID), StubX402Client)


def test_cloudflare_facilitator_id_in_live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """``facilitator_id_for_network`` reports the Cloudflare slot explicitly."""
    from gecko_core.payments.factory import CLOUDFLARE_NETWORK_ID

    monkeypatch.setenv("X402_MODE", "live")
    _reset_settings_cache()
    assert facilitator_id_for_network(CLOUDFLARE_NETWORK_ID) == "http-cloudflare"


def test_factory_module_exports_resolve_client_for_network() -> None:
    """The factory module is the canonical home for the resolver."""
    from gecko_core.payments import factory

    assert hasattr(factory, "resolve_client_for_network")
    assert hasattr(factory, "facilitator_id_for_network")
    assert hasattr(factory, "CLOUDFLARE_NETWORK_ID")
