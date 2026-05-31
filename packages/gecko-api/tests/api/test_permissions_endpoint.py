"""S26-C tests — GET /v1/permissions + GET /v1/permissions/keys.

Pure FastAPI route tests with TestClient; no Privy network, no DB.
Verifies:
  - Default response is the mock fixture (3 agents, 4-lane coverage)
  - PERMISSION_KEYS echoed verbatim under /keys
  - Wallet-gate downgrades on-chain keys to `pending` when wallet
    is not active (drafts → not_set, deployed → revoked)
  - `?include_wallets=true` without Privy creds returns `not_set`
    rather than the default `pending_sprint_26` (signals "we asked,
    nothing was found")
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from gecko_core.permissions import PERMISSION_KEYS


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build a clean TestClient — no Privy creds in env.

    Tests that need live-Privy behavior monkeypatch is_privy_configured
    directly; that avoids constructing a real PrivyClient.
    """
    monkeypatch.delenv("PRIVY_APP_ID", raising=False)
    monkeypatch.delenv("PRIVY_APP_SECRET", raising=False)
    from gecko_api.main import app

    return TestClient(app)


def test_get_permissions_default_returns_mock_fixture(client: TestClient) -> None:
    """Default call (no include_wallets) returns the 3-agent fixture."""
    resp = client.get("/v1/permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert "agents" in body
    agents = body["agents"]
    assert len(agents) == 3
    lanes = {a["lane"] for a in agents}
    assert lanes == {"paper", "drafts", "deployed"}


def test_get_permissions_lane_defaults_apply(client: TestClient) -> None:
    """Paper lane gets place_trades pending (wallet not active by default)."""
    resp = client.get("/v1/permissions")
    body = resp.json()
    paper = next(a for a in body["agents"] if a["lane"] == "paper")
    # Paper's lane default is "granted" for place_trades, but the
    # wallet-gate downgrades to "pending" when wallet != "active".
    assert paper["permissions"]["place_trades"] == "pending"
    # Off-chain keys are unaffected by the wallet gate.
    assert paper["permissions"]["read_market"] == "granted"
    assert paper["permissions"]["access_oracle"] == "granted"


def test_get_permissions_drafts_lane_denies_everything_on_chain(client: TestClient) -> None:
    """Drafts lane: on-chain keys are `denied` (not `pending`) by lane policy.

    Drafts aren't waiting on a wallet — they're explicitly forbidden from
    on-chain actions regardless of wallet state.
    """
    resp = client.get("/v1/permissions")
    body = resp.json()
    drafts = next(a for a in body["agents"] if a["lane"] == "drafts")
    assert drafts["permissions"]["place_trades"] == "denied"
    assert drafts["permissions"]["move_funds"] == "denied"
    assert drafts["permissions"]["withdraw_vault"] == "denied"
    assert drafts["privyWalletStatus"] == "not_set"


def test_get_permissions_deployed_lane_revoked_wallet(client: TestClient) -> None:
    """Deployed (killed) agents have a revoked wallet + all-denied grid."""
    resp = client.get("/v1/permissions")
    body = resp.json()
    deployed = next(a for a in body["agents"] if a["lane"] == "deployed")
    assert deployed["privyWalletStatus"] == "revoked"
    for key in PERMISSION_KEYS:
        assert deployed["permissions"][key] == "denied"


def test_get_permissions_include_wallets_no_privy_returns_not_set(
    client: TestClient,
) -> None:
    """include_wallets=true but Privy unconfigured → wallet status is not_set.

    Distinguishes "we tried to look up real wallet, nothing there" from
    the default "we haven't tried, Sprint 26 hasn't shipped" framing.
    """
    resp = client.get("/v1/permissions?include_wallets=true")
    body = resp.json()
    paper = next(a for a in body["agents"] if a["lane"] == "paper")
    assert paper["privyWalletStatus"] == "not_set"


def test_get_permissions_keys_echoes_canonical_tuple(client: TestClient) -> None:
    """/keys returns the PERMISSION_KEYS tuple in canonical order."""
    resp = client.get("/v1/permissions/keys")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"keys": list(PERMISSION_KEYS)}


def test_response_uses_camelcase_aliases(client: TestClient) -> None:
    """Frontend Zod schema expects agentId / agentName / privyWalletStatus."""
    resp = client.get("/v1/permissions")
    body = resp.json()
    a = body["agents"][0]
    assert "agentId" in a
    assert "agentName" in a
    assert "privyWalletStatus" in a
    # Python-side snake_case must NOT leak.
    assert "agent_id" not in a
    assert "agent_name" not in a
    assert "privy_wallet_status" not in a
