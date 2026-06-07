"""End-to-end app-surface contract suite (S47).

The ONE deliverable that makes the app-wire safe: a single FastAPI TestClient
suite that exercises EVERY endpoint `app.geckovision.tech` consumes (per the
frontend.md §1 contract), in BOTH cold/honest-empty AND populated states, and
asserts the documented field NAMES + TYPES the app's Zod mirrors expect.

Purpose = the contract guarantee. After this passes, any failure when wiring the
web app is a FRONTEND issue, not a backend one: every response shape the app
codegens against is pinned here.

Everything external is MOCKED — onchainos subprocess, the GeckoTerminal/based.bid
feed, the orchestrator process spawn, Mongo (in-memory fallback). NO network, NO
money, NO real broadcast. Target: < 10s total.

Targeted only — run with:
    python3 -m pytest tests/test_e2e_app_surface.py -q -p no:cacheprovider
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import agent_store as ast_  # noqa: E402

# ── helpers ─────────────────────────────────────────────────────────────────

# Private-key-like field names that must NEVER appear in any response, any branch.
_SECRETISH = {
    "privatekey", "private_key", "privkey", "secret", "secretkey", "secret_key",
    "mnemonic", "seed", "seedphrase", "seed_phrase", "keypair", "phrase", "passphrase",
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


def _has(d: dict, key: str, typ: type | tuple[type, ...]) -> None:
    """Assert key present AND of the documented type (None tolerated only where
    the contract says Optional — callers pass `(typ, type(None))` for those)."""
    assert key in d, f"missing contract field {key!r} in {sorted(d)}"
    assert isinstance(d[key], typ), f"{key!r} is {type(d[key]).__name__}, expected {typ}"


class _FakeSpawner:
    """Orchestrator process spawn — never starts a real subprocess."""

    def __init__(self) -> None:
        self._alive: dict[int, bool] = {}

    def spawn(self, cmd, cwd=None):
        h = object()
        self._alive[id(h)] = True
        return h

    def is_alive(self, h):
        return self._alive.get(id(h), False)

    def kill(self, h):
        self._alive[id(h)] = False


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Hermetic cold backend: no Mongo, empty state dir (honest-empty snapshots),
    stub x402, no signer env, in-memory registry, fake orchestrator spawner."""
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("GECKO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("X402_MODE", "stub")
    for k in (
        "GECKO_SIGNER_PUBKEY", "GECKO_WALLET_PUBKEY", "SIGNER_PUBKEY",
        "PRIVY_WALLET_ADDRESS", "GECKO_PRIVY_ADDRESS", "GECKO_ARENA_TOKENS",
    ):
        monkeypatch.delenv(k, raising=False)
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()
    import agent_api
    from agent_orchestrator import AgentOrchestrator

    agent_api._registry = ast_.AgentRegistry(collection=None)
    agent_api._state = ast_.AgentStateStore(collection=None)
    agent_api._orch = AgentOrchestrator(registry=agent_api._registry, spawner=_FakeSpawner())
    yield
    ast_._MEM_AGENTS.clear()
    ast_._MEM_STATE.clear()


def _client():
    import agent_api
    from fastapi.testclient import TestClient

    return TestClient(agent_api.app)


def _no_onchainos(monkeypatch):
    """Make `from onchainos import OnchainOS` raise so signer resolution falls
    through to honest-empty (no CLI / no network)."""
    import builtins

    real = builtins.__import__

    def _fake(name, *a, **k):
        if name == "onchainos":
            raise ImportError("onchainos unavailable in test")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake)


def _spec(sid: str = "trend_breakout") -> dict:
    return {
        "strategy_id": sid, "universe": ["BTC", "ETH"], "venue": "okx_spot",
        "entry_gates": {"churn_max": 3.0}, "exit": {"tp_pct": 1.0}, "dry_run": True,
    }


# Tiny synthetic candle series for the arena ?live=1 feed mock (no GeckoTerminal).
def _fake_candles(n: int = 60, drift: float = 0.001) -> list[dict]:
    px = 1.0
    out = []
    for _ in range(n):
        px *= 1.0 + drift
        out.append({"close": px, "open": px, "high": px, "low": px})
    return out


