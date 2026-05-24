"""TDD for the Birdeye tape source adapter.

BIRDEYE_API_KEY is absent in this env, so we cannot capture a live response.
We TDD the parser against the DOCUMENTED shape fixture
(tests/fixtures/tape/birdeye_ohlcv_shape_sample.json) and assert the
key-missing path raises cleanly (no fabricated data, no network).

When the key lands, the first step is to overwrite the fixture with a REAL
capture and re-run this file (Patterns B & E).
"""

from __future__ import annotations

import importlib.util
import json
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_BE = os.path.join(_REPO, "scripts", "calibration", "tape", "birdeye_source.py")
_FIXTURE = os.path.join(_REPO, "tests", "fixtures", "tape", "birdeye_ohlcv_shape_sample.json")

_spec = importlib.util.spec_from_file_location("tape_birdeye_source", _BE)
assert _spec and _spec.loader
be = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(be)


def _load_fixture() -> dict:
    with open(_FIXTURE) as f:
        return json.load(f)


def test_parse_documented_shape_to_canonical_ms() -> None:
    raw = _load_fixture()
    parsed = be.parse_response(raw)
    assert len(parsed) == len(raw["data"]["items"])
    c = parsed[0]
    assert set(c) == {"ts", "open", "high", "low", "close", "volume"}
    # unixTime is in SECONDS in Birdeye; canonical tape is ms
    assert c["ts"] == float(raw["data"]["items"][0]["unixTime"]) * 1000.0
    assert c["close"] == float(raw["data"]["items"][0]["c"])
    assert c["volume"] == float(raw["data"]["items"][0]["v"])


def test_parse_sorts_ascending() -> None:
    parsed = be.parse_response(_load_fixture())
    ts = [c["ts"] for c in parsed]
    assert ts == sorted(ts)


def test_parse_rejects_unsuccessful() -> None:
    with pytest.raises(be.BirdeyeSourceError):
        be.parse_response({"success": False, "message": "blacklisted"})


def test_collect_history_raises_when_key_missing(monkeypatch) -> None:
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    with pytest.raises(be.BirdeyeKeyMissing):
        be.collect_history("SomeMint", "5m", lookback_s=3600)


def test_collect_history_with_injected_fetcher_paginates() -> None:
    """With a fake fetcher (test-only bypass of the key gate) the collector walks
    time_from forward and de-duplicates by ts."""
    raw = _load_fixture()
    pages = [raw, {"success": True, "data": {"items": []}}]
    calls: list[dict] = []

    def fake_fetch(url: str, params: dict, headers: dict) -> dict:
        calls.append(params)
        return pages[min(len(calls) - 1, len(pages) - 1)]

    candles = be.collect_history(
        "SomeMint",
        "5m",
        lookback_s=600,
        now_s=1779545700,
        fetcher=fake_fetch,
        sleeper=lambda _s: None,
    )
    assert [c["ts"] for c in candles] == [1779544800000.0, 1779545100000.0]
    assert calls[0]["currency"] == "usd"
    assert calls[0]["type"] == "5m"


def test_api_key_present_reflects_env(monkeypatch) -> None:
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    assert be.api_key_present() is False
    monkeypatch.setenv("BIRDEYE_API_KEY", "x")
    assert be.api_key_present() is True
