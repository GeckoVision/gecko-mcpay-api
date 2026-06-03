"""Phase-1 backtest API — light tests.

Per the light-tests rule we do NOT run the full 27-variant sweep here (that's a
manual/integration check). We test the pure pieces: the verdict envelope shape
and the FastAPI routing/validation with run_backtest stubbed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))
_RIGOR = _CB.parent / "scripts" / "calibration"
if str(_RIGOR) not in sys.path:
    sys.path.insert(0, str(_RIGOR))

import backtest_strategy as bt  # noqa: E402
import overfitting_rigor as ofr  # noqa: E402


def _fake_result() -> dict:
    cpcv = ofr.CPCVResult(8, 2, 28, [0.1, -0.2], -0.39, -0.84, 0.15, 0.79, 30.0)
    pbo = ofr.PBOResult(0.18, 28, 27, -0.5)
    avoid = ofr.PBOResult(0.31, 28, 27, 0.1)
    dsr = ofr.DSRResult(0.006, 0.1, 0.4, 27, 45, 0.0, 3.0)
    verdict = ofr.make_verdict("trend_breakout", cpcv, dsr, pbo, -7.0, -0.8)
    return {
        "strategy": "trend_breakout", "n_trades": 45, "n_variants": 27, "fee_pct": 0.20,
        "mean_net_pct": -0.129, "total_net_pct": -5.8, "win_rate": 0.444,
        "sym_ci": {"BTC": {"n": 1, "mean": 0.35, "ci": (float("nan"), float("nan")), "excl_0": False},
                   "SOL": {"n": 16, "mean": -0.072, "ci": (-0.41, 0.27), "excl_0": False}},
        "sym_ci_excludes_0": 0, "cpcv": cpcv, "pbo": pbo, "avoid_pbo": avoid, "dsr": dsr,
        "verdict": verdict, "s5_paper_continue": False, "trades": [],
    }


def test_verdict_envelope_is_json_serializable_with_expected_keys():
    import json

    env = bt.verdict_envelope(_fake_result())
    json.dumps(env)  # must not raise
    assert env["strategy_id"] == "trend_breakout"
    assert env["verdict"] in ("DEPLOY", "PAPER ONLY", "REJECT")
    assert set(env["rigor"]) >= {"pbo", "avoidance_pbo", "dsr", "cpcv_median_sharpe"}
    assert env["rigor"]["pbo"] == 0.18
    assert "BTC" in env["per_symbol"] and env["per_symbol"]["SOL"]["n"] == 16


def test_verdict_envelope_handles_zero_trades():
    env = bt.verdict_envelope({"strategy": "x", "n_trades": 0, "verdict": None, "note": "0 trades"})
    assert env["verdict"] is None and env["n_trades"] == 0


def test_api_rejects_unknown_strategy():
    import backtest_api
    from fastapi.testclient import TestClient

    c = TestClient(backtest_api.app)
    r = c.post("/backtest", json={"strategy_id": "nope"})
    assert r.status_code == 422


def test_api_routes_to_run_backtest(monkeypatch):
    import backtest_api
    from fastapi.testclient import TestClient

    captured = {}

    def stub(**kwargs):
        captured.update(kwargs)
        return {"strategies": [{"strategy_id": kwargs["strategy_id"], "verdict": "REJECT"}]}

    monkeypatch.setattr(backtest_api.bt, "run_backtest", stub)
    c = TestClient(backtest_api.app)
    r = c.post("/backtest", json={"strategy_id": "trend_breakout", "entry_gates": {"churn_max": 3.0}})
    assert r.status_code == 200
    assert r.json()["strategies"][0]["verdict"] == "REJECT"
    assert captured["entry_gates"] == {"churn_max": 3.0}  # override threaded through


def test_api_503_when_data_missing(monkeypatch):
    import backtest_api
    from fastapi.testclient import TestClient

    def boom(**kwargs):
        raise ValueError("no majors data — run ingest first")

    monkeypatch.setattr(backtest_api.bt, "run_backtest", boom)
    c = TestClient(backtest_api.app)
    r = c.post("/backtest", json={"strategy_id": "trend_breakout"})
    assert r.status_code == 503


def test_healthz():
    import backtest_api
    from fastapi.testclient import TestClient

    c = TestClient(backtest_api.app)
    r = c.get("/healthz")
    assert r.status_code == 200 and "coins" in r.json()