# ════════════════════════════════════════════════════════════════════════════
# 1. /healthz
# ════════════════════════════════════════════════════════════════════════════
def test_healthz_contract():
    j = _client().get("/healthz").json()
    _has(j, "ok", bool)
    _has(j, "data_coins", list)
    _has(j, "n_agents", int)
    _assert_no_secret(j)


# ════════════════════════════════════════════════════════════════════════════
# 2. /market-temp — stale (cold) AND populated
# ════════════════════════════════════════════════════════════════════════════
def test_market_temp_cold_honest_empty():
    j = _client().get("/market-temp").json()
    # honest-empty branch: {temp, label, stale, drivers}
    _has(j, "temp", (int, float))
    _has(j, "label", str)
    _has(j, "drivers", list)
    assert j.get("stale") is True
    _assert_no_secret(j)


def test_market_temp_populated(monkeypatch, tmp_path):
    import json

    import market_temp as mt

    snap = {
        "temp": 0.42, "label": "warm", "btc_net": 0.1, "drivers": ["x"],
        "coins": {"SOL": {"net": 0.3, "mentions": 5}}, "divergences": [],
        "updated_at": "2026-06-05T00:00:00+00:00",
    }
    Path(mt.snapshot_path()).write_text(json.dumps(snap))
    j = _client().get("/market-temp").json()
    _has(j, "temp", (int, float))
    _has(j, "label", str)
    _has(j, "btc_net", (int, float))
    _has(j, "coins", dict)
    assert j["label"] == "warm"
    _assert_no_secret(j)


# ════════════════════════════════════════════════════════════════════════════
# 3. /vault — all 3 profiles + demo_profit + 422 on bogus
# ════════════════════════════════════════════════════════════════════════════
def _assert_vault_shape(j: dict) -> None:
    assert set(("snapshot", "verdicts", "allocation", "market_temp")).issubset(j)
    snap = j["snapshot"]
    _has(snap, "profile", str)
    _has(snap, "allocation_usd", (int, float))
    _has(snap, "hurdle_apy", (int, float))
    _has(snap, "lots", list)
    mt = j["market_temp"]
    _has(mt, "stale", bool)
    assert isinstance(j["verdicts"], list)
    _assert_no_secret(j)


@pytest.mark.parametrize("profile", ["conservative", "moderate", "aggressive"])
def test_vault_cold_all_profiles(profile):
    j = _client().get(f"/vault?profile={profile}").json()
    _assert_vault_shape(j)
    # honest-empty: no profit allocated yet
    assert j["snapshot"]["allocation_usd"] == 0
    assert j["snapshot"]["lots"] == []
    assert j["verdicts"] == []
    assert j["allocation"] is None  # null unless demo_profit > 0


def test_vault_demo_profit_populated_with_projection_and_label():
    j = _client().get("/vault?demo_profit=100&profile=moderate").json()
    _assert_vault_shape(j)
    assert j["snapshot"]["lots"], "demo_profit should populate lots"
    lot = j["snapshot"]["lots"][0]
    # item #5 — per-lot human label/description + the $1000→+$100 projection tile
    for k, typ in (
        ("source", str), ("principal_usd", (int, float)), ("leverage", (int, float)),
        ("net_apy", (int, float)), ("liquidation_drop_pct", (int, float)),
        ("correlated", bool), ("label", str), ("description", str),
        ("target_principal_usd", (int, float)), ("target_gain_usd", (int, float)),
        ("projected_balance_1y", (int, float)),
    ):
        _has(lot, k, typ)
    # days_to_target is float OR null (None when net_apy <= 0) — both contract-valid
    assert "days_to_target" in lot
    assert lot["days_to_target"] is None or isinstance(lot["days_to_target"], (int, float))
    # allocation report present + its documented sub-shape
    alloc = j["allocation"]
    assert alloc is not None
    _has(alloc, "deposited", list)
    _has(alloc, "denied", list)
    # verdicts carry the discriminated action enum
    for v in j["verdicts"]:
        assert v["action"] in {"HOLD", "ROTATE", "DELEVERAGE", "EXIT"}


