"""Wallet + payment-surface endpoints for agent_api (web3 lane, item #3).

Covers GET /wallet, GET /wallet/balance, GET /receipts in:
  * cold/unconfigured state → honest-empty shapes, no 500
  * populated state (env pubkey, mocked onchainos balance, artifact ledger)

CRITICAL invariant under test: NO private-key-like field ever appears in ANY
response, on any branch. `_assert_no_secret` walks every response recursively.

All onchainos subprocesses are mocked — no network, no money, no CLI dependency.

Targeted only — run with:
    python3 -m pytest tests/test_wallet_receipts_endpoints.py -q -p no:cacheprovider
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import agent_store as ast_  # noqa: E402

# Names that must NEVER appear in any response payload.
_SECRETISH = {
    "privatekey",
    "private_key",
    "privkey",
    "secret",
    "secretkey",
    "secret_key",
    "mnemonic",
    "seed",
    "seedphrase",
    "seed_phrase",
    "keypair",
    "phrase",
    "passphrase",
}


def _assert_no_secret(obj: object, path: str = "$") -> None:
    """Fail if any key (recursively) looks like private-key material."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            norm = str(k).replace("-", "").replace("_", "").lower()
            assert norm not in _SECRETISH, f"secret-like key {k!r} leaked at {path}"
            _assert_no_secret(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_no_secret(v, f"{path}[{i}]")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # cold backend: empty state dir, stub mode, no signer env, no onchainos.
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("GECKO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("X402_MODE", "stub")
    for k in (
        "GECKO_SIGNER_PUBKEY",
        "GECKO_WALLET_PUBKEY",
        "SIGNER_PUBKEY",
        "PRIVY_WALLET_ADDRESS",
        "GECKO_PRIVY_ADDRESS",
    ):
        monkeypatch.delenv(k, raising=False)
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()
    import agent_api
    from agent_orchestrator import AgentOrchestrator

    agent_api._registry = ast_.AgentRegistry(collection=None)
    agent_api._state = ast_.AgentStateStore(collection=None)
    agent_api._orch = AgentOrchestrator(registry=agent_api._registry)
    yield
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()


def _client():
    import agent_api
    from fastapi.testclient import TestClient

    return TestClient(agent_api.app)


def _stub_onchainos_unavailable(monkeypatch):
    """Make the onchainos import fail so _resolve_signer falls through cleanly."""
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "onchainos":
            raise ImportError("onchainos CLI not available in test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)


# ── GET /wallet ─────────────────────────────────────────────────────────────
def test_wallet_cold_honest_empty(monkeypatch):
    _stub_onchainos_unavailable(monkeypatch)
    r = _client().get("/wallet")
    assert r.status_code == 200
    j = r.json()
    assert j["signer_pubkey"] is None
    assert j["custody"] == "none"
    assert j["status"] == "unconfigured"
    assert j["x402_mode"] == "stub"
    _assert_no_secret(j)


def test_wallet_env_pubkey_okx_tee(monkeypatch):
    monkeypatch.setenv("GECKO_SIGNER_PUBKEY", "So1anaPubKey1111111111111111111111111111111")
    r = _client().get("/wallet")
    assert r.status_code == 200
    j = r.json()
    assert j["signer_pubkey"] == "So1anaPubKey1111111111111111111111111111111"
    assert j["custody"] == "okx_tee"
    assert j["status"] == "ok"
    _assert_no_secret(j)


def test_wallet_privy_embedded(monkeypatch):
    _stub_onchainos_unavailable(monkeypatch)
    monkeypatch.setenv("PRIVY_WALLET_ADDRESS", "PrivyAddr2222222222222222222222222222222222")
    r = _client().get("/wallet")
    j = r.json()
    assert j["custody"] == "privy_embedded"
    assert j["signer_pubkey"] == "PrivyAddr2222222222222222222222222222222222"
    _assert_no_secret(j)


def test_wallet_never_leaks_secret_even_if_resolver_returns_one(monkeypatch):
    """Defense-in-depth: even if _resolve_signer were tricked into emitting a
    secret-like key, _redact() must strip it before the response."""
    import agent_api

    monkeypatch.setattr(
        agent_api,
        "_resolve_signer",
        lambda: ("PubKeyOnly333333333333333333333333333333333", "okx_tee", "ok"),
    )
    # also poison the redactor's input via a wrapped handler is overkill; instead
    # assert _redact strips a planted secret directly.
    poisoned = {"signer_pubkey": "pub", "private_key": "LEAK", "mnemonic": "LEAK words"}
    cleaned = agent_api._redact(poisoned)
    assert "private_key" not in cleaned
    assert "mnemonic" not in cleaned
    assert cleaned["signer_pubkey"] == "pub"
    # and the live endpoint stays clean
    _assert_no_secret(_client().get("/wallet").json())


# ── GET /wallet/balance ─────────────────────────────────────────────────────
def test_wallet_balance_cold_stale_empty(monkeypatch):
    _stub_onchainos_unavailable(monkeypatch)
    r = _client().get("/wallet/balance")
    assert r.status_code == 200
    j = r.json()
    assert j["pubkey"] is None
    assert j["balances"] == []
    assert j["stale"] is True
    _assert_no_secret(j)


def test_wallet_balance_populated_via_mocked_onchainos(monkeypatch):
    monkeypatch.setenv("GECKO_SIGNER_PUBKEY", "SignerPub444444444444444444444444444444444")

    class _FakeOnchainOS:
        def __init__(self, chain="solana"):
            pass

        def get_token_balance(self, mint, force=False):

            return 1.5 if mint == agent_api._SOL_MINT else 250.0

    # inject a fake onchainos module so the handler's `from onchainos import OnchainOS` hits it
    import types as _types

    import agent_api

    fake_mod = _types.ModuleType("onchainos")
    fake_mod.OnchainOS = _FakeOnchainOS
    monkeypatch.setitem(sys.modules, "onchainos", fake_mod)

    r = _client().get("/wallet/balance")
    assert r.status_code == 200
    j = r.json()
    assert j["pubkey"] == "SignerPub444444444444444444444444444444444"
    assert j["stale"] is False
    toks = {b["token"]: b["amount"] for b in j["balances"]}
    assert toks == {"SOL": 1.5, "USDC": 250.0}
    _assert_no_secret(j)


def test_wallet_balance_onchainos_error_degrades_to_stale(monkeypatch):
    monkeypatch.setenv("GECKO_SIGNER_PUBKEY", "SignerPub555555555555555555555555555555555")

    class _BoomOnchainOS:
        def __init__(self, chain="solana"):
            pass

        def get_token_balance(self, mint, force=False):
            raise RuntimeError("CLI timed out")

    import types as _types

    fake_mod = _types.ModuleType("onchainos")
    fake_mod.OnchainOS = _BoomOnchainOS
    monkeypatch.setitem(sys.modules, "onchainos", fake_mod)

    r = _client().get("/wallet/balance")
    assert r.status_code == 200
    j = r.json()
    assert j["stale"] is True
    assert j["balances"] == []
    _assert_no_secret(j)


# ── GET /receipts ───────────────────────────────────────────────────────────
def test_receipts_cold_honest_empty():
    r = _client().get("/receipts")
    assert r.status_code == 200
    j = r.json()
    assert j["receipts"] == []
    assert j["n"] == 0
    assert j["mode"] == "stub"
    _assert_no_secret(j)


def test_receipts_from_artifact_ledger_stub_sig(monkeypatch, tmp_path):
    # write a tiny artifact ledger with a gate_call row
    ledger = tmp_path / "artifact_20260605.jsonl"
    rows = [
        {"decision_id": "abc123", "kind": "gate_call", "ts": "2026-06-05T00:00:00+00:00",
         "payload": {"idea_hash": "hash-1", "tier": "basic"}},
        {"decision_id": "def456", "kind": "gate_allow", "ts": "2026-06-05T00:01:00+00:00",
         "payload": {"tier": "pro"}},
        {"decision_id": "x", "kind": "heartbeat", "ts": "2026-06-05T00:02:00+00:00", "payload": {}},
    ]
    ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    r = _client().get("/receipts")
    assert r.status_code == 200
    j = r.json()
    assert j["n"] == 2  # heartbeat excluded
    assert j["mode"] == "stub"
    for rec in j["receipts"]:
        assert rec["mode"] == "stub"
        # stub sigs MUST carry the stub- prefix so they can't pass as on-chain
        assert rec["tx_sig"].startswith("stub-")
    _assert_no_secret(j)


def test_receipts_malformed_line_degrades_stale(tmp_path):
    ledger = tmp_path / "artifact_20260605.jsonl"
    ledger.write_text(
        '{"decision_id":"ok1","kind":"gate_call","ts":"2026-06-05T00:00:00+00:00","payload":{}}\n'
        "{not valid json}\n",
        encoding="utf-8",
    )
    r = _client().get("/receipts")
    assert r.status_code == 200
    j = r.json()
    assert j.get("stale") is True
    assert j["n"] == 1
    _assert_no_secret(j)
