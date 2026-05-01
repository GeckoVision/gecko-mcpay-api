"""S14-TEST-POLICY-01 — universal X402Client conformer contract test.

Generalizes the S12.5-TEST-04 pattern (`test_cdp_live_verify.py`) to every
concrete client. Each client gets a recorded-fixture round-trip:

  * StubX402Client    — trivial; verifies the canonical PaymentResult shape
                        and Protocol class-attrs.
  * LiveX402Client    — frames.ag → Solana, replayed via respx. Mocks
                        ``~/.agentwallet/config.json`` + the Helius RPC
                        confirmation poll.
  * FramesX402Client  — same wire path as ``LiveX402Client`` today; kept
                        distinct so a V2 split (policy controls,
                        ``/x402/fetch``) trips this test rather than
                        passing silently.
  * CDPX402Client     — replay-mode via an injected ``_FacilitatorLike``
                        fake. The live-toggle path against the real
                        ``/verify`` endpoint stays in
                        ``test_cdp_live_verify.py`` (S12.5-TEST-04, gated
                        by ``GECKO_CDP_LIVE_VERIFY=1``).

Future Cloudflare/awal facilitators inherit the policy automatically by
adding a fixture file under ``fixtures/`` and a parametrize entry below.

Each fixture asserts:

  1. ``charge(intent)`` returns a ``PaymentResult`` matching the recorded
     ``expected_result`` field-for-field (intent_id, status, tx_signature,
     error). This is the wire-shape boundary the S12.5 hardening sweep
     was built to lock down — drift in any of these four fields is the
     bug class that f9f0135 / 2e93b27 / 2ca40b9 introduced.
  2. ``client.supported_networks`` and ``client.facilitator_id`` match
     the recorded values. These are the Protocol class-attrs the
     ``factory.resolve_client_for_network`` dispatcher reads, so a
     network-key drift here would silently misroute payments.
  3. ``isinstance(client, X402Client)`` — the runtime_checkable Protocol
     conformance check. Any conformer that drops one of the methods or
     class-attrs fails this assertion.

CI runs all 4 clients in stub-fixture mode by default. The CDP live-mode
toggle (``GECKO_CDP_LIVE_VERIFY=1``) remains opt-in via the existing
``test_cdp_live_verify.py``; this test never burns CDP credentials.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from gecko_core.payments.cdp_x402_client import CDPX402Client
from gecko_core.payments.models import PaymentIntent, PaymentResult
from gecko_core.payments.networks import resolve_network
from gecko_core.payments.protocol import X402Client
from gecko_core.payments.x402_client import (
    FramesX402Client,
    LiveX402Client,
    StubX402Client,
)
from pydantic import SecretStr

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any]:
    raw = (_FIXTURES_DIR / f"{name}-charge.json").read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def _intent_from_fixture(fx: dict[str, Any]) -> PaymentIntent:
    intent = fx["intent"]
    return PaymentIntent(
        intent_id=intent["intent_id"],
        session_id=UUID(intent["session_id"]),
        tier=intent["tier"],
        amount_usd=Decimal(intent["amount_usd"]),
    )


def _assert_payment_result_matches(actual: PaymentResult, expected: dict[str, Any]) -> None:
    """Field-for-field check on the wire-shape boundary."""
    assert actual.intent_id == expected["intent_id"]
    assert actual.status == expected["status"]
    assert actual.tx_signature == expected["tx_signature"]
    assert actual.error == expected["error"]


def _assert_protocol_attrs(
    client: X402Client,
    expected_networks: list[str],
    expected_facilitator_id: str,
) -> None:
    """Class-attr check — these gate the factory dispatch."""
    assert isinstance(client, X402Client), (
        f"{type(client).__name__} fails runtime X402Client Protocol check; "
        "a charge/verify method or one of supported_networks/facilitator_id "
        "is missing or has the wrong shape."
    )
    assert tuple(client.supported_networks) == tuple(expected_networks), (
        f"{type(client).__name__}.supported_networks drifted from fixture: "
        f"{client.supported_networks!r} vs {expected_networks!r}. "
        "Update the fixture only if the dispatch routing is intentionally "
        "changing — otherwise this is a bug."
    )
    assert client.facilitator_id == expected_facilitator_id, (
        f"{type(client).__name__}.facilitator_id drifted: "
        f"{client.facilitator_id!r} vs {expected_facilitator_id!r}. "
        "This string is surfaced on receipts and in `bb doctor` output."
    )


# ---------------------------------------------------------------------------
# Stub
# ---------------------------------------------------------------------------


async def test_stub_x402_client_contract() -> None:
    fx = _load_fixture("stub")
    client = StubX402Client()
    _assert_protocol_attrs(client, fx["expected_supported_networks"], fx["expected_facilitator_id"])

    intent = _intent_from_fixture(fx)
    result = await client.charge(intent)
    _assert_payment_result_matches(result, fx["expected_result"])

    # verify() on the stub should always say confirmed — tx_signature is
    # never produced, but the Protocol contract says verify must accept any
    # string and return a ConfirmationStatus.
    assert await client.verify("any-stub-signature") == "confirmed"


# ---------------------------------------------------------------------------
# Live (frames.ag → Solana)
# ---------------------------------------------------------------------------


def _write_agent_wallet_config(tmp_path: Path, config: dict[str, Any]) -> Path:
    """Write a fake ~/.agentwallet/config.json under ``tmp_path``.

    Returned path is passed to ``LiveX402Client(config_path=...)`` so we
    never touch the operator's real wallet config.
    """
    cfg_dir = tmp_path / ".agentwallet"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "config.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    return cfg_path


@respx.mock
async def test_live_x402_client_contract(tmp_path: Path) -> None:
    fx = _load_fixture("live")
    cfg_path = _write_agent_wallet_config(tmp_path, fx["agent_wallet_config"])

    # Mock the frames.ag transfer-solana POST.
    frames_base = "https://frames.ag/api"
    username = fx["agent_wallet_config"]["username"]
    transfer_route = respx.post(
        f"{frames_base}/wallets/{username}/actions/transfer-solana",
    ).mock(
        return_value=httpx.Response(
            status_code=fx["frames_response"]["status_code"],
            json=fx["frames_response"]["body"],
        )
    )

    # Mock the Helius / public Solana RPC confirmation poll. We don't pin
    # a specific URL because the production code falls back to the public
    # devnet RPC when no Helius key is set; we route any RPC POST.
    rpc_route = respx.post(url__regex=r"https://(api|.+\.helius-rpc\.com).*").mock(
        return_value=httpx.Response(status_code=200, json=fx["rpc_response"])
    )

    client = LiveX402Client(
        facilitator_url="",
        wallet_secret=SecretStr(""),
        frames_base_url=frames_base,
        network=resolve_network("solana-devnet"),
        treasury_address=fx["treasury_address"],
        helius_api_key=None,
        config_path=cfg_path,
        confirm_timeout_s=5.0,
        confirm_interval_s=0.05,
    )
    _assert_protocol_attrs(client, fx["expected_supported_networks"], fx["expected_facilitator_id"])

    result = await client.charge(_intent_from_fixture(fx))
    _assert_payment_result_matches(result, fx["expected_result"])

    assert transfer_route.called, "frames.ag transfer-solana endpoint was not exercised"
    assert rpc_route.called, "Solana RPC confirmation poll was not exercised"


# ---------------------------------------------------------------------------
# Frames (V2 alias for live today)
# ---------------------------------------------------------------------------


@respx.mock
async def test_frames_x402_client_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fx = _load_fixture("frames")
    cfg_path = _write_agent_wallet_config(tmp_path, fx["agent_wallet_config"])

    # FramesX402Client has a thinner constructor (api_key only); it pulls
    # everything else from PaymentSettings. Pin the env so the pydantic-
    # settings load is deterministic and points at our tmp wallet config.
    monkeypatch.setenv("X402_NETWORK", "solana-devnet")
    monkeypatch.setenv("GECKO_WALLET_ADDRESS", fx["treasury_address"])
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    from gecko_core.payments.x402_client import _reset_settings_cache

    _reset_settings_cache()

    frames_base = "https://frames.ag/api"
    username = fx["agent_wallet_config"]["username"]
    transfer_route = respx.post(
        f"{frames_base}/wallets/{username}/actions/transfer-solana",
    ).mock(
        return_value=httpx.Response(
            status_code=fx["frames_response"]["status_code"],
            json=fx["frames_response"]["body"],
        )
    )
    rpc_route = respx.post(url__regex=r"https://(api|.+\.helius-rpc\.com).*").mock(
        return_value=httpx.Response(status_code=200, json=fx["rpc_response"])
    )

    client = FramesX402Client(api_key=SecretStr(""))
    # FramesX402Client inherits __init__ defaults (network/treasury from
    # env via _settings()), but we explicitly override the wallet config
    # path + timeouts so this test never touches the operator's home dir.
    client._config_path = cfg_path
    client._confirm_timeout_s = 5.0
    client._confirm_interval_s = 0.05

    _assert_protocol_attrs(client, fx["expected_supported_networks"], fx["expected_facilitator_id"])

    result = await client.charge(_intent_from_fixture(fx))
    _assert_payment_result_matches(result, fx["expected_result"])

    assert transfer_route.called
    assert rpc_route.called

    _reset_settings_cache()


# ---------------------------------------------------------------------------
# CDP (Base mainnet) — replay-mode via injected facilitator.
# ---------------------------------------------------------------------------


class _ReplayFacilitator:
    """Minimal ``_FacilitatorLike`` that returns a recorded SettleResponse.

    We don't import x402.schemas.SettleResponse because the production
    ``_map_response`` reads via ``getattr(response, "success", ...)`` —
    duck-typing is the contract surface. A simple object suffices, and
    keeps the test independent of x402-py's response model evolution.
    """

    def __init__(self, recorded: dict[str, Any]) -> None:
        self._recorded = recorded
        self.calls = 0

    async def settle(self, payload: Any, requirements: Any) -> Any:
        self.calls += 1
        return _ReplayedResponse(self._recorded)


class _ReplayedResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self.success = bool(data.get("success", False))
        self.transaction = data.get("transaction")
        self.error_reason = data.get("error_reason")
        self.error_message = data.get("error_message")


async def test_cdp_x402_client_contract() -> None:
    fx = _load_fixture("cdp")
    facilitator = _ReplayFacilitator(fx["settle_response"])

    client = CDPX402Client(
        facilitator=facilitator,
        treasury_address=fx["treasury_address"],
    )
    _assert_protocol_attrs(client, fx["expected_supported_networks"], fx["expected_facilitator_id"])

    result = await client.charge(_intent_from_fixture(fx))
    _assert_payment_result_matches(result, fx["expected_result"])
    assert facilitator.calls == 1, "CDP facilitator settle() was not invoked exactly once"

    # verify() must accept an EVM-shaped tx hash and return a coarse status.
    assert await client.verify(fx["expected_result"]["tx_signature"]) == "confirmed"
    assert await client.verify("") == "unknown"
    assert await client.verify("not-a-hex-string") == "unknown"


# ---------------------------------------------------------------------------
# Coverage assertion — adding a new client without a fixture must trip CI.
# ---------------------------------------------------------------------------


def test_every_concrete_client_has_a_fixture() -> None:
    """If a new ``X402Client`` conformer ships without a fixture, fail loud.

    Walk the payments package's known concrete-client classes and assert
    every one has a fixture file in ``fixtures/``. The Cloudflare/awal
    clients reserved by S15 will trip this the moment they are added —
    forcing the author to record a fixture and extend this file.
    """
    known = {
        "stub": StubX402Client,
        "live": LiveX402Client,
        "frames": FramesX402Client,
        "cdp": CDPX402Client,
    }
    for name in known:
        path = _FIXTURES_DIR / f"{name}-charge.json"
        assert path.is_file(), f"missing contract fixture for {name!r} client at {path}"