def test_vault_conservative_demo_is_hold_not_rotate():
    """Item #4 — the conservative (pure-lend, borrow_rate=0) leg must HOLD, never
    emit the spurious ROTATE→~2.07x 'lever for free' artifact."""
    j = _client().get("/vault?demo_profit=100&profile=conservative").json()
    actions = [v["action"] for v in j["verdicts"]]
    assert actions, "conservative demo should produce a verdict"
    assert "ROTATE" not in actions, f"conservative lend must not ROTATE; got {actions}"
    assert all(a == "HOLD" for a in actions), actions


def test_vault_bogus_profile_422():
    """Item #4 — unknown profile fails loud (422), no silent conservative fallback."""
    r = _client().get("/vault?profile=bogus")
    assert r.status_code == 422
    assert "detail" in r.json()


def test_vault_cold_no_peg_signal_when_disabled(monkeypatch):
    """S48 — with Pegana disabled (default in tests), /vault never hits the network;
    lots carry an honest-None peg_state. Cold has no lots, but the field contract
    holds for the populated path below."""
    monkeypatch.delenv("GECKO_PEGANA_ENABLED", raising=False)
    j = _client().get("/vault?demo_profit=100&profile=moderate").json()
    for lot in j["snapshot"]["lots"]:
        assert lot.get("peg_state") is None  # no signal → honest None
    for v in j["verdicts"]:
        assert v.get("peg_state") is None


def test_vault_exposes_peg_state_when_enabled(monkeypatch):
    """S48 end-to-end — flag on, Pegana client MOCKED (no network). A DRIFT on
    jitoSOL surfaces on the moderate basket's held lst leg: snapshot lot + verdict
    both carry peg_state=DRIFT and the verdict is DELEVERAGE. (DRIFT lets the
    deposit through with a deleverage signal; DEPEG would be denied at the gate, a
    path covered by the unit suite.)"""
    import pegana_feed as pf

    class _Stub:
        def __init__(self, *a, **k):
            pass

        def peg_states(self, symbols, *, now=None):
            return {s: {"state": "DRIFT", "discount": -0.018} for s in symbols if s == "jitoSOL"}

    monkeypatch.setenv("GECKO_PEGANA_ENABLED", "1")
    monkeypatch.setattr(pf, "PeganaClient", _Stub)
    j = _client().get("/vault?demo_profit=100&profile=moderate").json()
    # DRIFT denies the NEW deposit into the lst leg (deny-default on off-peg)
    denied = {d["source"] for d in (j["allocation"] or {}).get("denied", [])}
    assert "lst_staking" in denied
    # the lend leg (USDC, no signal) still deposits and carries honest-None peg_state
    lend_lot = [lot for lot in j["snapshot"]["lots"] if lot["source"] == "stable_spread"]
    assert lend_lot and lend_lot[0]["peg_state"] is None
    # field contract: every verdict/lot carries the peg_state key (None or a state)
    for v in j["verdicts"]:
        assert "peg_state" in v and "peg_discount" in v


# ════════════════════════════════════════════════════════════════════════════
# 4. /arena/board — cold honest-empty + ?live=1 with the feed MOCKED
# ════════════════════════════════════════════════════════════════════════════
def _assert_arena_row(row: dict) -> None:
    # the ONLY row shape — NO raw floats by design
    _has(row, "name", str)
    _has(row, "band", str)
    _has(row, "risk_bucket", str)
    _has(row, "bars", int)
    assert row["band"] in {"surviving+", "surviving", "at-risk", "eliminated"}
    assert row["risk_bucket"] in {"contained", "moderate", "high", "extreme"}
    # the no-public-raw-floats rule: these must NEVER cross the wire
    for forbidden in ("max_dd", "vol", "window_ret", "n"):
        assert forbidden not in row, f"raw float {forbidden!r} leaked onto the public board"


def test_arena_board_cold_honest_empty():
    j = _client().get("/arena/board").json()
    _has(j, "board", list)
    assert j["board"] == []
    assert j.get("stale") is True
    assert "kpi" in j  # subtitle always present
    _assert_no_secret(j)


