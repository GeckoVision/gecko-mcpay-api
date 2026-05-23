"""TDD for the OKX tape source adapter against a CAPTURED REAL fixture.

The fixture tests/fixtures/tape/okx_history_candles_PYTH-USDT_5m_sample.json was
captured live from OKX public REST on 2026-05-23; row[0] is a forming bar
(confirm == "0"). We assert the parser drops it, reads USD volume from
volCcyQuote, and that pagination walks strictly backward.
"""

from __future__ import annotations

import importlib.util
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_OKX = os.path.join(_REPO, "scripts", "calibration", "tape", "okx_source.py")
_FIXTURE = os.path.join(
    _REPO, "tests", "fixtures", "tape", "okx_history_candles_PYTH-USDT_5m_sample.json"
)

_spec = importlib.util.spec_from_file_location("tape_okx_source", _OKX)
assert _spec and _spec.loader
okx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(okx)


def _load_fixture() -> dict:
    with open(_FIXTURE) as f:
        return json.load(f)


def test_fixture_has_a_forming_bar() -> None:
    """Guard: the fixture must contain a forming bar so the drop test is real."""
    raw = _load_fixture()
    assert raw["code"] == "0"
    confirms = [str(r[8]) for r in raw["data"]]
    assert "0" in confirms, "fixture should include a forming bar to exercise drop"


def test_parse_drops_forming_bar() -> None:
    raw = _load_fixture()
    parsed = okx.parse_response(raw)
    assert len(parsed) == len(raw["data"]) - 1  # exactly the forming bar removed
    kept_ts = {c["ts"] for c in parsed}
    forming_ts = float(next(r[0] for r in raw["data"] if str(r[8]) == "0"))
    assert forming_ts not in kept_ts


def test_parse_canonical_shape_and_usd_volume() -> None:
    raw = _load_fixture()
    parsed = okx.parse_response(raw)
    c = parsed[0]
    assert set(c) == {"ts", "open", "high", "low", "close", "volume"}
    assert all(isinstance(v, float) for v in c.values())
    # USD volume must be volCcyQuote (row index 7), NOT base vol (index 5)
    confirmed = [r for r in raw["data"] if str(r[8]) == "1"]
    by_ts = {float(r[0]): r for r in confirmed}
    row = by_ts[c["ts"]]
    assert c["volume"] == float(row[7])
    assert c["volume"] != float(row[5]) or float(row[5]) == float(row[7])


def test_parse_rejects_bad_code() -> None:
    import pytest

    with pytest.raises(okx.OkxSourceError):
        okx.parse_response({"code": "50011", "msg": "rate limited", "data": []})


def test_instrument_missing_detection() -> None:
    assert okx.is_instrument_missing({"code": "51001", "msg": "x", "data": []})
    assert not okx.is_instrument_missing({"code": "0", "data": []})


def test_okx_instrument_mapping() -> None:
    assert okx.okx_instrument("pyth") == "PYTH-USDT"
    assert okx.okx_instrument("BTC") == "BTC-USDT"


def test_fetch_history_paginates_backward_with_fake_fetcher() -> None:
    """Two synthetic pages: the second must be requested with after=<page1 oldest>
    and the merged result must be ascending + de-duplicated."""
    page1 = {
        "code": "0",
        "data": [
            ["3000", "1", "1", "1", "1", "1", "1", "10", "1"],
            ["2000", "1", "1", "1", "1", "1", "1", "10", "1"],
        ],
    }
    page2 = {
        "code": "0",
        "data": [
            ["2000", "1", "1", "1", "1", "1", "1", "10", "1"],  # overlap -> dedup
            ["1000", "1", "1", "1", "1", "1", "1", "10", "1"],
        ],
    }
    calls: list[dict] = []
    seq = [page1, page2]

    def fake_fetch(url: str, params: dict) -> dict:
        calls.append(params)
        return seq[len(calls) - 1]

    candles, missing = okx.fetch_history(
        "PYTH",
        "5m",
        lookback_ms=2500,  # spans from ts 3000 back past 1000
        max_calls=2,
        fetcher=fake_fetch,
        sleeper=lambda _s: None,
    )
    assert not missing
    assert [c["ts"] for c in candles] == [1000.0, 2000.0, 3000.0]  # ascending, deduped
    assert "after" not in calls[0]
    assert calls[1]["after"] == 2000  # page2 cursor = page1 oldest ts


def test_fetch_history_routes_missing_instrument() -> None:
    def fake_fetch(url: str, params: dict) -> dict:
        return {"code": "51001", "msg": "Instrument ID does not exist", "data": []}

    candles, missing = okx.fetch_history(
        "POPCAT", "5m", lookback_ms=1000, fetcher=fake_fetch, sleeper=lambda _s: None
    )
    assert missing
    assert candles == []
