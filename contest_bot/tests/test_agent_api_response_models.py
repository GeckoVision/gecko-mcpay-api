"""Response-model coverage for agent_api.

Asserts the new `response_model=` declarations document the known fields for
codegen WITHOUT dropping any real key (extra="allow") and WITHOUT 500-ing on the
honest-empty / variant branches. Both cold and populated states are exercised.

Targeted only — run with:
    python3 -m pytest tests/test_agent_api_response_models.py -q -p no:cacheprovider
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import agent_store as ast_  # noqa: E402


class _FakeSpawner:
    def __init__(self):
        self._alive = {}

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
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    # cold snapshots: point state dir at an empty tmp so market-temp/arena are honest-empty
    monkeypatch.setenv("GECKO_STATE_DIR", str(tmp_path))
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


def _spec(sid="trend_breakout"):
    return {"strategy_id": sid, "universe": ["BTC", "ETH"], "venue": "okx_spot",
            "entry_gates": {"churn_max": 3.0}, "exit": {"tp_pct": 1.0}}


# ── /healthz ──────────────────────────────────────────────────────────────
def test_healthz_shape():
    r = _client().get("/healthz")
    assert r.status_code == 200
    j = r.json()
    assert set(["ok", "data_coins", "n_agents"]).issubset(j)
    assert isinstance(j["data_coins"], list)


# ── /market-temp ──────────────────────────────────────────────────────────
def test_market_temp_cold_honest_empty_keeps_stale():
    # cold (no snapshot) → {temp, label, stale, drivers}; stale must survive coercion
    j = _client().get("/market-temp").json()
    assert j["stale"] is True
    assert j["label"] == "neutral"
    assert "drivers" in j


def test_market_temp_populated_keeps_all_fields(monkeypatch):
    import agent_api  # the handler does `import market_temp as mt` at call time
    import market_temp as mt

    populated = {
        "temp": 0.42, "label": "warm", "btc_net": 0.1, "drivers": ["x"],
        "coins": {"SOL": {"net": 0.3, "mentions": 5}},
        "divergences": ["BTC vs alts"], "updated_at": "2026-06-05T00:00:00+00:00",
    }
    monkeypatch.setattr(mt, "load_snapshot", lambda *a, **k: populated)
    j = _client().get("/market-temp").json()
    # no known field dropped, nested coin sub-shape intact
    for k in populated:
        assert k in j, f"dropped {k}"
    assert j["coins"]["SOL"]["mentions"] == 5
    assert "stale" not in j or j["stale"] is None
    assert agent_api  # silence lint


# ── /arena/board ──────────────────────────────────────────────────────────
def test_arena_board_cold_honest_empty():
    j = _client().get("/arena/board").json()
    assert j["board"] == []
    assert j["stale"] is True
    assert "kpi" in j  # cached branch prepends kpi


def test_arena_board_live_and_error_variants(monkeypatch):
    import arena_score

    monkeypatch.setattr(
        arena_score, "build_board",
        lambda *a, **k: [{"name": "X", "band": "surviving", "risk_bucket": "contained", "bars": 100}],
    )
    live = _client().get("/arena/board?live=1").json()
    assert live["live"] is True
    assert live["board"][0]["risk_bucket"] == "contained"
    assert live["n"] == 1

    # error branch: build_board raises → {board: [], error, note}, no 500
    def _boom(*a, **k):
        raise RuntimeError("feed down")

    monkeypatch.setattr(arena_score, "build_board", _boom)
    err = _client().get("/arena/board?live=1").json()
    assert err["board"] == []
    assert "error" in err and "note" in err


# ── /vault ────────────────────────────────────────────────────────────────
def test_vault_cold_allocation_null():
    j = _client().get("/vault").json()
    assert j["allocation"] is None  # no demo_profit → no allocation
    assert "snapshot" in j and "lots" in j["snapshot"]
    assert "market_temp" in j and "stale" in j["market_temp"]


def test_vault_demo_profit_populates_allocation():
    j = _client().get("/vault?profile=moderate&demo_profit=100").json()
    assert j["allocation"] is not None
    # deposited/denied keys survive
    assert "deposited" in j["allocation"]
    assert "denied" in j["allocation"]


# ── /agents deploy/list/get + control ─────────────────────────────────────
def test_deploy_list_get_keep_fields():
    c = _client()
    d = c.post("/agents", json={"spec": _spec(), "user_id": "u1", "verdict": "PAPER ONLY"})
    assert d.status_code == 200
    aid = d.json()["agent_id"]
    assert d.json()["status"] == "deployed"
    assert d.json()["launch"].startswith("bash launch_agent.sh")

    lst = c.get("/agents").json()
    row = next(a for a in lst["agents"] if a["agent_id"] == aid)
    # spec dict + venue/universe survive coercion
    assert row["spec"]["entry_gates"]["churn_max"] == 3.0
    assert row["venue"] == "okx_spot"
    assert row["universe"] == ["BTC", "ETH"]
    assert row["verdict"] == "PAPER ONLY"

    g = c.get(f"/agents/{aid}").json()
    assert g["agent"]["strategy_id"] == "trend_breakout"
    assert g["state"] is None


def test_get_agent_state_mirror_survives():
    c = _client()
    aid = c.post("/agents", json={"spec": _spec()}).json()["agent_id"]
    ast_.AgentStateStore().put_state(aid, {"poll_count": 9, "positions": []})
    g = c.get(f"/agents/{aid}").json()
    assert g["state"]["state"]["poll_count"] == 9
    assert g["state"]["agent_id"] == aid


def test_start_stop_kill_orchestrator():
    c = _client()
    aid = c.post("/agents", json={"spec": _spec()}).json()["agent_id"]

    s = c.post(f"/agents/{aid}/start").json()
    assert s["status"] == "running" and isinstance(s["port"], int)

    # second start → already=True must survive
    s2 = c.post(f"/agents/{aid}/start").json()
    assert s2["already"] is True

    orc = c.get("/orchestrator").json()
    assert any(r["agent_id"] == aid for r in orc["running"])
    assert "max_per_user" in orc

    k = c.post(f"/agents/{aid}/kill").json()
    assert k["kill_switch"] is True and k["agent_id"] == aid

    st = c.post(f"/agents/{aid}/stop").json()
    assert st["status"] == "stopped" and st["process_killed"] is True


def test_global_kill_get_and_post():
    c = _client()
    assert c.post("/kill?engaged=true").json() == {"scope": "global", "kill_switch": True}
    assert c.get("/kill").json()["kill_switch"] is True
    assert c.post("/kill?engaged=false").json()["kill_switch"] is False


# ── /backtest empty + populated (deferred-shape safety) ───────────────────
def test_backtest_unknown_strategy_422():
    assert _client().post("/backtest", json={"strategy_id": "nope"}).status_code == 422


def test_backtest_empty_envelope_variant(monkeypatch):
    import backtest_strategy as bt

    empty = {
        "coins": ["BTC"], "fee_pct": 0.2,
        "strategies": [{"strategy_id": "trend_breakout", "n_trades": 0, "verdict": None, "note": "0 trades"}],
        "orthogonality_rho": None,
    }
    monkeypatch.setattr(bt, "run_backtest", lambda **k: empty)
    j = _client().post("/backtest", json={"strategy_id": "trend_breakout"}).json()
    env = j["strategies"][0]
    assert env["verdict"] is None
    assert env["note"] == "0 trades"
    assert env["n_trades"] == 0
    assert j["orthogonality_rho"] is None


def test_backtest_populated_envelope_keeps_nested(monkeypatch):
    import backtest_strategy as bt

    populated = {
        "coins": ["BTC", "ETH"], "fee_pct": 0.2,
        "strategies": [{
            "strategy_id": "trend_breakout", "verdict": "PAPER ONLY", "s5_paper_continue": True,
            "rationale": ["r1"], "n_trades": 42, "n_variants": 7, "fee_pct": 0.2,
            "win_rate": 0.51, "mean_net_pct": 0.03, "total_net_pct": 1.2,
            "rigor": {"cpcv_median_sharpe": 0.5, "cpcv_ci": [0.1, 0.9],
                      "cpcv_pct_paths_negative": 0.2, "pbo": 0.3, "avoidance_pbo": 0.25, "dsr": 0.4},
            "per_symbol": {"BTC": {"n": 20, "mean_net_pct": 0.04, "ci": [0.01, 0.07], "ci_excludes_0": True}},
            "symbols_ci_excludes_0": ["BTC"],
        }],
        "orthogonality_rho": -0.17,
    }
    monkeypatch.setattr(bt, "run_backtest", lambda **k: populated)
    j = _client().post("/backtest", json={"strategy_id": "trend_breakout"}).json()
    env = j["strategies"][0]
    # deep nesting must survive coercion
    assert env["rigor"]["avoidance_pbo"] == 0.25
    assert env["per_symbol"]["BTC"]["ci_excludes_0"] is True
    assert env["per_symbol"]["BTC"]["ci"] == [0.01, 0.07]
    assert env["symbols_ci_excludes_0"] == ["BTC"]
    assert j["orthogonality_rho"] == -0.17