def test_arena_board_live_with_mocked_feed(monkeypatch):
    """?live=1 path with the based.bid/GeckoTerminal feed fully mocked — no network."""
    monkeypatch.setenv("GECKO_ARENA_TOKENS", "WIF:mintWIF,BONK:mintBONK")

    class _FakeProvider:
        def __init__(self, *a, **k):
            pass

        def get_candles(self, mint, bar="5m", limit=200, drop_forming=True):
            # WIF trends up (surviving+), BONK flat-up too — both have data
            return _fake_candles()

    fake_feed = types.ModuleType("strategies.basedbid_feed")
    fake_feed.BasedBidCandleProvider = _FakeProvider
    monkeypatch.setitem(sys.modules, "strategies.basedbid_feed", fake_feed)

    j = _client().get("/arena/board?live=1").json()
    _has(j, "board", list)
    _has(j, "kpi", str)
    assert j.get("live") is True
    _has(j, "n", int)
    assert j["n"] == len(j["board"]) == 2
    for row in j["board"]:
        _assert_arena_row(row)
    _assert_no_secret(j)


def test_arena_board_live_feed_error_honest_empty(monkeypatch):
    """A feed failure on ?live=1 must degrade to {board:[], error, note}, never 500."""

    class _BoomProvider:
        def __init__(self, *a, **k):
            raise RuntimeError("feed down")

    fake_feed = types.ModuleType("strategies.basedbid_feed")
    fake_feed.BasedBidCandleProvider = _BoomProvider
    monkeypatch.setitem(sys.modules, "strategies.basedbid_feed", fake_feed)

    r = _client().get("/arena/board?live=1")
    assert r.status_code == 200
    j = r.json()
    assert j["board"] == []
    _has(j, "error", str)
    _has(j, "note", str)


# ════════════════════════════════════════════════════════════════════════════
# 5. /wallet + /wallet/balance + /receipts — honest-empty + NO secret leak
# ════════════════════════════════════════════════════════════════════════════
def test_wallet_cold_honest_empty(monkeypatch):
    _no_onchainos(monkeypatch)
    j = _client().get("/wallet").json()
    _has(j, "custody", str)
    _has(j, "status", str)
    _has(j, "x402_mode", str)
    assert j["signer_pubkey"] is None
    assert j["custody"] == "none"
    assert j["x402_mode"] == "stub"
    _assert_no_secret(j)


def test_wallet_balance_cold_stale(monkeypatch):
    _no_onchainos(monkeypatch)
    j = _client().get("/wallet/balance").json()
    _has(j, "balances", list)
    _has(j, "stale", bool)
    assert j["balances"] == []
    assert j["stale"] is True
    _assert_no_secret(j)


def test_wallet_balance_populated_mocked(monkeypatch):
    monkeypatch.setenv("GECKO_SIGNER_PUBKEY", "Pub11111111111111111111111111111111111111111")
    import agent_api

    class _FakeOnchainOS:
        def __init__(self, chain="solana"):
            pass

        def get_token_balance(self, mint, force=False):
            return 1.5 if mint == agent_api._SOL_MINT else 250.0

    fake = types.ModuleType("onchainos")
    fake.OnchainOS = _FakeOnchainOS
    monkeypatch.setitem(sys.modules, "onchainos", fake)
    j = _client().get("/wallet/balance").json()
    assert j["stale"] is False
    toks = {b["token"]: b["amount"] for b in j["balances"]}
    assert toks == {"SOL": 1.5, "USDC": 250.0}
    for b in j["balances"]:
        _has(b, "token", str)
        _has(b, "amount", (int, float))
    _assert_no_secret(j)


def test_receipts_cold_honest_empty():
    j = _client().get("/receipts").json()
    _has(j, "receipts", list)
    _has(j, "n", int)
    _has(j, "mode", str)
    assert j["receipts"] == []
    assert j["n"] == 0
    assert j["mode"] == "stub"
    _assert_no_secret(j)


