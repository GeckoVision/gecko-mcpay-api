"""market_temp — news/sentiment → risk-on/off read. Pure, no network."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from datetime import UTC, datetime, timedelta  # noqa: E402

from market_temp import (  # noqa: E402
    CoinTemp,
    compute_market_temp,
    from_okx_sentiment,
    risk_off_gate,
)


def test_parse_okx_sentiment_shape():
    resp = {"data": [{"details": [
        {"ccy": "BTC", "mentionCnt": "2749", "sentiment": {"bullishRatio": "0.23", "bearishRatio": "0.44"}},
        {"ccy": "SOL", "mentionCnt": "705", "sentiment": {"bullishRatio": "0.43", "bearishRatio": "0.16"}},
    ]}]}
    coins = from_okx_sentiment(resp)
    assert coins["BTC"].net == -0.21 and coins["SOL"].mentions == 705


def test_risk_off_when_btc_bearish_plus_macro():
    coins = {"BTC": CoinTemp("BTC", 0.23, 0.44, 2749)}
    mt = compute_market_temp(coins, headlines=["Iran conflict escalates", "OECD warns of recession"])
    assert mt.label == "risk_off" and mt.temp < -0.25
    assert any("conflict" in d for d in mt.drivers)


def test_risk_on_when_bullish_no_macro():
    coins = {"BTC": CoinTemp("BTC", 0.55, 0.10, 1000)}
    mt = compute_market_temp(coins, headlines=["spot ETF inflows surge to ATH"])
    assert mt.label in ("warm", "risk_on") and mt.temp > 0.2


def test_neutral_when_balanced():
    coins = {"BTC": CoinTemp("BTC", 0.30, 0.30, 500)}
    mt = compute_market_temp(coins, headlines=[])
    assert mt.label == "neutral"


def test_sentiment_price_divergence_flagged():
    coins = {
        "BTC": CoinTemp("BTC", 0.23, 0.44, 2749),
        "SOL": CoinTemp("SOL", 0.43, 0.16, 705),
    }
    mt = compute_market_temp(coins, headlines=["recession risk"], price_moves={"SOL": -10.1})
    assert any("SOL" in d and "counter-trend" in d for d in mt.divergences)


def test_btc_anchors_temp_not_the_bullish_alts():
    # alts net-bullish but BTC bearish + macro → still risk-off (BTC is the anchor)
    coins = {
        "BTC": CoinTemp("BTC", 0.23, 0.44, 2749),
        "SOL": CoinTemp("SOL", 0.43, 0.16, 705),
        "XRP": CoinTemp("XRP", 0.54, 0.11, 96),
    }
    mt = compute_market_temp(coins, headlines=["war", "recession"])
    assert mt.label == "risk_off"  # not warmed up by the bullish alts


def test_as_dict_serializable():
    import json

    coins = {"BTC": CoinTemp("BTC", 0.23, 0.44, 2749)}
    json.dumps(compute_market_temp(coins).as_dict())


def test_snapshot_roundtrip(tmp_path):
    import market_temp as m

    coins = {"BTC": CoinTemp("BTC", 0.23, 0.44, 2749)}
    p = str(tmp_path / "mt.json")
    m.save_snapshot(compute_market_temp(coins, headlines=["recession"]), path=p)
    snap = m.load_snapshot(path=p)
    assert snap["label"] == "risk_off" and "updated_at" in snap


def test_load_snapshot_neutral_when_absent(tmp_path):
    import market_temp as m

    snap = m.load_snapshot(path=str(tmp_path / "nope.json"))
    assert snap["label"] == "neutral" and snap["stale"] is True


def _snap(temp, label="x", age_s=0.0, **extra):
    ts = (datetime.now(UTC) - timedelta(seconds=age_s)).isoformat()
    return {"temp": temp, "label": label, "updated_at": ts, **extra}


def test_gate_blocks_when_risk_off():
    ok, reason = risk_off_gate(_snap(-0.57, "risk_off"), floor=-0.25)
    assert ok is False and "risk_off" in reason


def test_gate_passes_when_above_floor():
    ok, reason = risk_off_gate(_snap(-0.10, "cool"), floor=-0.25)
    assert ok is True and "ok" in reason


def test_gate_failopen_on_stale_default_snapshot():
    # load_snapshot's cold-start default carries stale=True
    ok, reason = risk_off_gate({"temp": 0.0, "label": "neutral", "stale": True})
    assert ok is True and "no_snapshot" in reason


def test_gate_failopen_when_snapshot_too_old():
    # temp is risk_off, but the snapshot is older than max_age → fail-open, don't block on dead data
    ok, reason = risk_off_gate(_snap(-0.57, "risk_off", age_s=99999), floor=-0.25, max_age_s=21600)
    assert ok is True and "stale" in reason


def test_gate_failopen_on_unparseable_temp():
    ok, reason = risk_off_gate({"temp": "nope", "updated_at": datetime.now(UTC).isoformat()})
    assert ok is True and "unparseable" in reason


def test_gate_boundary_exactly_at_floor_blocks():
    # temp == floor → blocked (≤, the falling-knife belt is inclusive)
    ok, _ = risk_off_gate(_snap(-0.25, "risk_off"), floor=-0.25)
    assert ok is False


def test_api_market_temp_endpoint(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("GECKO_STATE_DIR", str(tmp_path))  # isolate snapshot path
    import agent_api
    from fastapi.testclient import TestClient

    r = TestClient(agent_api.app).get("/market-temp")
    assert r.status_code == 200 and "label" in r.json()
