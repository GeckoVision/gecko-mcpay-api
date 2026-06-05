"""Phase 3 — arena survival scoring + public bucketing (no raw floats on the wire). Mocked."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import arena_score as asc  # noqa: E402


class _FakeProvider:
    """Returns canned candle series per token mint (ascending closes)."""

    def __init__(self, series: dict[str, list[float]]):
        self.series = series

    def get_candles(self, mint, bar="5m", limit=200, drop_forming=True):
        closes = self.series.get(mint)
        if not closes:
            return []
        return [{"close": c} for c in closes]


def test_survival_bands():
    assert asc.survival_band(0.05, 0.10) == "surviving+"   # contained dd, up
    assert asc.survival_band(0.05, -0.10) == "surviving"    # contained dd, down
    assert asc.survival_band(0.35, 0.0) == "at-risk"        # deep dd survived
    assert asc.survival_band(0.60, 0.0) == "eliminated"     # blew up


def test_build_board_public_strips_raw_floats():
    prov = _FakeProvider({
        "M_SAFE": [1.0, 1.05, 1.10],            # up, tiny dd → surviving+
        "M_BLOWUP": [1.0, 1.0, 0.4],            # 60% dd → eliminated
    })
    board = asc.build_board(prov, {"SAFE": "M_SAFE", "BLOWUP": "M_BLOWUP"}, public=True)
    # survival-first ranking: SAFE before BLOWUP
    assert [r["name"] for r in board] == ["SAFE", "BLOWUP"]
    assert board[0]["band"] == "surviving+" and board[1]["band"] == "eliminated"
    # PUBLIC rows must NOT leak raw floats
    for r in board:
        assert set(r) == {"name", "band", "risk_bucket", "bars"}
        assert "max_dd" not in r and "window_ret" not in r and "vol" not in r


def test_build_board_internal_keeps_raw():
    prov = _FakeProvider({"M": [1.0, 1.2, 1.1]})
    rows = asc.build_board(prov, {"T": "M"}, public=False)
    assert "max_dd" in rows[0] and "window_ret" in rows[0]  # raw kept for diagnostics


def test_no_data_token_skipped():
    prov = _FakeProvider({"M": []})  # pre-graduation / no pool
    assert asc.build_board(prov, {"T": "M"}) == []


def test_api_arena_board_endpoint(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("GECKO_STATE_DIR", str(tmp_path))
    import agent_api

    # stub the feed so the endpoint test makes no network call
    import arena_score
    from fastapi.testclient import TestClient
    monkeypatch.setattr(arena_score, "build_board", lambda *a, **k: [{"name": "X", "band": "surviving", "risk_bucket": "contained", "bars": 100}])
    r = TestClient(agent_api.app).get("/arena/board")
    assert r.status_code == 200
    body = r.json()
    assert body["board"][0]["band"] == "surviving" and "survival" in body["kpi"]