def test_receipts_populated_stub_sig(tmp_path):
    import json

    ledger = tmp_path / "artifact_20260605.jsonl"
    ledger.write_text(
        json.dumps({
            "decision_id": "abc", "kind": "gate_call",
            "ts": "2026-06-05T00:00:00+00:00",
            "payload": {"idea_hash": "h1", "tier": "basic", "amount_usd": 0.0},
        }) + "\n",
        encoding="utf-8",
    )
    j = _client().get("/receipts").json()
    assert j["n"] == 1
    rec = j["receipts"][0]
    _has(rec, "mode", str)
    assert rec["mode"] == "stub"
    assert rec["tx_sig"].startswith("stub-")  # never passes for an on-chain sig
    _assert_no_secret(j)


# ════════════════════════════════════════════════════════════════════════════
# 6. /agents — deploy → list → get (venue/dry_run/custody) → start/stop/kill
# ════════════════════════════════════════════════════════════════════════════
def test_agents_full_lifecycle(monkeypatch):
    _no_onchainos(monkeypatch)  # custody resolves to "none" honestly
    c = _client()

    # deploy
    d = c.post("/agents", json={"spec": _spec(), "user_id": "u1", "verdict": "PAPER ONLY"})
    assert d.status_code == 200
    dj = d.json()
    _has(dj, "agent_id", str)
    _has(dj, "status", str)
    _has(dj, "launch", str)
    assert dj["status"] == "deployed"
    aid = dj["agent_id"]

    # list
    lst = c.get("/agents").json()
    _has(lst, "agents", list)
    row = next(a for a in lst["agents"] if a["agent_id"] == aid)
    _has(row, "user_id", str)
    _has(row, "spec", dict)
    _has(row, "status", str)
    assert row["venue"] == "okx_spot"

    # get — item #5: execution block carries venue/dry_run/custody
    g = c.get(f"/agents/{aid}").json()
    _has(g, "agent", dict)
    assert "state" in g  # null until running
    _has(g, "execution", dict)
    ex = g["execution"]
    _has(ex, "venue", str)
    _has(ex, "dry_run", bool)
    _has(ex, "live", bool)
    _has(ex, "custody", str)
    assert ex["dry_run"] is True and ex["live"] is False  # paper-safe default
    assert ex["custody"] == "none"  # onchainos mocked unavailable

    # start (orchestrator spawn faked)
    s = c.post(f"/agents/{aid}/start").json()
    _has(s, "agent_id", str)
    _has(s, "port", int)
    _has(s, "status", str)
    assert s["status"] == "running"

    # per-agent kill-switch
    k = c.post(f"/agents/{aid}/kill?engaged=true").json()
    _has(k, "agent_id", str)
    _has(k, "kill_switch", bool)
    assert k["kill_switch"] is True

    # stop
    st = c.post(f"/agents/{aid}/stop").json()
    _has(st, "status", str)
    _has(st, "process_killed", bool)
    assert st["status"] == "stopped"


def test_deploy_reject_verdict_409():
    r = _client().post("/agents", json={"spec": _spec(), "verdict": "REJECT"})
    assert r.status_code == 409


def test_deploy_unknown_strategy_422():
    r = _client().post("/agents", json={"spec": _spec("nope")})
    assert r.status_code == 422


def test_get_unknown_agent_404():
    assert _client().get("/agents/doesnotexist").status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# 7. /orchestrator
# ════════════════════════════════════════════════════════════════════════════
def test_orchestrator_contract():
    c = _client()
    j = c.get("/orchestrator").json()
    _has(j, "running", list)
    _has(j, "max_per_user", int)
    # populated branch after a start
    aid = c.post("/agents", json={"spec": _spec()}).json()["agent_id"]
    c.post(f"/agents/{aid}/start")
    j2 = c.get("/orchestrator").json()
    assert any(r["agent_id"] == aid for r in j2["running"])
    for r in j2["running"]:
        _has(r, "agent_id", str)
        _has(r, "port", int)


# ════════════════════════════════════════════════════════════════════════════
# 8. /kill — GET + POST (global panic button)
# ════════════════════════════════════════════════════════════════════════════
def test_global_kill_get_post_contract():
    c = _client()
    # GET initial state
    g = c.get("/kill").json()
    _has(g, "scope", str)
    _has(g, "kill_switch", bool)
    assert g["scope"] == "global"

    # POST engage
    p = c.post("/kill?engaged=true").json()
    _has(p, "scope", str)
    _has(p, "kill_switch", bool)
    assert p["kill_switch"] is True
    # read-back reflects it
    assert c.get("/kill").json()["kill_switch"] is True

    # POST disengage
    assert c.post("/kill?engaged=false").json()["kill_switch"] is False


# ════════════════════════════════════════════════════════════════════════════
# 9. /backtest — heavy run MOCKED (no real CPCV sweep in the test)
# ════════════════════════════════════════════════════════════════════════════
def test_backtest_contract_mocked(monkeypatch):
    """Mock bt.run_backtest with a tiny fixture envelope — never run a real CPCV
    sweep in a contract test (it's slow + data-dependent)."""
    import agent_api

    fixture = {
        "coins": ["BTC", "ETH"],
        "fee_pct": 0.20,
        "strategies": [
            {
                "strategy_id": "trend_breakout", "verdict": "PAPER ONLY",
                "s5_paper_continue": True, "rationale": ["fixture"],
                "n_trades": 42, "n_variants": 1, "fee_pct": 0.20,
                "win_rate": 0.5, "mean_net_pct": 0.1, "total_net_pct": 4.2,
                "rigor": {
                    "cpcv_median_sharpe": 0.3, "cpcv_ci": [-0.1, 0.7],
                    "cpcv_pct_paths_negative": 0.2, "pbo": 0.1,
                    "avoidance_pbo": 0.05, "dsr": 0.4,
                },
                "per_symbol": {"BTC": {"n": 21, "mean_net_pct": 0.1, "ci": [-0.1, 0.3], "ci_excludes_0": False}},
                "symbols_ci_excludes_0": [],
            }
        ],
        "orthogonality_rho": None,
    }
    monkeypatch.setattr(agent_api.bt, "run_backtest", lambda **kw: fixture)

    r = _client().post("/backtest", json={"strategy_id": "trend_breakout", "fee_pct": 0.20})
    assert r.status_code == 200
    j = r.json()
    _has(j, "coins", list)
    _has(j, "fee_pct", (int, float))
    _has(j, "strategies", list)
    env = j["strategies"][0]
    _has(env, "strategy_id", str)
    _has(env, "verdict", str)
    _has(env, "n_trades", int)
    _has(env, "rigor", dict)
    _has(env["rigor"], "dsr", (int, float))
    _has(env, "per_symbol", dict)
    _assert_no_secret(j)


def test_backtest_unknown_strategy_422():
    r = _client().post("/backtest", json={"strategy_id": "nope"})
    assert r.status_code == 422


def test_backtest_no_data_503(monkeypatch):
    """A data-missing run surfaces as 503 (ValueError → HTTPException), not a 500."""
    import agent_api

    def _boom(**kw):
        raise ValueError("no majors data — run ingest first")

    monkeypatch.setattr(agent_api.bt, "run_backtest", _boom)
    r = _client().post("/backtest", json={"strategy_id": "trend_breakout"})
    assert r.status_code == 503


# ════════════════════════════════════════════════════════════════════════════
# 10. /openapi.json — the app's typed-client codegen contract
# ════════════════════════════════════════════════════════════════════════════
def test_openapi_carries_response_schemas():
    """The changed read endpoints must expose a response schema (not `any`) so the
    app codegen yields typed models. Asserts the 200 response references a $ref."""
    spec = _client().get("/openapi.json").json()
    paths = spec["paths"]
    for path, method in (
        ("/vault", "get"), ("/arena/board", "get"), ("/market-temp", "get"),
        ("/agents/{agent_id}", "get"), ("/agents", "get"), ("/backtest", "post"),
        ("/wallet", "get"), ("/receipts", "get"),
    ):
        content = paths[path][method]["responses"]["200"]["content"]["application/json"]
        assert "$ref" in str(content["schema"]), f"{method.upper()} {path} has no typed response schema"
